from django_filters import rest_framework as filters

from .models import Itinerary


class ItineraryFilter(filters.FilterSet):
    """
    Custom filters for itineraries.

    ?status=PLANNING&status=BOOKED   any of several statuses
    ?min_budget=500&max_budget=2000  on the attached budget
    ?start_date_after=2026-01-01&start_date_before=2026-12-31
    ?destination_country=france
    """
    min_budget = filters.NumberFilter(field_name='budget__total_budget', lookup_expr='gte')
    max_budget = filters.NumberFilter(field_name='budget__total_budget', lookup_expr='lte')
    start_date_after = filters.DateFilter(field_name='start_date', lookup_expr='gte')
    start_date_before = filters.DateFilter(field_name='start_date', lookup_expr='lte')
    destination_country = filters.CharFilter(field_name='destination__country', lookup_expr='icontains')
    status = filters.MultipleChoiceFilter(choices=Itinerary.Status.choices)
    upcoming = filters.BooleanFilter(method='filter_upcoming')

    class Meta:
        model = Itinerary
        fields = ['status', 'destination', 'is_public']

    def filter_upcoming(self, queryset, name, value):
        from django.utils import timezone
        today = timezone.now().date()
        return queryset.filter(start_date__gte=today) if value else queryset.filter(start_date__lt=today)
