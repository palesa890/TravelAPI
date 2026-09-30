from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from accounts.serializers import UserSummarySerializer
from bookings.serializers import ActivitySerializer
from budgets.serializers import BudgetSummarySerializer
from destinations.serializers import DestinationListSerializer
from travel_api.serializers import BaseModelSerializer

from .models import Collaboration, DailyPlan, Itinerary, TripDocument

User = get_user_model()


class DailyPlanSerializer(BaseModelSerializer):
    activity_details = ActivitySerializer(source='activities', many=True, read_only=True)

    class Meta:
        model = DailyPlan
        fields = (
            'id', 'itinerary', 'day_number', 'date', 'title', 'notes',
            'activities', 'activity_details', 'created_at', 'updated_at',
        )
        read_only_fields = ('itinerary',)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        itinerary = self.context.get('itinerary') or getattr(self.instance, 'itinerary', None)
        if itinerary is None:
            return attrs
        plan_date = attrs.get('date', getattr(self.instance, 'date', None))
        day_number = attrs.get('day_number', getattr(self.instance, 'day_number', None))
        if plan_date and not (itinerary.start_date <= plan_date <= itinerary.end_date):
            raise serializers.ValidationError({'date': 'Date must fall within the itinerary dates.'})
        if day_number and day_number > itinerary.duration_days:
            raise serializers.ValidationError({'day_number': 'Day number exceeds the trip length.'})
        clash = itinerary.daily_plans.filter(day_number=day_number)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if day_number and clash.exists():
            raise serializers.ValidationError({'day_number': 'A plan for this day already exists.'})
        for activity in attrs.get('activities', []):
            if activity.destination_id != itinerary.destination_id:
                raise serializers.ValidationError({'activities': f'"{activity}" is not at this trip\'s destination.'})
        return attrs


