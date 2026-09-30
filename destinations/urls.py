# destinations/urls.py  (mounted at /api/v1/destinations/)
from django.urls import path

from bookings.views import AccommodationViewSet, ActivityViewSet
from reviews.views import DestinationReviewListCreateView

from .views import (
    DestinationBySlugView,
    DestinationFavoriteView,
    DestinationPhotoViewSet,
    DestinationSearchView,
)

app_name = 'destinations'

urlpatterns = [
    path('search/', DestinationSearchView.as_view(), name='destination-search'),
    path('slug/<slug:slug>/', DestinationBySlugView.as_view(), name='destination-by-slug'),
    path('<int:pk>/favorite/', DestinationFavoriteView.as_view(), name='destination-favorite'),

    # Nested resources
    path('<int:destination_pk>/reviews/', DestinationReviewListCreateView.as_view(), name='destination-reviews'),
    path('<int:destination_pk>/accommodations/', AccommodationViewSet.as_view({'get': 'list'}),
         name='destination-accommodations'),
    path('<int:destination_pk>/photos/', DestinationPhotoViewSet.as_view({'get': 'list', 'post': 'create'}),
         name='destination-photo-list'),
    path('<int:destination_pk>/photos/<int:pk>/',
         DestinationPhotoViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'}), name='destination-photo-detail'),
    path('<int:destination_pk>/activities/', ActivityViewSet.as_view({'get': 'list'}),
         name='destination-activities'),
]
