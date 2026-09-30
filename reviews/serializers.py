from rest_framework import serializers

from travel_api.serializers import BaseModelSerializer

from .models import Review


class ReviewSerializer(BaseModelSerializer):
    """Read serializer for list and detail."""
    user_username = serializers.ReadOnlyField(source='user.username')
    destination_name = serializers.ReadOnlyField(source='destination.name')
    is_positive = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = (
            'id', 'user', 'user_username', 'destination', 'destination_name', 'rating',
            'title', 'comment', 'visited_on', 'is_positive', 'created_at', 'updated_at',
        )
        read_only_fields = ('user',)

    def get_is_positive(self, obj) -> bool:
        return obj.is_positive()


class ReviewCreateSerializer(ReviewSerializer):
    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError('Rating must be between 1 and 5.')
        return value

    def validate_comment(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError('Comment must be at least 5 characters long.')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        if request and Review.objects.filter(user=request.user, destination=attrs['destination']).exists():
            raise serializers.ValidationError({'destination': 'You have already reviewed this destination.'})
        return attrs

    def create(self, validated_data):
        return Review.objects.create(user=self.context['request'].user, **validated_data)


class ReviewUpdateSerializer(ReviewCreateSerializer):
    """Same rules as create, but the destination cannot change."""

    class Meta(ReviewSerializer.Meta):
        read_only_fields = ('user', 'destination')

    def validate(self, attrs):
        # Skip the duplicate-review check from ReviewCreateSerializer.
        return BaseModelSerializer.validate(self, attrs)
