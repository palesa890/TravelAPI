from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIRequestFactory

from bookings.models import Booking
from budgets.models import Budget
from destinations.models import Destination
from itineraries.models import Collaboration, Itinerary
from itineraries.permissions import CanEditItinerary, IsTripOwner, IsTripOwnerOrCollaborator

pytestmark = pytest.mark.django_db

LIST = reverse('itinerary-list')
UPCOMING = reverse('itinerary-upcoming-trips')
MINE = reverse('itineraries:itinerary-list-create')
SEARCH = reverse('itineraries:trip-search')
TODAY = date.today()


def detail(pk):
    return reverse('itinerary-detail', kwargs={'pk': pk})


def titles(response):
    return [t['title'] for t in response.data['results']]


def future(days):
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture
def editor(make_user, itinerary, add_collaborator):
    user = make_user('editor')
    add_collaborator(itinerary, user, Collaboration.Role.EDITOR)
    return user


@pytest.fixture
def viewer(make_user, itinerary, add_collaborator):
    user = make_user('viewer')
    add_collaborator(itinerary, user, Collaboration.Role.VIEWER)
    return user


class TestCreate:
    def payload(self, destination, **overrides):
        data = {'title': 'Summer', 'destination': destination.id, 'start_date': future(10), 'end_date': future(12)}
        data.update(overrides)
        return data

    def test_create_sets_owner_and_generates_plans(self, authenticated_client, user, destination):
        response = authenticated_client.post(LIST, self.payload(destination, generate_daily_plans=True))
        assert response.status_code == status.HTTP_201_CREATED
        trip = Itinerary.objects.get(pk=response.data['id'])
        assert trip.owner == user
        assert list(trip.daily_plans.values_list('day_number', flat=True)) == [1, 2, 3]

    def test_list_create_view(self, authenticated_client, destination, itinerary):
        response = authenticated_client.post(MINE, self.payload(destination))
        assert response.status_code == status.HTTP_201_CREATED
        listing = authenticated_client.get(f'{MINE}?search=summer')
        assert titles(listing) == ['Summer']

    def test_requires_authentication(self, api_client):
        assert api_client.get(LIST).status_code == status.HTTP_401_UNAUTHORIZED


class TestReadAndFilter:
    @pytest.fixture
    def trips(self, user, destination, itinerary):
        paris = Destination.objects.create(name='Paris', city='Paris', country='France', description='x')
        past = Itinerary.objects.create(title='Old Paris', owner=user, destination=paris, status='COMPLETED',
                                        start_date=TODAY - timedelta(days=60), end_date=TODAY - timedelta(days=55))
        Budget.objects.create(itinerary=itinerary, total_budget=1000)
        Budget.objects.create(itinerary=past, total_budget=3000)
        return {'bali': itinerary, 'paris': past}

    def test_list_includes_shared_trips_only(self, other_client, itinerary, other_user, add_collaborator):
        assert other_client.get(LIST).data['count'] == 0
        add_collaborator(itinerary, other_user)
        assert titles(other_client.get(LIST)) == ['Bali Trip']

    def test_retrieve_detail(self, authenticated_client, itinerary):
        Budget.objects.create(itinerary=itinerary, total_budget=500)
        response = authenticated_client.get(detail(itinerary.id))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['my_role'] == 'OWNER'
        assert response.data['is_upcoming'] is True
        assert response.data['destination']['name'] == 'Bali'
        assert response.data['budget']['total_budget'] == '500.00'
        assert response.data['duration_days'] == 6

    def test_stranger_gets_404(self, other_client, itinerary):
        assert other_client.get(detail(itinerary.id)).status_code == status.HTTP_404_NOT_FOUND

    def test_viewer_can_read(self, client_for, viewer, itinerary):
        response = client_for(viewer).get(detail(itinerary.id))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['my_role'] == 'VIEWER'


class TestUpdateAndDelete:
    def test_owner_and_editor_can_update_viewer_cannot(
            self, authenticated_client, client_for, editor, viewer, itinerary):
        assert authenticated_client.patch(detail(itinerary.id), {'title': 'Owner edit'}).status_code == 200
        assert client_for(editor).patch(detail(itinerary.id), {'title': 'Editor edit'}).status_code == 200
        response = client_for(viewer).patch(detail(itinerary.id), {'title': 'Viewer edit'})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['error']['message'] == 'You need editor access to modify this itinerary.'

    def test_only_owner_can_delete(self, authenticated_client, client_for, editor, itinerary):
        assert client_for(editor).delete(detail(itinerary.id)).status_code == status.HTTP_403_FORBIDDEN
        assert authenticated_client.delete(detail(itinerary.id)).status_code == status.HTTP_204_NO_CONTENT


class TestPermissionClasses:
    factory = APIRequestFactory()

    def request(self, method, user):
        request = getattr(self.factory, method)('/')
        request.user = user
        return request

    def test_matrix(self, user, itinerary, editor, viewer, other_user):
        cases = {
            # (permission, method): {user: allowed}
            (IsTripOwner, 'get'): {user: True, editor: False, viewer: False, other_user: False},
            (IsTripOwnerOrCollaborator, 'get'): {user: True, editor: True, viewer: True, other_user: False},
            (IsTripOwnerOrCollaborator, 'patch'): {user: True, editor: False, viewer: False, other_user: False},
            (CanEditItinerary, 'get'): {user: True, editor: True, viewer: True, other_user: False},
            (CanEditItinerary, 'patch'): {user: True, editor: True, viewer: False, other_user: False},
        }
        for (permission, method), expectations in cases.items():
            for who, allowed in expectations.items():
                result = permission().has_object_permission(self.request(method, who), None, itinerary)
                assert result is allowed, (permission.__name__, method, who.username)

    def test_works_on_related_objects_and_rejects_unrelated(self, user, itinerary):
        budget = Budget.objects.create(itinerary=itinerary, total_budget=1)
        request = self.request('patch', user)
        assert CanEditItinerary().has_object_permission(request, None, budget)
        assert not CanEditItinerary().has_object_permission(request, None, object())
        assert not IsTripOwnerOrCollaborator().has_object_permission(request, None, object())


class TestModels:
    def test_str_and_properties(self, itinerary, viewer):
        assert str(itinerary) == 'Bali Trip'
        assert itinerary.duration_days == 6
        assert itinerary.is_upcoming()
        assert str(Collaboration.objects.get(user=viewer)) == 'viewer - Bali Trip (VIEWER)'
        assert Itinerary(title='x').duration_days == 0

    def test_clean(self, itinerary):
        itinerary.end_date = itinerary.start_date - timedelta(days=1)
        with pytest.raises(ValidationError):
            itinerary.clean()

    def test_total_booking_cost_ignores_cancelled(self, itinerary, user, accommodation):
        Booking.objects.create(user=user, itinerary=itinerary, booking_type='ACCOMMODATION',
                               accommodation=accommodation, total_price=Decimal('10'))
        Booking.objects.create(user=user, itinerary=itinerary, booking_type='ACCOMMODATION',
                               accommodation=accommodation, total_price=Decimal('99'), status='CANCELLED')
        assert itinerary.total_booking_cost() == Decimal('10')
