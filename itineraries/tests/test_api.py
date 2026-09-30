"""
APITestCase-style tests for itinerary CRUD and role-based permissions.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from budgets.models import Budget
from destinations.models import Destination
from itineraries.models import Collaboration, Itinerary

User = get_user_model()


def future(days):
    return (date.today() + timedelta(days=days)).isoformat()


class ItineraryAPITestCase(APITestCase):
    """
    Test itinerary CRUD operations.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='testpass123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.destination = Destination.objects.create(
            name='Paris', city='Paris', country='France', description='City of light',
        )
        self.itinerary = Itinerary.objects.create(
            title='Paris Trip', destination=self.destination, owner=self.user,
            start_date=future(30), end_date=future(36),
        )
        Budget.objects.create(itinerary=self.itinerary, total_budget=2000)

    def tearDown(self):
        # Drop the forced authentication so no state leaks between tests.
        self.client.force_authenticate(user=None)
        mail.outbox.clear()

    def test_list_itineraries(self):
        """Test retrieving list of user's itineraries"""
        response = self.client.get('/api/v1/itineraries/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

    def test_create_itinerary(self):
        """Test creating new itinerary"""
        data = {
            'title': 'Rome Adventure', 'destination': self.destination.id,
            'start_date': future(60), 'end_date': future(69),
        }
        response = self.client.post('/api/v1/itineraries/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Itinerary.objects.count(), 2)

    def test_update_itinerary(self):
        """Test updating existing itinerary"""
        response = self.client.patch(f'/api/v1/itineraries/{self.itinerary.id}/', {'title': 'Paris & Lyon'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.itinerary.refresh_from_db()
        self.assertEqual(self.itinerary.title, 'Paris & Lyon')

    def test_update_budget(self):
        """The budget lives on its own resource, linked one-to-one with the itinerary."""
        budget = self.itinerary.budget
        response = self.client.patch(f'/api/v1/budgets/{budget.id}/', {'total_budget': 2500})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        budget.refresh_from_db()
        self.assertEqual(budget.total_budget, 2500)

    def test_delete_itinerary(self):
        """Test deleting itinerary"""
        response = self.client.delete(f'/api/v1/itineraries/{self.itinerary.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Itinerary.objects.count(), 0)

    def test_unauthorized_access(self):
        """Test that unauthenticated users cannot access"""
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/v1/itineraries/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_update_others_itinerary(self):
        """Test users cannot update others' itineraries"""
        other_user = User.objects.create_user(username='other', password='pass123')
        self.client.force_authenticate(user=other_user)
        response = self.client.patch(f'/api/v1/itineraries/{self.itinerary.id}/', {'title': 'Mine now'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_rejects_end_before_start(self):
        data = {'title': 'Backwards', 'destination': self.destination.id,
                'start_date': future(10), 'end_date': future(5)}
        response = self.client.post('/api/v1/itineraries/', data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('end_date', response.data['error']['details'])


class PermissionTestCase(APITestCase):
    """
    Test custom permissions for the owner / editor / viewer roles.
    """

    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='pass123')
        self.collaborator = User.objects.create_user(username='collab', password='pass123')
        self.viewer = User.objects.create_user(username='viewer', password='pass123')
        destination = Destination.objects.create(name='Rome', city='Rome', country='Italy', description='History')
        self.itinerary = Itinerary.objects.create(
            title='Test Trip', owner=self.owner, destination=destination,
            start_date=future(10), end_date=future(12),
        )
        self.url = f'/api/v1/itineraries/{self.itinerary.id}/'

    def tearDown(self):
        self.client.force_authenticate(user=None)

    def test_owner_can_edit(self):
        """Test owner has full permissions"""
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(self.url, {'title': 'Updated'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_collaborator_permissions(self):
        """Test collaborator permissions based on role"""
        self.itinerary.add_collaborator(self.collaborator, role='editor')
        self.client.force_authenticate(user=self.collaborator)
        response = self.client.patch(self.url, {'title': 'Updated by Collab'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_read_but_not_edit(self):
        self.itinerary.add_collaborator(self.viewer, role='viewer')
        self.client.force_authenticate(user=self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)
        response = self.client.patch(self.url, {'title': 'Nope'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_owner_can_delete(self):
        self.itinerary.add_collaborator(self.collaborator, role='editor')
        self.client.force_authenticate(user=self.collaborator)
        self.assertEqual(self.client.delete(self.url).status_code, status.HTTP_403_FORBIDDEN)

    def test_add_collaborator_updates_role_and_validates(self):
        self.itinerary.add_collaborator(self.collaborator, role='viewer')
        self.itinerary.add_collaborator(self.collaborator, role='EDITOR')
        self.assertEqual(Collaboration.objects.get(user=self.collaborator).role, 'EDITOR')
        with self.assertRaises(Exception):
            self.itinerary.add_collaborator(self.viewer, role='admin')
        with self.assertRaises(Exception):
            self.itinerary.add_collaborator(self.owner)
