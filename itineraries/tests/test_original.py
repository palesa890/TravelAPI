import pytest
from django.urls import reverse
from rest_framework import status
from destinations.models import Destination, Category
from itineraries.models import Itinerary


@pytest.mark.django_db
class TestItineraries:
    def test_create_itinerary(self, authenticated_client, user):
        cat = Category.objects.create(name="City")
        dest = Destination.objects.create(name="Eiffel Tower", country="France", city="Paris", category=cat)
        url = reverse('itinerary-list')
        data = {
            "title": "Paris Trip",
            "destination": dest.id,
            "start_date": "2026-10-01",
            "end_date": "2026-10-07"
        }
        response = authenticated_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert Itinerary.objects.filter(owner=user).exists()
