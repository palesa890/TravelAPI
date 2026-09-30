from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status

from bookings.models import Activity, Booking

pytestmark = pytest.mark.django_db

LIST = reverse('booking-list')
BULK = reverse('bookings:bulk-update')


def detail(pk):
    return reverse('booking-detail', kwargs={'pk': pk})


def my_detail(pk):
    return reverse('bookings:my-booking-detail', kwargs={'pk': pk})


@pytest.fixture
def make_booking(user, itinerary, accommodation, activity):
    def _make(**kwargs):
        kwargs.setdefault('user', user)
        kwargs.setdefault('itinerary', itinerary)
        kwargs.setdefault('booking_type', Booking.BookingType.ACCOMMODATION)
        if kwargs['booking_type'] == Booking.BookingType.ACCOMMODATION:
            kwargs.setdefault('accommodation', accommodation)
        else:
            kwargs.setdefault('activity', activity)
        kwargs.setdefault('total_price', Decimal('100.00'))
        return Booking.objects.create(**kwargs)
    return _make


class TestCreate:
    def test_price_is_calculated_for_stays(self, authenticated_client, itinerary, accommodation):
        response = authenticated_client.post(LIST, {
            'itinerary': itinerary.id, 'booking_type': 'ACCOMMODATION', 'accommodation': accommodation.id,
            'check_in': itinerary.start_date.isoformat(),
            'check_out': (itinerary.start_date + timedelta(days=3)).isoformat(), 'quantity': 2,
        })
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['total_price'] == '600.00'
        assert response.data['status'] == 'PENDING'

    def test_price_is_calculated_for_activities(self, authenticated_client, itinerary, activity):
        response = authenticated_client.post(LIST, {
            'itinerary': itinerary.id, 'booking_type': 'ACTIVITY', 'activity': activity.id, 'quantity': 3,
        })
        assert response.data['total_price'] == '120.00'


class TestReadAndFilter:
    def test_detail_hides_irrelevant_item(self, authenticated_client, make_booking, itinerary):
        stay = make_booking(check_in=itinerary.start_date, check_out=itinerary.start_date + timedelta(days=2))
        data = authenticated_client.get(detail(stay.id)).data
        assert 'activity_detail' not in data and data['nights'] == 2
        assert data['accommodation_detail']['name'] == 'Beach Hotel'
        assert data['refund_if_cancelled_today'] == Decimal('100.00')

        tour = make_booking(booking_type='ACTIVITY')
        data = authenticated_client.get(detail(tour.id)).data
        assert 'accommodation_detail' not in data and 'nights' not in data
        assert data['activity_detail']['title'] == 'Surf lesson'

    def test_users_only_see_their_own(self, other_client, make_booking):
        booking = make_booking()
        assert other_client.get(LIST).data['count'] == 0
        assert other_client.get(detail(booking.id)).status_code == status.HTTP_404_NOT_FOUND
        assert other_client.get(my_detail(booking.id)).status_code == status.HTTP_404_NOT_FOUND


class TestModels:
    def test_str_and_item_name(self, make_booking, accommodation):
        booking = make_booking()
        assert str(booking) == 'Accommodation - Beach Hotel (testuser)'
        assert str(accommodation) == 'Beach Hotel'
        assert Booking(booking_type='ACTIVITY').item_name == 'Unknown item'
        assert str(Activity(title='Hike')) == 'Hike'

    def test_cancelled_bookings_get_no_further_refund(self, make_booking):
        booking = make_booking()
        booking.cancel()
        assert booking.calculate_refund() == Decimal('0.00')
        with pytest.raises(ValidationError):
            booking.cancel()

    def test_confirm_requires_pending(self, make_booking):
        booking = make_booking(status=Booking.Status.CANCELLED)
        with pytest.raises(ValidationError):
            booking.confirm()
