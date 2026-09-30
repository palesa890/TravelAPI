from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bookings.models import Accommodation, Activity
from destinations.models import Category, Destination
from itineraries.models import Collaboration, Itinerary

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(username="testuser", password="password123", email="testuser@example.com")


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authenticated_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


# --- Additional shared fixtures ---

@pytest.fixture
def make_user(db):
    def _make(username, **kwargs):
        kwargs.setdefault('email', f'{username}@example.com')
        kwargs.setdefault('password', 'StrongPass123!')
        return User.objects.create_user(username=username, **kwargs)
    return _make


@pytest.fixture
def client_for():
    """Return an APIClient authenticated as the given user."""
    def _client(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client
    return _client


@pytest.fixture
def other_user(make_user):
    return make_user('otheruser')


@pytest.fixture
def other_client(client_for, other_user):
    return client_for(other_user)


@pytest.fixture
def admin_user(make_user):
    return make_user('admin', is_staff=True)


@pytest.fixture
def category(db):
    return Category.objects.create(name='Beach', description='Sun and sand')


@pytest.fixture
def destination(category):
    return Destination.objects.create(
        name='Bali', city='Denpasar', country='Indonesia', description='Island paradise',
        category=category, climate=Destination.Climate.TROPICAL, average_cost_per_day=Decimal('80.00'),
    )


@pytest.fixture
def accommodation(destination):
    return Accommodation.objects.create(
        destination=destination, name='Beach Hotel', address='1 Beach Rd', price_per_night=Decimal('100.00'),
    )


@pytest.fixture
def activity(destination):
    return Activity.objects.create(destination=destination, title='Surf lesson', price=Decimal('40.00'))


@pytest.fixture
def trip_dates():
    start = date.today() + timedelta(days=30)
    return start, start + timedelta(days=5)


@pytest.fixture
def itinerary(user, destination, trip_dates):
    start, end = trip_dates
    return Itinerary.objects.create(
        title='Bali Trip', owner=user, destination=destination, start_date=start, end_date=end,
    )


@pytest.fixture
def add_collaborator():
    def _add(itinerary, user, role=Collaboration.Role.VIEWER):
        return Collaboration.objects.create(itinerary=itinerary, user=user, role=role)
    return _add
