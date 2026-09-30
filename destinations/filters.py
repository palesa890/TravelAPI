from django.db.models import Q
from django_filters import rest_framework as filters

from .models import Destination

BUDGET_RANGES = {
    'budget': (None, 100),
    'moderate': (100, 250),
    'luxury': (250, None),
}


class DestinationFilter(filters.FilterSet):
    """
    Advanced destination filtering.

    ?climate=TROPICAL&climate=DRY   any of several climates
    ?budget_range=budget|moderate|luxury
    ?category=Beach  or  ?category=3
    ?min_rating=4
    """
    country = filters.CharFilter(lookup_expr='icontains')
    city = filters.CharFilter(lookup_expr='icontains')
    climate = filters.MultipleChoiceFilter(choices=Destination.Climate.choices)
    category = filters.CharFilter(method='filter_category')
    budget_range = filters.ChoiceFilter(
        method='filter_by_budget', choices=[(k, k.title()) for k in BUDGET_RANGES],
    )
    min_cost = filters.NumberFilter(field_name='average_cost_per_day', lookup_expr='gte')
    max_cost = filters.NumberFilter(field_name='average_cost_per_day', lookup_expr='lte')
    min_rating = filters.NumberFilter(method='filter_min_rating')

    class Meta:
        model = Destination
        fields = ['country', 'city', 'category', 'climate']

    def filter_category(self, queryset, name, value):
        if value.isdigit():
            return queryset.filter(category_id=int(value))
        return queryset.filter(category__name__iexact=value)

    def filter_by_budget(self, queryset, name, value):
        low, high = BUDGET_RANGES[value]
        q = Q()
        if low is not None:
            q &= Q(average_cost_per_day__gte=low)
        if high is not None:
            q &= Q(average_cost_per_day__lt=high)
        return queryset.filter(q)

    def filter_min_rating(self, queryset, name, value):
        # Relies on the avg_rating annotation added by the viewset queryset.
        return queryset.filter(avg_rating__gte=value)
