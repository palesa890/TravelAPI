from django_filters import rest_framework as filters

from .models import Review


class ReviewFilter(filters.FilterSet):
    """
    ?destination=3  ?min_rating=4  ?max_rating=2  ?username=alice  ?positive=true
    """
    min_rating = filters.NumberFilter(field_name='rating', lookup_expr='gte')
    max_rating = filters.NumberFilter(field_name='rating', lookup_expr='lte')
    username = filters.CharFilter(field_name='user__username', lookup_expr='iexact')
    positive = filters.BooleanFilter(method='filter_positive')

    class Meta:
        model = Review
        fields = ['destination', 'rating']

    def filter_positive(self, queryset, name, value):
        return queryset.filter(rating__gte=4) if value else queryset.filter(rating__lt=4)
