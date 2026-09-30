
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status


User = get_user_model()
pytestmark = pytest.mark.django_db

REGISTER = reverse('accounts:auth-register')
LOGIN = reverse('accounts:token-obtain-pair')
REFRESH = reverse('accounts:token-refresh')
VERIFY = reverse('accounts:token-verify')
LOGOUT = reverse('accounts:logout')
PROFILE = reverse('accounts:auth-profile')
CHANGE_PASSWORD = reverse('accounts:password-change')
RESET = reverse('accounts:password-reset')
RESET_CONFIRM = reverse('accounts:password-reset-confirm')


def test_urls_are_versioned():
    assert REGISTER == '/api/v1/accounts/register/'


class TestRegistration:
    def payload(self, **overrides):
        data = {'username': 'alice', 'email': 'Alice@Example.com', 'password': 'Sup3rSecret!'}
        data.update(overrides)
        return data

    def test_register_success_lowercases_email_and_hides_password(self, api_client):
        response = api_client.post(REGISTER, self.payload())
        assert response.status_code == status.HTTP_201_CREATED
        assert 'password' not in response.data
        user = User.objects.get(username='alice')
        assert user.email == 'alice@example.com'
        assert user.check_password('Sup3rSecret!')

    def test_password_confirmation_must_match(self, api_client):
        response = api_client.post(REGISTER, self.payload(password2='different'))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'password2' in response.data['error']['details']

    def test_matching_confirmation_is_accepted(self, api_client):
        response = api_client.post(REGISTER, self.payload(password2='Sup3rSecret!'))
        assert response.status_code == status.HTTP_201_CREATED

    def test_weak_password_rejected(self, api_client):
        response = api_client.post(REGISTER, self.payload(password='12345678'))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestJWT:
    def login(self, client, username='testuser', password='password123'):
        return client.post(LOGIN, {'username': username, 'password': password})

    def test_login_returns_tokens_and_user(self, api_client, user):
        response = self.login(api_client)
        assert response.status_code == status.HTTP_200_OK
        assert {'access', 'refresh', 'user'} <= set(response.data)
        assert response.data['user']['username'] == 'testuser'

    def test_login_with_wrong_password(self, api_client, user):
        response = self.login(api_client, password='wrong')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data['error']['status_code'] == 401

    def test_access_token_authenticates_requests(self, api_client, user):
        access = self.login(api_client).data['access']
        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        assert api_client.get(PROFILE).status_code == status.HTTP_200_OK

    def test_refresh_and_verify(self, api_client, user):
        tokens = self.login(api_client).data
        refreshed = api_client.post(REFRESH, {'refresh': tokens['refresh']})
        assert refreshed.status_code == status.HTTP_200_OK
        assert 'access' in refreshed.data
        assert api_client.post(VERIFY, {'token': tokens['access']}).status_code == status.HTTP_200_OK

    def test_logout_blacklists_refresh_token(self, api_client, user):
        refresh = self.login(api_client).data['refresh']
        assert api_client.post(LOGOUT, {'refresh': refresh}).status_code == status.HTTP_200_OK
        assert api_client.post(REFRESH, {'refresh': refresh}).status_code == status.HTTP_401_UNAUTHORIZED


class TestProfile:
    def test_requires_authentication(self, api_client):
        response = api_client.get(PROFILE)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_profile(self, authenticated_client, user, itinerary, destination):
        user.favorite_destinations.add(destination)
        response = authenticated_client.get(PROFILE)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['trip_count'] == 1
        assert response.data['favorite_destinations'][0]['name'] == 'Bali'
        assert response.data['age'] is None


class TestUserModel:
    def test_str(self, user):
        assert str(user) == 'testuser'

    def test_total_spent_without_bookings(self, user):
        assert user.total_spent() == 0
