import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.test import APIRequestFactory

from travel_api.exceptions import custom_exception_handler
from travel_api.notifications import notify_user
from travel_api.permissions import IsAdminOrReadOnly

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


class TestExceptionHandler:
    def test_django_validation_error_becomes_400(self):
        response = custom_exception_handler(DjangoValidationError({'field': 'bad'}), {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error']['message'] == 'Validation failed.'
        assert response.data['error']['details'] == {'field': ['bad']}

    def test_integrity_error_becomes_409(self):
        response = custom_exception_handler(IntegrityError('dup'), {})
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['error']['status_code'] == 409

    def test_detail_message_is_promoted(self):
        response = custom_exception_handler(NotFound('Nope.'), {})
        assert response.data['error']['message'] == 'Nope.'

    def test_unhandled_exceptions_become_json_500(self):
        response = custom_exception_handler(RuntimeError('boom'), {})
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.data['error']['message'] == 'An unexpected error occurred.'
        assert 'boom' not in str(response.data)

    def test_debug_mode_shows_django_error_page(self, settings):
        settings.DEBUG = True
        assert custom_exception_handler(RuntimeError('boom'), {}) is None


class TestIsAdminOrReadOnly:
    def check(self, method, user):
        request = getattr(factory, method)('/')
        request.user = user
        return IsAdminOrReadOnly().has_permission(request, None)

    def test_rules(self, user, admin_user):
        assert self.check('get', AnonymousUser())
        assert not self.check('post', AnonymousUser())
        assert not self.check('post', user)
        assert self.check('post', admin_user)


class TestNotifications:
    def test_skips_users_without_email(self, make_user):
        assert notify_user(make_user('noemail', email=''), 'Hi', 'Body') is False

    def test_sends(self, user, mailoutbox):
        assert notify_user(user, 'Hi', 'Body') is True
        assert mailoutbox[0].subject == 'Hi'


class TestApiSurface:
    def test_api_root_lists_viewsets(self, authenticated_client):
        response = authenticated_client.get(reverse('api-root'))
        assert response.status_code == status.HTTP_200_OK
        assert {'itineraries', 'destinations', 'bookings', 'budgets', 'reviews', 'analytics'} <= set(response.data)

    def test_all_routes_are_versioned(self):
        assert reverse('itinerary-list').startswith('/api/v1/')
        assert reverse('budgets:budget-expenses', kwargs={'budget_id': 1}).startswith('/api/v1/')

    def test_openapi_schema_generates(self, api_client):
        assert api_client.get(reverse('schema')).status_code == status.HTTP_200_OK


class TestOwnershipPermissions:
    def request(self, method, user):
        request = getattr(factory, method)('/')
        request.user = user
        return request

    def test_booking_account_and_review_ownership(self, user, other_user, itinerary, accommodation, destination):
        from accounts.permissions import IsAccountOwner
        from bookings.models import Booking
        from bookings.permissions import IsBookingOwner
        from reviews.models import Review
        from reviews.permissions import IsReviewAuthorOrReadOnly

        booking = Booking.objects.create(user=user, itinerary=itinerary, booking_type='ACCOMMODATION',
                                         accommodation=accommodation, total_price=10)
        review = Review.objects.create(user=user, destination=destination, rating=5, comment='Great')

        assert IsBookingOwner().has_object_permission(self.request('get', user), None, booking)
        assert not IsBookingOwner().has_object_permission(self.request('get', other_user), None, booking)
        assert IsAccountOwner().has_object_permission(self.request('get', user), None, user)
        assert not IsAccountOwner().has_object_permission(self.request('get', other_user), None, user)
        assert IsReviewAuthorOrReadOnly().has_object_permission(self.request('get', other_user), None, review)
        assert not IsReviewAuthorOrReadOnly().has_object_permission(self.request('patch', other_user), None, review)
        assert IsReviewAuthorOrReadOnly().has_object_permission(self.request('patch', user), None, review)
