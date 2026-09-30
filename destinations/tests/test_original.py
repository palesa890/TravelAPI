import pytest
from django.urls import reverse
from rest_framework import status
from destinations.models import Destination, Category


@pytest.mark.django_db
class TestDestinations:
    def test_create_destination(self, authenticated_client):
        category = Category.objects.create(name="Beach")
        url = reverse('destination-list')
        data = {
            "name": "Tropical Paradise",
            "country": "Maldives",
            "city": "Male",
            "description": "Clear waters",
            "category": category.id
        }
        response = authenticated_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert Destination.objects.count() == 1
