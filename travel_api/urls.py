# travel_api/urls.py
"""
API v1 URL layout

/api/v1/                      DefaultRouter (all ViewSets, un-namespaced names e.g. 'itinerary-list')
/api/v1/accounts/...          accounts:*      auth, profile, passwords
/api/v1/destinations/...      destinations:*  search, slug lookup, favorites, nested reviews/accommodations/activities
/api/v1/trips/...             itineraries:*   trip search, reports, collaborators, daily plans, trip bookings
/api/v1/bookings/...          bookings:*      bulk update, booking detail
/api/v1/budgets/...           budgets:*       nested expenses
/api/v1/reviews/...           reviews:*       reviews by user
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from bookings.views import AccommodationViewSet, ActivityViewSet, BookingViewSet
from budgets.views import BudgetViewSet, TripAnalyticsViewSet
from destinations.views import CategoryViewSet, DestinationViewSet
from itineraries.views import ItineraryViewSet
from reviews.views import ReviewViewSet

router = DefaultRouter()
router.register(r'itineraries', ItineraryViewSet, basename='itinerary')
router.register(r'destinations', DestinationViewSet, basename='destination')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'bookings', BookingViewSet, basename='booking')
router.register(r'accommodations', AccommodationViewSet, basename='accommodation')
router.register(r'activities', ActivityViewSet, basename='activity')
router.register(r'budgets', BudgetViewSet, basename='budget')
router.register(r'reviews', ReviewViewSet, basename='review')
router.register(r'analytics', TripAnalyticsViewSet, basename='analytics')

API_PREFIX = f'api/{settings.API_VERSION}/'

urlpatterns = [
    path('admin/', admin.site.urls),

    # OpenAPI schema & docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # App endpoints (namespaced)
    path(f'{API_PREFIX}accounts/', include('accounts.urls')),
    path(f'{API_PREFIX}destinations/', include('destinations.urls')),
    path(f'{API_PREFIX}trips/', include('itineraries.urls')),
    path(f'{API_PREFIX}bookings/', include('bookings.urls')),
    path(f'{API_PREFIX}budgets/', include('budgets.urls')),
    path(f'{API_PREFIX}reviews/', include('reviews.urls')),

    # ViewSets
    path(API_PREFIX, include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
