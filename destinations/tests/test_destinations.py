from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status

from bookings.models import Activity
from destinations.models import Category, Destination
from reviews.models import Review

pytestmark = pytest.mark.django_db

LIST = reverse('destination-list')
SEARCH = reverse('destinations:destination-search')
FAVORITES = reverse('destination-favorites')


def detail(pk):
    return reverse('destination-detail', kwargs={'pk': pk})


def names(response):
    return [d['name'] for d in response.data['results']]


@pytest.fixture
def catalogue(category):
    city = Category.objects.create(name='City')
    return {
        'bali': Destination.objects.create(name='Bali', city='Denpasar', country='Indonesia', description='Beaches',
                                           category=category, climate='TROPICAL', average_cost_per_day=80),
        'paris': Destination.objects.create(name='Paris', city='Paris', country='France', description='Art and food',
                                            category=city, climate='TEMPERATE', average_cost_per_day=180),
        'dubai': Destination.objects.create(name='Dubai', city='Dubai', country='UAE', description='Desert luxury',
                                            category=city, climate='DRY', average_cost_per_day=400),
    }


class TestDestinationViewSet:
    def test_list_is_public_and_uses_large_pagination(self, api_client, catalogue):
        response = api_client.get(LIST)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 3
        assert names(response) == ['Bali', 'Dubai', 'Paris']

    def test_long_descriptions_are_truncated_in_lists(self, api_client, category):
        Destination.objects.create(name='Long', city='C', country='X', description='word ' * 100)
        description = api_client.get(LIST).data['results'][0]['description']
        assert description.endswith('...') and len(description) <= 150

    def test_create_requires_authentication(self, api_client):
        response = api_client.post(LIST, {'name': 'X', 'city': 'Y', 'country': 'Z', 'description': 'd'})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data['error']['message']

    def test_create_generates_slug(self, authenticated_client):
        response = authenticated_client.post(LIST, {
            'name': 'Cape Town', 'city': 'Cape Town', 'country': 'South Africa', 'description': 'Mountains',
        })
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['slug'] == 'cape-town-cape-town'

    def test_only_admins_can_update_or_delete(self, authenticated_client, client_for, admin_user, destination):
        assert authenticated_client.patch(detail(destination.id), {'name': 'X'}).status_code == 403
        admin = client_for(admin_user)
        assert admin.patch(detail(destination.id), {'description': 'Updated'}).status_code == 200
        assert admin.delete(detail(destination.id)).status_code == 204

    def test_unknown_destination_404_has_error_shape(self, api_client):
        response = api_client.get(detail(999))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data['error']['status_code'] == 404


class TestNestedRoutes:
    def test_accommodations_and_activities_for_destination(self, api_client, destination, accommodation, activity):
        other = Destination.objects.create(name='Other', city='O', country='O', description='o')
        Activity.objects.create(destination=other, title='Elsewhere', price=1)
        kwargs = {'destination_pk': destination.id}
        acc = api_client.get(reverse('destinations:destination-accommodations', kwargs=kwargs))
        act = api_client.get(reverse('destinations:destination-activities', kwargs=kwargs))
        assert [a['name'] for a in acc.data['results']] == ['Beach Hotel']
        assert [a['title'] for a in act.data['results']] == ['Surf lesson']


class TestModels:
    def test_str(self, destination, category):
        assert str(destination) == 'Bali (Denpasar, Indonesia)'
        assert str(category) == 'Beach'

    def test_clean_rejects_blank_fields(self):
        with pytest.raises(ValidationError):
            Destination(name='', city='x', country='y', description='d').clean()

    def test_average_rating_and_cost_estimate(self, destination, user):
        assert destination.average_rating() is None
        Review.objects.create(user=user, destination=destination, rating=3, comment='ok')
        assert destination.average_rating() == 3
        assert destination.estimated_trip_cost(3, travelers=2) == Decimal('480.00')
