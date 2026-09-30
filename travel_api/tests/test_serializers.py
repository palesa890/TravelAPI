"""
Direct serializer tests: validation rules, create/update overrides and representations.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from rest_framework.test import APIRequestFactory

from accounts.serializers import UserRegisterSerializer
from bookings.models import Booking
from bookings.serializers import BookingCreateSerializer, BookingDetailSerializer
from budgets.serializers import BudgetSerializer
from destinations.models import Destination
from destinations.serializers import DestinationListSerializer
from itineraries.serializers import ItineraryCreateSerializer
from reviews.models import Review
from reviews.serializers import ReviewCreateSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def context(user):
    request = APIRequestFactory().post('/')
    request.user = user
    return {'request': request}


class TestUserRegisterSerializer:
    def test_create_hashes_password(self):
        serializer = UserRegisterSerializer(data={'username': 'sam', 'email': 'SAM@x.com', 'password': 'Val1dPass!'})
        assert serializer.is_valid(), serializer.errors
        user = serializer.save()
        assert user.email == 'sam@x.com' and user.check_password('Val1dPass!')
        assert 'password' not in serializer.data

    def test_rejects_mismatched_confirmation(self):
        serializer = UserRegisterSerializer(data={'username': 'sam', 'password': 'Val1dPass!', 'password2': 'x'})
        assert not serializer.is_valid()
        assert 'password2' in serializer.errors


class TestItineraryCreateSerializer:
    def test_generates_daily_plans(self, destination, trip_dates, user):
        start, end = trip_dates
        serializer = ItineraryCreateSerializer(data={
            'title': 'Plan it', 'destination': destination.id, 'start_date': start, 'end_date': end,
            'generate_daily_plans': True,
        })
        assert serializer.is_valid(), serializer.errors
        itinerary = serializer.save(owner=user)
        assert itinerary.daily_plans.count() == 6

    @pytest.mark.parametrize('field, value', [('title', 'ab'), ('status', 'COMPLETED')])
    def test_field_validation(self, destination, trip_dates, field, value):
        start, end = trip_dates
        data = {'title': 'Valid', 'destination': destination.id, 'start_date': start, 'end_date': end, field: value}
        serializer = ItineraryCreateSerializer(data=data)
        assert not serializer.is_valid()
        assert field in serializer.errors

    def test_model_clean_runs(self, destination, trip_dates):
        start, end = trip_dates
        serializer = ItineraryCreateSerializer(data={
            'title': 'Backwards', 'destination': destination.id, 'start_date': end, 'end_date': start,
        })
        assert not serializer.is_valid()
        assert 'end_date' in serializer.errors


class TestBookingSerializers:
    def test_create_prices_the_booking_and_sets_user(self, context, itinerary, accommodation, user):
        serializer = BookingCreateSerializer(data={
            'itinerary': itinerary.id, 'booking_type': 'ACCOMMODATION', 'accommodation': accommodation.id,
            'check_in': itinerary.start_date, 'check_out': itinerary.start_date + timedelta(days=2),
        }, context=context)
        assert serializer.is_valid(), serializer.errors
        booking = serializer.save()
        assert booking.user == user and booking.total_price == Decimal('200.00')

    def test_rejects_other_peoples_itinerary(self, other_user, itinerary, accommodation):
        request = APIRequestFactory().post('/')
        request.user = other_user
        serializer = BookingCreateSerializer(data={
            'itinerary': itinerary.id, 'booking_type': 'ACCOMMODATION', 'accommodation': accommodation.id,
        }, context={'request': request})
        assert not serializer.is_valid()
        assert 'itinerary' in serializer.errors

    def test_detail_representation_drops_unused_item(self, user, itinerary, activity):
        booking = Booking.objects.create(user=user, itinerary=itinerary, booking_type='ACTIVITY',
                                         activity=activity, total_price=40)
        data = BookingDetailSerializer(booking).data
        assert data['activity_detail']['title'] == 'Surf lesson'
        assert 'accommodation_detail' not in data and 'nights' not in data


class TestBudgetSerializer:
    def test_computed_fields(self, context, itinerary):
        serializer = BudgetSerializer(data={'itinerary': itinerary.id, 'total_budget': '1000', 'currency': 'eur'},
                                      context=context)
        assert serializer.is_valid(), serializer.errors
        budget = serializer.save()
        assert budget.currency == 'EUR'
        assert serializer.data['remaining_balance'] == Decimal('1000.00')
        assert serializer.data['is_over_budget'] is False

    def test_negative_budget(self, context, itinerary):
        serializer = BudgetSerializer(data={'itinerary': itinerary.id, 'total_budget': '-5'}, context=context)
        assert not serializer.is_valid()
        assert 'total_budget' in serializer.errors


class TestReviewCreateSerializer:
    def test_one_review_per_destination(self, context, user, destination):
        Review.objects.create(user=user, destination=destination, rating=4, comment='First visit')
        serializer = ReviewCreateSerializer(data={'destination': destination.id, 'rating': 5, 'comment': 'Again!'},
                                            context=context)
        assert not serializer.is_valid()
        assert 'destination' in serializer.errors

    def test_rating_range(self, context, destination):
        serializer = ReviewCreateSerializer(data={'destination': destination.id, 'rating': 9, 'comment': 'Too good'},
                                            context=context)
        assert not serializer.is_valid()
        assert 'rating' in serializer.errors


class TestDestinationListSerializer:
    def test_truncates_description_and_reads_annotation(self):
        destination = Destination.objects.create(name='Long', city='C', country='X', description='word ' * 60)
        destination.avg_rating = 4.256
        data = DestinationListSerializer(destination).data
        assert data['description'].endswith('...')
        assert data['average_rating'] == 4.26
