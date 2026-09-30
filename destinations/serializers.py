# destinations/serializers.py
from typing import Optional

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from bookings.serializers import AccommodationSerializer
from reviews.serializers import ReviewSerializer
from travel_api.serializers import BaseModelSerializer

from .models import Category, Destination, DestinationPhoto, SearchPreference


class AverageRatingMixin:
    """Shared `average_rating` field logic for destination serializers."""

    def get_average_rating(self, obj) -> Optional[float]:
        # Use the queryset's avg_rating annotation when present to avoid a query per row.
        if hasattr(obj, 'avg_rating'):
            return round(obj.avg_rating, 2) if obj.avg_rating is not None else None
        return obj.average_rating()


class CategorySerializer(BaseModelSerializer):
    destination_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ('id', 'name', 'description', 'destination_count', 'created_at', 'updated_at')

    def get_destination_count(self, obj) -> int:
        annotated = getattr(obj, 'destination_count', None)
        return annotated if annotated is not None else obj.destinations.count()


class DestinationListSerializer(AverageRatingMixin, BaseModelSerializer):
    """Lightweight representation for list and search results."""
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    average_rating = serializers.SerializerMethodField()

    class Meta:
        model = Destination
        fields = (
            'id', 'name', 'slug', 'city', 'country', 'climate', 'category', 'category_name',
            'description', 'average_cost_per_day', 'average_rating', 'cover_image',
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        description = data.get('description') or ''
        if len(description) > 150:
            data['description'] = description[:147].rstrip() + '...'
        return data


class DestinationSerializer(BaseModelSerializer):
    """Used for create and update."""

    class Meta:
        model = Destination
        fields = (
            'id', 'name', 'slug', 'country', 'city', 'description', 'category', 'climate',
            'average_cost_per_day', 'cover_image', 'created_at', 'updated_at',
        )
        read_only_fields = ('slug',)

    def validate_average_cost_per_day(self, value):
        if value < 0:
            raise serializers.ValidationError('Average cost per day cannot be negative.')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        name = attrs.get('name', getattr(self.instance, 'name', None))
        city = attrs.get('city', getattr(self.instance, 'city', None))
        duplicates = Destination.objects.filter(name__iexact=name, city__iexact=city)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError({'name': 'This destination already exists in that city.'})
        return attrs


class DestinationDetailSerializer(AverageRatingMixin, DestinationSerializer):
    """Full destination with nested category, reviews and accommodations."""
    category = CategorySerializer(read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    recent_reviews = serializers.SerializerMethodField()
    accommodations = serializers.SerializerMethodField()

    class Meta(DestinationSerializer.Meta):
        fields = DestinationSerializer.Meta.fields + (
            'average_rating', 'review_count', 'recent_reviews', 'accommodations',
        )

    def get_review_count(self, obj) -> int:
        annotated = getattr(obj, 'review_count', None)
        return annotated if annotated is not None else obj.reviews.count()

    @extend_schema_field(ReviewSerializer(many=True))
    def get_recent_reviews(self, obj):
        prefetched = getattr(obj, 'prefetched_reviews', None)
        reviews = prefetched[:5] if prefetched is not None else obj.reviews.select_related('user')[:5]
        return ReviewSerializer(reviews, many=True, context=self.context).data

    @extend_schema_field(AccommodationSerializer(many=True))
    def get_accommodations(self, obj):
        return AccommodationSerializer(obj.accommodations.all(), many=True, context=self.context).data


class SearchPreferenceSerializer(BaseModelSerializer):
    class Meta:
        model = SearchPreference
        fields = (
            'id', 'scope', 'name', 'query', 'country', 'climate', 'category',
            'min_budget', 'max_budget', 'filters', 'created_at', 'updated_at',
        )
        read_only_fields = ('scope',)

    def validate_filters(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Filters must be a JSON object.')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not any(attrs.get(f) for f in ('query', 'country', 'climate', 'category', 'filters')) \
                and attrs.get('min_budget') is None and attrs.get('max_budget') is None:
            raise serializers.ValidationError('Provide at least one search criterion to save.')
        return attrs


class DestinationPhotoSerializer(BaseModelSerializer):
    """Upload with multipart/form-data: image (+ optional caption)."""
    uploaded_by = serializers.ReadOnlyField(source='uploaded_by.username')

    class Meta:
        model = DestinationPhoto
        fields = ('id', 'destination', 'image', 'caption', 'uploaded_by', 'created_at', 'updated_at')
        read_only_fields = ('destination',)
        extra_kwargs = {
            'image': {'help_text': 'JPG, PNG or WEBP image; validated by content and size.'},
            'caption': {'help_text': 'Optional short description of the photo.'},
        }
