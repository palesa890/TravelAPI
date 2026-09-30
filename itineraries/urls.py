# itineraries/urls.py  (mounted at /api/v1/trips/)
from django.urls import path

from bookings.views import BookingViewSet

from .views import (
    DailyPlanViewSet,
    TripDocumentViewSet,
    ItineraryListCreateView,
    TripCollaborationView,
    TripCollaboratorListView,
    generate_trip_report,
    trip_search,
)

app_name = 'itineraries'

daily_plan_list = DailyPlanViewSet.as_view({'get': 'list', 'post': 'create'})
daily_plan_detail = DailyPlanViewSet.as_view({
    'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy',
})

trip_document_list = TripDocumentViewSet.as_view({'get': 'list', 'post': 'create'})
trip_document_detail = TripDocumentViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})

urlpatterns = [
    path('search/', trip_search, name='trip-search'),
    path('mine/', ItineraryListCreateView.as_view(), name='itinerary-list-create'),
    path('<int:trip_id>/report/', generate_trip_report, name='trip-report'),

    # Nested resources
    path('<int:trip_id>/collaborators/', TripCollaboratorListView.as_view(), name='trip-collaborator-list'),
    path('<int:trip_id>/collaborators/<int:user_id>/',
         TripCollaborationView.as_view(http_method_names=['get', 'patch', 'delete', 'head', 'options']),
         name='trip-collaborator-detail'),
    path('<int:trip_id>/daily-plans/', daily_plan_list, name='daily-plan-list'),
    path('<int:trip_id>/daily-plans/<int:pk>/', daily_plan_detail, name='daily-plan-detail'),
    path('<int:trip_id>/documents/', trip_document_list, name='trip-document-list'),
    path('<int:trip_id>/documents/<int:pk>/', trip_document_detail, name='trip-document-detail'),
    path('<int:trip_id>/documents/<int:pk>/download/', TripDocumentViewSet.as_view({'get': 'download'}),
         name='trip-document-download'),
    path('<int:trip_id>/bookings/', BookingViewSet.as_view({'get': 'list'}), name='trip-bookings'),
]
