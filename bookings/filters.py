from django_filters import rest_framework as filters

from .models import Booking


class BookingFilter(filters.FilterSet):
    """
    ?status=PENDING&status=CONFIRMED
    ?min_price=100&max_price=500
    ?booked_after=2026-01-01&booked_before=2026-02-01
    ?check_in_after=2026-06-01
    """
    status = filters.MultipleChoiceFilter(choices=Booking.Status.choices)
    booking_type = filters.ChoiceFilter(choices=Booking.BookingType.choices)
    min_price = filters.NumberFilter(field_name='total_price', lookup_expr='gte')
    max_price = filters.NumberFilter(field_name='total_price', lookup_expr='lte')
    booked_after = filters.DateFilter(field_name='booking_date', lookup_expr='date__gte')
    booked_before = filters.DateFilter(field_name='booking_date', lookup_expr='date__lte')
    check_in_after = filters.DateFilter(field_name='check_in', lookup_expr='gte')
    destination = filters.NumberFilter(field_name='itinerary__destination')

    class Meta:
        model = Booking
        fields = ['status', 'booking_type', 'itinerary']
