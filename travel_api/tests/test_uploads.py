"""
File upload tests: storage location, size/type validation, permissions and cleanup.
"""
import io
import os
import shutil
import tempfile
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from destinations.models import Destination, DestinationPhoto
from itineraries.models import Collaboration, Itinerary, TripDocument

User = get_user_model()


def pdf_file(name='ticket.pdf', size=None):
    content = b'%PDF-1.4\n' + (b'0' * (size or 100))
    return SimpleUploadedFile(name, content, content_type='application/pdf')


def png_file(name='photo.png'):
    buffer = io.BytesIO()
    Image.new('RGB', (10, 10), color='blue').save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class MediaTestCase(APITestCase):
    """Stores uploads in a throwaway MEDIA_ROOT that is removed after each test."""

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix='travel-api-test-media-')
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.owner = User.objects.create_user(username='owner', password='pass12345')
        self.destination = Destination.objects.create(name='Bali', city='Denpasar', country='Indonesia',
                                                      description='Island')
        start = date.today() + timedelta(days=20)
        self.itinerary = Itinerary.objects.create(title='Bali Trip', owner=self.owner, destination=self.destination,
                                                  start_date=start, end_date=start + timedelta(days=3))
        self.client.force_authenticate(self.owner)

    def tearDown(self):
        self.client.force_authenticate(user=None)
        self.media_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)


class TripDocumentUploadTests(MediaTestCase):
    def url(self, pk=None, suffix=''):
        base = f'/api/v1/trips/{self.itinerary.id}/documents/'
        return f'{base}{pk}/{suffix}' if pk else base

    def upload(self, file, **extra):
        return self.client.post(self.url(), {'title': 'Flight', 'document_type': 'TICKET', 'file': file, **extra},
                                format='multipart')

    def test_upload_stores_file_under_media_with_random_name(self):
        response = self.upload(pdf_file())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['extension'], 'pdf')
        self.assertNotIn('file', response.data)  # served only through the authenticated download URL
        document = TripDocument.objects.get()
        self.assertTrue(document.file.name.startswith('itineraries/documents/'))
        self.assertNotIn('ticket', document.file.name)
        self.assertTrue(os.path.exists(os.path.join(self.media_root, document.file.name)))

    def test_download(self):
        document_id = self.upload(pdf_file()).data['id']
        response = self.client.get(self.url(document_id, 'download/'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))

    def test_rejects_disguised_file(self):
        fake = SimpleUploadedFile('ticket.pdf', b'MZ this is really an exe', content_type='application/pdf')
        response = self.upload(fake)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', response.data['error']['details'])

    def test_rejects_unsupported_extension(self):
        response = self.upload(SimpleUploadedFile('virus.exe', b'MZ...'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(MAX_UPLOAD_SIZE_MB=1)
    def test_rejects_oversized_file(self):
        response = self.upload(pdf_file(size=int(1.5 * 1024 * 1024)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Maximum size is 1 MB', str(response.data))

    def test_viewer_can_list_but_not_upload(self):
        viewer = User.objects.create_user(username='viewer', password='pass12345')
        Collaboration.objects.create(itinerary=self.itinerary, user=viewer, role=Collaboration.Role.VIEWER)
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(self.url()).status_code, status.HTTP_200_OK)
        self.assertEqual(self.upload(pdf_file()).status_code, status.HTTP_403_FORBIDDEN)

    def test_stranger_gets_404(self):
        self.client.force_authenticate(User.objects.create_user(username='stranger', password='pass12345'))
        self.assertEqual(self.client.get(self.url()).status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_removes_file_from_disk(self):
        document_id = self.upload(pdf_file()).data['id']
        path = os.path.join(self.media_root, TripDocument.objects.get().file.name)
        self.assertEqual(self.client.delete(self.url(document_id)).status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(os.path.exists(path))


class DestinationPhotoUploadTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.url = f'/api/v1/destinations/{self.destination.id}/photos/'

    def test_upload_and_list(self):
        response = self.client.post(self.url, {'image': png_file(), 'caption': 'Sunset'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['uploaded_by'], 'owner')
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url).data['count'], 1)

    def test_rejects_non_image(self):
        bad = SimpleUploadedFile('photo.jpg', b'not an image at all', content_type='image/jpeg')
        response = self.client.post(self.url, {'image': bad}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_requires_login(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {'image': png_file()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_only_uploader_can_delete(self):
        photo_id = self.client.post(self.url, {'image': png_file()}, format='multipart').data['id']
        self.client.force_authenticate(User.objects.create_user(username='other', password='pass12345'))
        self.assertEqual(self.client.delete(f'{self.url}{photo_id}/').status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(f'{self.url}{photo_id}/').status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DestinationPhoto.objects.exists())


class ProfilePictureUploadTests(MediaTestCase):
    def test_replacing_picture_deletes_old_file(self):
        first = self.client.patch('/api/v1/accounts/me/', {'profile_picture': png_file()}, format='multipart')
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        old_path = os.path.join(self.media_root, self.owner.profile_picture.name)
        self.assertTrue(os.path.exists(old_path))
        self.client.patch('/api/v1/accounts/me/', {'profile_picture': png_file('new.png')}, format='multipart')
        self.assertFalse(os.path.exists(old_path))
