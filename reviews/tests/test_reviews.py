from datetime import date, timedelta

import pytest
from django.urls import reverse
from rest_framework import status

from destinations.models import Destination
from reviews.models import Review

pytestmark = pytest.mark.django_db

LIST = reverse('review-list')
MINE = reverse('review-mine')


def detail(pk):
    return reverse('review-detail', kwargs={'pk': pk})


@pytest.fixture
def review(user, destination):
    return Review.objects.create(user=user, destination=destination, rating=5, title='Wow', comment='Loved it')


class TestCreate:
    def test_anonymous_cannot_post(self, api_client, destination):
        response = api_client.post(LIST, {'destination': destination.id, 'rating': 5, 'comment': 'Great!'})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize('payload, field', [
        ({'rating': 0}, 'rating'),
        ({'rating': 6}, 'rating'),
        ({'comment': ' hi '}, 'comment'),
        ({'visited_on': (date.today() + timedelta(days=3)).isoformat()}, 'visited_on'),
    ])
    def test_validation(self, authenticated_client, destination, payload, field):
        data = {'destination': destination.id, 'rating': 4, 'comment': 'Good trip', **payload}
        response = authenticated_client.post(LIST, data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert field in response.data['error']['details']

    def test_one_review_per_destination(self, authenticated_client, review, destination):
        response = authenticated_client.post(LIST, {'destination': destination.id, 'rating': 3, 'comment': 'Again!'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestReadAndFilter:
    @pytest.fixture
    def reviews(self, review, other_user, destination):
        paris = Destination.objects.create(name='Paris', city='Paris', country='France', description='x')
        Review.objects.create(user=other_user, destination=destination, rating=2, comment='Too hot')
        Review.objects.create(user=other_user, destination=paris, rating=4, comment='Great food')

    def test_public_list_with_custom_pagination(self, api_client, reviews):
        response = api_client.get(f'{LIST}?page_size=2')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 3
        assert response.data['total_pages'] == 2
        assert response.data['current_page'] == 1
        assert len(response.data['results']) == 2


class TestUpdateDelete:
    def test_others_cannot_modify(self, other_client, review, api_client):
        assert other_client.patch(detail(review.id), {'rating': 1}).status_code == status.HTTP_403_FORBIDDEN
        assert other_client.delete(detail(review.id)).status_code == status.HTTP_403_FORBIDDEN
        assert api_client.get(detail(review.id)).status_code == status.HTTP_200_OK

    def test_author_deletes(self, authenticated_client, review):
        assert authenticated_client.delete(detail(review.id)).status_code == status.HTTP_204_NO_CONTENT


class TestModel:
    def test_str_and_positive(self, review):
        assert str(review) == 'Bali - 5 Stars'
        assert review.is_positive()
