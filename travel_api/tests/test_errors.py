"""
Every error type comes back with the right status code and the same JSON shape.
"""
from unittest import mock

import pytest
from django.urls import reverse
from rest_framework import status

pytestmark = pytest.mark.django_db


def assert_error_shape(response, code):
    assert response.status_code == code
    error = response.data['error']
    assert error['status_code'] == code
    assert error['message']
    assert 'details' in error


def test_validation_error_is_400(authenticated_client):
    assert_error_shape(authenticated_client.post(reverse('itinerary-list'), {}), status.HTTP_400_BAD_REQUEST)


def test_missing_credentials_is_401(api_client):
    assert_error_shape(api_client.get(reverse('itinerary-list')), status.HTTP_401_UNAUTHORIZED)


def test_invalid_token_is_401(api_client):
    api_client.credentials(HTTP_AUTHORIZATION='Bearer not-a-real-token')
    assert_error_shape(api_client.get(reverse('itinerary-list')), status.HTTP_401_UNAUTHORIZED)


def test_permission_denied_is_403(authenticated_client, destination):
    response = authenticated_client.delete(reverse('destination-detail', kwargs={'pk': destination.id}))
    assert_error_shape(response, status.HTTP_403_FORBIDDEN)


def test_not_found_is_404(authenticated_client):
    assert_error_shape(authenticated_client.get(reverse('itinerary-detail', kwargs={'pk': 999})), 404)


def test_pdf_failure_is_clean_500(authenticated_client, itinerary):
    url = reverse('itinerary-export-pdf', kwargs={'pk': itinerary.id})
    with mock.patch('reportlab.platypus.SimpleDocTemplate.build', side_effect=ValueError('bad markup')):
        response = authenticated_client.get(url)
    assert_error_shape(response, status.HTTP_500_INTERNAL_SERVER_ERROR)
    assert 'bad markup' not in str(response.data)
