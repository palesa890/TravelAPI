import pytest
from django.urls import reverse
from rest_framework import status
from destinations.models import Destination, Category
from itineraries.models import Itinerary
from budgets.models import Budget


@pytest.mark.django_db
class TestBudgets:
    def test_create_budget(self, authenticated_client, user):
        cat = Category.objects.create(name="Historic")
        dest = Destination.objects.create(name="Rome", country="Italy", city="Rome", category=cat)
        itin = Itinerary.objects.create(
            title="Rome Trip", owner=user, destination=dest, start_date="2026-12-01", end_date="2026-12-10"
        )

        url = reverse('budget-list')
        data = {
            "itinerary": itin.id,
            "total_budget": 2000.00
        }
        response = authenticated_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert Budget.objects.filter(itinerary=itin).exists()
