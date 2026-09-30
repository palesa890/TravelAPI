# bookings/urls.py  (mounted at /api/v1/bookings/)
from django.urls import path

from .views import BookingDetailView, bulk_update_bookings

app_name = 'bookings'

urlpatterns = [
    path('bulk-update/', bulk_update_bookings, name='bulk-update'),
    path('mine/<int:pk>/', BookingDetailView.as_view(), name='my-booking-detail'),
]
