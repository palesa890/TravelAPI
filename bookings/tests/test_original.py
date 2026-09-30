import pytest
from django.urls import reverse
from rest_framework import status
from destinations.models import Destination, Category
from itineraries.models import Itinerary
from bookings.models import Booking, Accommodation


@pytest.mark.django_db
class TestBookings:
    def test_create_booking(self, authenticated_client, user):
        cat = Category.objects.create(name="Nature")
        dest = Destination.objects.create(name="Grand Canyon", country="USA", city="AZ", category=cat)
        itin = Itinerary.objects.create(
            title="Canyon Tour", owner=user, destination=dest, start_date="2026-11-01", end_date="2026-11-05"
        )
        acc = Accommodation.objects.create(
            destination=dest, name="Canyon Lodge", address="Main Park Rd", price_per_night=150.00
        )

        url = reverse('booking-list')
        data = {
            "itinerary": itin.id,
            "booking_type": "ACCOMMODATION",
            "accommodation": acc.id,
            "total_price": 600.00
        }
        response = authenticated_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert Booking.objects.filter(user=user).exists()
