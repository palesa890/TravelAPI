import pytest
from django.urls import reverse
from rest_framework import status
from destinations.models import Destination, Category
from reviews.models import Review


@pytest.mark.django_db
class TestReviews:
    def test_create_review(self, authenticated_client, user):
        cat = Category.objects.create(name="Island")
        dest = Destination.objects.create(name="Bali", country="Indonesia", city="Denpasar", category=cat)

        url = reverse('review-list')
        data = {
            "destination": dest.id,
            "rating": 5,
            "comment": "Amazing place!"
        }
        response = authenticated_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert Review.objects.filter(user=user, destination=dest).exists()
