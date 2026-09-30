import pytest
from django.urls import reverse
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestAccounts:
    def test_user_registration(self, api_client):
        url = reverse('accounts:auth-register')
        data = {
            "username": "traveler1",
            "email": "traveler1@example.com",
            "password": "SecurePassword123!",
            "first_name": "John",
            "last_name": "Doe"
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(username="traveler1").exists()

    def test_user_login(self, api_client):
        User.objects.create_user(username="traveler2", password="SecurePassword123!")
        url = reverse('accounts:token-obtain-pair')
        response = api_client.post(url, {"username": "traveler2", "password": "SecurePassword123!"})
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