class CollaborationSerializer(BaseModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.only('id', 'username', 'email', 'is_active'),
        help_text='ID of the user to add as a collaborator.',
    )
    user_detail = UserSummarySerializer(source='user', read_only=True)
    invited_by = serializers.ReadOnlyField(source='invited_by.username', help_text='Username of who sent the invite.')

    class Meta:
        model = Collaboration
        fields = ('id', 'itinerary', 'user', 'user_detail', 'role', 'invited_by', 'created_at', 'updated_at')
        read_only_fields = ('itinerary',)
        extra_kwargs = {
            'role': {'help_text': 'EDITOR can modify the trip; VIEWER has read-only access.'},
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        itinerary = self.context.get('itinerary') or getattr(self.instance, 'itinerary', None)
        user = attrs.get('user')
        if self.instance is not None and user and user != self.instance.user:
            raise serializers.ValidationError(
                {'user': 'The collaborator cannot be changed; remove and re-add instead.'}
            )
        if itinerary and user and self.instance is None:
            if itinerary.owner_id == user.id:
                raise serializers.ValidationError({'user': 'The trip owner cannot be added as a collaborator.'})
            if itinerary.collaborations.filter(user=user).exists():
                raise serializers.ValidationError({'user': 'This user is already a collaborator.'})
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        return Collaboration.objects.create(
            itinerary=self.context['itinerary'],
            invited_by=request.user if request else None,
            **validated_data,
        )


# Alias kept for views importing CollaboratorSerializer
CollaboratorSerializer = CollaborationSerializer


class ItineraryListSerializer(BaseModelSerializer):
    """Lightweight serializer for list views."""
    owner_username = serializers.ReadOnlyField(source='owner.username')
    destination_name = serializers.ReadOnlyField(source='destination.name')
    duration_days = serializers.SerializerMethodField(help_text='Number of days, inclusive of start and end.')
    total_activities = serializers.SerializerMethodField(help_text='Activities planned across all days.')

    class Meta:
        model = Itinerary
        fields = (
            'id', 'title', 'owner', 'owner_username', 'destination', 'destination_name',
            'start_date', 'end_date', 'duration_days', 'total_activities', 'status', 'travelers',
            'budget', 'created_at',
        )
        read_only_fields = ('owner', 'budget')

    def get_duration_days(self, obj) -> int:
        return obj.duration_days

    def get_total_activities(self, obj) -> int:
        annotated = getattr(obj, 'total_activities', None)
        if annotated is not None:
            return annotated
        return sum(plan.activities.count() for plan in obj.daily_plans.all())


class ItineraryDetailSerializer(ItineraryListSerializer):
    """Full itinerary with nested destination, plans, collaborators and budget."""
    destination = DestinationListSerializer(read_only=True)
    daily_plans = DailyPlanSerializer(many=True, read_only=True)
    collaborations = CollaborationSerializer(many=True, read_only=True)
    budget = BudgetSummarySerializer(read_only=True)
    total_booking_cost = serializers.SerializerMethodField()
    booking_count = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()

    class Meta(ItineraryListSerializer.Meta):
        fields = ItineraryListSerializer.Meta.fields + (
            'description', 'is_public', 'daily_plans', 'collaborations',
            'total_booking_cost', 'booking_count', 'my_role', 'updated_at',
        )

    def _active_bookings(self, obj):
        # Uses the Prefetch(to_attr='active_bookings') from the viewset when available.
        active = getattr(obj, 'active_bookings', None)
        if active is None:
            from bookings.models import Booking
            active = list(obj.bookings.exclude(status=Booking.Status.CANCELLED))
        return active

    def get_total_booking_cost(self, obj) -> Decimal:
        return sum((b.total_price for b in self._active_bookings(obj)), Decimal('0.00'))

    def get_booking_count(self, obj) -> int:
        return len(self._active_bookings(obj))

    def get_my_role(self, obj) -> str:
        request = self.context.get('request')
        return obj.get_role(request.user) if request else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['is_upcoming'] = instance.is_upcoming()
        return data


class ItinerarySerializer(BaseModelSerializer):
    """Base write serializer shared by create and update."""

    class Meta:
        model = Itinerary
        fields = (
            'id', 'title', 'description', 'owner', 'destination', 'start_date', 'end_date',
            'status', 'travelers', 'is_public', 'budget', 'created_at', 'updated_at',
        )
        read_only_fields = ('owner', 'budget')
        extra_kwargs = {
            'title': {'help_text': 'Trip name, at least 3 characters.'},
            'destination': {'help_text': 'ID of the destination being visited.'},
            'start_date': {'help_text': 'First day of the trip (YYYY-MM-DD).'},
            'end_date': {'help_text': 'Last day of the trip (YYYY-MM-DD); trips can be at most a year long.'},
            'travelers': {'help_text': 'Number of people travelling (at least 1).'},
            'is_public': {'help_text': 'Public trips can be viewed by anyone with the link.'},
        }

    def validate_title(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError('Title must be at least 3 characters long.')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        start = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        if start and end and (end - start).days > 365:
            raise serializers.ValidationError({'end_date': 'Trips cannot be longer than one year.'})
        return attrs


class ItineraryCreateSerializer(ItinerarySerializer):
    generate_daily_plans = serializers.BooleanField(
        write_only=True, required=False, default=False,
        help_text='Create an empty daily plan for each day of the trip.',
    )

    class Meta(ItinerarySerializer.Meta):
        fields = ItinerarySerializer.Meta.fields + ('generate_daily_plans',)

    def validate_status(self, value):
        if value in (Itinerary.Status.COMPLETED, Itinerary.Status.CANCELLED):
            raise serializers.ValidationError('New itineraries cannot start as completed or cancelled.')
        return value

    @transaction.atomic
    def create(self, validated_data):
        generate = validated_data.pop('generate_daily_plans', False)
        itinerary = Itinerary.objects.create(**validated_data)
        if generate:
            itinerary.generate_daily_plans()
        return itinerary


class ItineraryUpdateSerializer(ItinerarySerializer):
    def validate_status(self, value):
        if value == Itinerary.Status.COMPLETED and self.instance.end_date > date.today():
            raise serializers.ValidationError('A trip cannot be completed before it ends.')
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        dates_changed = any(
            f in validated_data and validated_data[f] != getattr(instance, f)
            for f in ('start_date', 'end_date')
        )
        instance = super().update(instance, validated_data)
        if dates_changed:
            # Drop plans that now fall outside the trip and realign the rest.
            instance.daily_plans.exclude(date__range=(instance.start_date, instance.end_date)).delete()
            plans = list(instance.daily_plans.all())
            # Two passes so the (itinerary, day_number) unique constraint never collides.
            for plan in plans:
                plan.day_number += 10000
            DailyPlan.objects.bulk_update(plans, ['day_number'])
            for plan in plans:
                plan.day_number = (plan.date - instance.start_date).days + 1
            DailyPlan.objects.bulk_update(plans, ['day_number'])
        return instance


class ItineraryBudgetStatusSerializer(serializers.ModelSerializer):
    """Budget vs actual spend, fed by the annotated queryset in ItineraryViewSet.budget_status."""
    destination_name = serializers.ReadOnlyField(source='destination.name')
    total_budget = serializers.DecimalField(
        source='budget.total_budget', max_digits=12, decimal_places=2, read_only=True,
    )
    currency = serializers.ReadOnlyField(source='budget.currency')
    total_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, help_text='Sum of non-cancelled bookings.',
    )
    budget_variance = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, help_text='Budget minus cost; negative means over budget.',
    )

    class Meta:
        model = Itinerary
        fields = ('id', 'title', 'destination_name', 'start_date', 'total_budget', 'currency',
                  'total_cost', 'budget_variance')


class TripDocumentSerializer(BaseModelSerializer):
    """
    Upload with multipart/form-data: title, document_type, file.
    The file itself is fetched through the authenticated `download_url`, never a public media URL.
    """
    # Declaring the field explicitly drops the model's validators, so pass them again.
    file = serializers.FileField(
        write_only=True,
        validators=TripDocument._meta.get_field('file').validators,
        help_text='PDF, JPG, PNG or WEBP. Checked by content as well as extension; max size set by MAX_UPLOAD_SIZE_MB.',
    )
    uploaded_by = serializers.ReadOnlyField(source='uploaded_by.username')
    extension = serializers.ReadOnlyField()
    size_bytes = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = TripDocument
        fields = ('id', 'itinerary', 'title', 'document_type', 'file', 'extension', 'size_bytes',
                  'download_url', 'uploaded_by', 'created_at', 'updated_at')
        read_only_fields = ('itinerary',)

    def get_size_bytes(self, obj) -> int:
        try:
            return obj.file.size
        except (FileNotFoundError, ValueError):
            # The row exists but the file was removed from storage.
            return 0

    def get_download_url(self, obj) -> str:
        from django.urls import reverse
        path = reverse('itineraries:trip-document-download', kwargs={'trip_id': obj.itinerary_id, 'pk': obj.pk})
        request = self.context.get('request')
        return request.build_absolute_uri(path) if request else path
