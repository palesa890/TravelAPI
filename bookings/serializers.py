from decimal import Decimal
from typing import Optional

from rest_framework import serializers

from travel_api.serializers import BaseModelSerializer

from .models import Accommodation, Activity, Booking


class AccommodationSerializer(BaseModelSerializer):
    class Meta:
        model = Accommodation
        fields = (
            'id', 'destination', 'name', 'accommodation_type', 'address',
            'price_per_night', 'created_at', 'updated_at',
        )


class ActivitySerializer(BaseModelSerializer):
    booking_count = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = (
            'id', 'destination', 'title', 'description', 'price', 'duration_hours',
            'booking_count', 'created_at', 'updated_at',
        )

    def get_booking_count(self, obj) -> int:
        annotated = getattr(obj, 'booking_count', None)
        if annotated is not None:
            return annotated
        return obj.bookings.exclude(status=Booking.Status.CANCELLED).count()


def validate_dates_within_trip(attrs, itinerary):
    """Raise if check_in / check_out fall outside the itinerary's dates."""
    for field in ('check_in', 'check_out'):
        day = attrs.get(field)
        if day and not (itinerary.start_date <= day <= itinerary.end_date):
            raise serializers.ValidationError({field: 'Date must fall within the itinerary dates.'})


class BookingListSerializer(BaseModelSerializer):
    itinerary_title = serializers.CharField(source='itinerary.title', read_only=True)
    item_name = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = (
            'id', 'itinerary', 'itinerary_title', 'booking_type', 'item_name', 'status',
            'check_in', 'check_out', 'total_price', 'booking_date',
        )

    def get_item_name(self, obj) -> str:
        return obj.item_name


class BookingCreateSerializer(BaseModelSerializer):
    total_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, min_value=0,
        help_text='Optional; calculated from the booked item when omitted.',
    )

    class Meta:
        model = Booking
        fields = (
            'id', 'user', 'itinerary', 'booking_type', 'accommodation', 'activity',
            'check_in', 'check_out', 'quantity', 'total_price', 'status',
            'booking_date', 'updated_at',
        )
        read_only_fields = ('user', 'status', 'booking_date')
        extra_kwargs = {
            'itinerary': {'help_text': 'Trip this booking belongs to; you must be its owner or an editor.'},
            'booking_type': {'help_text': 'ACCOMMODATION requires `accommodation`; ACTIVITY requires `activity`.'},
            'check_in': {'help_text': 'Arrival date, within the trip dates.'},
            'check_out': {'help_text': 'Departure date, after check-in.'},
            'quantity': {'help_text': 'Rooms for stays, tickets for activities.'},
        }

    def validate_itinerary(self, itinerary):
        request = self.context.get('request')
        if request and not itinerary.can_edit(request.user):
            raise serializers.ValidationError('You cannot add bookings to this itinerary.')
        return itinerary

    def validate_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError('Quantity must be at least 1.')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        itinerary = attrs['itinerary']
        item = attrs.get('accommodation') or attrs.get('activity')
        if item is not None and item.destination_id != itinerary.destination_id:
            raise serializers.ValidationError('The booked item must be at the itinerary destination.')
        validate_dates_within_trip(attrs, itinerary)
        return attrs

    def create(self, validated_data):
        request = self.context['request']
        booking = Booking(user=request.user, **validated_data)
        if validated_data.get('total_price') is None:
            booking.total_price = booking.calculate_total_price()
        booking.save()
        return booking


class BookingUpdateSerializer(BaseModelSerializer):
    """Only dates and quantity can change after a booking is made."""

    class Meta:
        model = Booking
        fields = ('id', 'check_in', 'check_out', 'quantity', 'total_price', 'status', 'updated_at')
        read_only_fields = ('total_price', 'status')

    def validate(self, attrs):
        if self.instance.status == Booking.Status.CANCELLED:
            raise serializers.ValidationError('Cancelled bookings cannot be modified.')
        attrs = super().validate(attrs)
        itinerary = self.instance.itinerary
        validate_dates_within_trip(attrs, itinerary)
        return attrs

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        # Re-price the booking whenever its dates or quantity change.
        instance.total_price = instance.calculate_total_price()
        instance.save()
        return instance


class BookingDetailSerializer(BaseModelSerializer):
    """
    Detailed serializer for retrieving single booking instances,
    including nested details for accommodation and activity.
    """
    accommodation_detail = AccommodationSerializer(source='accommodation', read_only=True)
    activity_detail = ActivitySerializer(source='activity', read_only=True)
    user_username = serializers.ReadOnlyField(source='user.username')
    itinerary_title = serializers.CharField(source='itinerary.title', read_only=True)
    nights = serializers.SerializerMethodField()
    refund_if_cancelled_today = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = (
            'id', 'user', 'user_username', 'itinerary', 'itinerary_title', 'booking_type',
            'accommodation', 'accommodation_detail', 'activity', 'activity_detail',
            'status', 'check_in', 'check_out', 'nights', 'quantity', 'total_price',
            'refund_amount', 'refund_if_cancelled_today', 'booking_date',
            'confirmed_at', 'cancelled_at', 'updated_at',
        )
        read_only_fields = fields

    def get_nights(self, obj) -> Optional[int]:
        return obj.nights

    def get_refund_if_cancelled_today(self, obj) -> Decimal:
        return obj.calculate_refund()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Only show the detail block relevant to this booking type.
        if instance.booking_type == Booking.BookingType.ACCOMMODATION:
            data.pop('activity', None)
            data.pop('activity_detail', None)
        else:
            data.pop('accommodation', None)
            data.pop('accommodation_detail', None)
            data.pop('nights', None)
        return data


class BulkBookingItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=[Booking.Status.CONFIRMED, Booking.Status.CANCELLED])


class BulkBookingUpdateSerializer(serializers.Serializer):
    updates = BulkBookingItemSerializer(many=True)

    def validate_updates(self, value):
        if not value:
            raise serializers.ValidationError('At least one update is required.')
        if len(value) > 100:
            raise serializers.ValidationError('A maximum of 100 bookings can be updated at once.')
        ids = [item['id'] for item in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError('Each booking may appear only once.')
        return value
