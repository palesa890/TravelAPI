# reviews/urls.py  (mounted at /api/v1/reviews/)
from django.urls import path

from .views import UserReviewListView

app_name = 'reviews'

urlpatterns = [
    path('by-user/<str:username>/', UserReviewListView.as_view(), name='user-reviews'),
]
