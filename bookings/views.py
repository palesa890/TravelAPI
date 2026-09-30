# bookings/views.py
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from travel_api.notifications import notify_user
from travel_api.pagination import LargeResultsPagination

from .filters import BookingFilter
from .models import Accommodation, Activity, Booking
from .permissions import IsBookingOwner
from .serializers import (
    AccommodationSerializer,
    ActivitySerializer,
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
    BookingUpdateSerializer,
    BulkBookingUpdateSerializer,
)


def apply_status_change(booking, new_status):
    """Run the model transition for a status change. Returns the refund when cancelling."""
    if new_status == Booking.Status.CONFIRMED:
        booking.confirm()
        return None
    return booking.cancel()


# --- FBV 3: Bulk update bookings ---
@extend_schema(
    request=BulkBookingUpdateSerializer,
    responses={200: OpenApiTypes.OBJECT, 207: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    examples=[
        OpenApiExample('Request', request_only=True, value={'updates': [
            {'id': 12, 'status': 'CONFIRMED'}, {'id': 13, 'status': 'CANCELLED'},
        ]}),
        OpenApiExample('Partial success (207)', response_only=True, status_codes=['207'], value={
            'succeeded': 1, 'failed': 1, 'results': [
                {'id': 12, 'success': True, 'status': 'CONFIRMED'},
                {'id': 13, 'success': False, 'error': 'Booking is already cancelled.'},
            ],
        }),
    ],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_update_bookings(request):
    """
    Confirm or cancel several bookings in one request.
    Body: {"updates": [{"id": 1, "status": "CONFIRMED"}, {"id": 2, "status": "CANCELLED"}]}
    Each update runs in its own savepoint, so one failure doesn't undo the others.

    Returns 200 when every update succeeds, 207 on partial success, 400 when all fail.

    Example:
        POST /api/v1/bookings/bulk-update/
        {"updates": [{"id": 12, "status": "CONFIRMED"}]}
        -> 200 {"succeeded": 1, "failed": 0,
                "results": [{"id": 12, "success": true, "status": "CONFIRMED"}]}
    """
    serializer = BulkBookingUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    updates = serializer.validated_data['updates']

    bookings = {
        b.id: b for b in Booking.objects.filter(
            user=request.user, id__in=[u['id'] for u in updates]
        ).select_related('itinerary')
    }
    results = []
    with transaction.atomic():
        for item in updates:
            booking = bookings.get(item['id'])
            if booking is None:
                results.append({'id': item['id'], 'success': False, 'error': 'Booking not found.'})
                continue
            try:
                with transaction.atomic():
                    refund = apply_status_change(booking, item['status'])
            except DjangoValidationError as exc:
                results.append({'id': booking.id, 'success': False, 'error': ' '.join(exc.messages)})
                continue
            result = {'id': booking.id, 'success': True, 'status': booking.status}
            if refund is not None:
                result['refund_amount'] = refund
            results.append(result)

    succeeded = sum(1 for r in results if r['success'])
    failed = len(results) - succeeded
    if succeeded == 0:
        response_status = status.HTTP_400_BAD_REQUEST
    elif failed:
        response_status = status.HTTP_207_MULTI_STATUS
    else:
        response_status = status.HTTP_200_OK
    return Response(
        {'succeeded': succeeded, 'failed': failed, 'results': results},
        status=response_status,
    )


class ProtectConfirmedBookingMixin:
    """Confirmed bookings must be cancelled (and refunded) before they can be deleted."""

    def perform_destroy(self, instance):
        if instance.status == Booking.Status.CONFIRMED:
            raise ValidationError({'detail': 'Cancel a confirmed booking before deleting it.'})
        instance.delete()


# --- CBV 5: Booking retrieve, update & destroy ---
class BookingDetailView(ProtectConfirmedBookingMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    GET: Retrieve booking.
    PUT/PATCH: Update dates or quantity (price is recalculated).
    DELETE: Delete a pending or cancelled booking.
    """
    permission_classes = [IsAuthenticated, IsBookingOwner]

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return BookingUpdateSerializer
        return BookingDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()

        return (
            Booking.objects.filter(user=self.request.user)
            .select_related('accommodation', 'activity', 'itinerary', 'user')
        )


# --- ViewSet: bookings ---
@extend_schema_view(
    confirm=extend_schema(request=None, responses=OpenApiTypes.OBJECT),
    cancel=extend_schema(request=None, responses=OpenApiTypes.OBJECT),
)
class BookingViewSet(ProtectConfirmedBookingMixin, viewsets.ModelViewSet):
    """
    Manage accommodation and activity bookings, with confirm/cancel actions.

    The price is calculated from the booked item when total_price is omitted:
    nights x rooms x price_per_night for stays, tickets x price for activities.
    Cancelling refunds 100% (14+ days before), 50% (7-13), 25% (2-6), otherwise 0%.
    """
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingFilter
    search_fields = ['accommodation__name', 'activity__title', 'itinerary__title']
    ordering_fields = ['booking_date', 'total_price', 'check_in']
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()

        queryset = (
            Booking.objects.filter(user=self.request.user)
            .select_related('accommodation', 'activity', 'itinerary', 'user')
        )
        # Nested route: /trips/<trip_id>/bookings/
        if 'trip_id' in self.kwargs:
            queryset = queryset.filter(itinerary_id=self.kwargs['trip_id'])
        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return BookingListSerializer
        if self.action == 'create':
            return BookingCreateSerializer
        if self.action in ('update', 'partial_update'):
            return BookingUpdateSerializer
        return BookingDetailSerializer

    def get_permissions(self):
        if self.action in ['create', 'list']:
            return [IsAuthenticated()]
        elif self.action in ['update', 'partial_update', 'destroy', 'confirm', 'cancel']:
            return [IsAuthenticated(), IsBookingOwner()]
        return [IsAuthenticated()]

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirm a pending booking and email a confirmation."""
        booking = self.get_object()
        booking.confirm()
        notify_user(
            request.user,
            'Booking confirmed',
            f'Your booking for {booking.item_name} ({booking.total_price}) is confirmed.',
        )
        return Response(
            {'message': 'Booking confirmed successfully.', 'booking': BookingDetailSerializer(booking).data},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a booking; the refund depends on how close the trip is."""
        booking = self.get_object()
        refund_amount = booking.cancel()
        return Response(
            {'message': 'Booking cancelled.', 'refund_amount': refund_amount,
             'booking': BookingDetailSerializer(booking).data},
            status=status.HTTP_200_OK,
        )


# --- ViewSets: read-only catalogue of bookable items ---
class AccommodationViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse accommodations. Also nested at /destinations/<destination_pk>/accommodations/."""
    serializer_class = AccommodationSerializer
    permission_classes = [AllowAny]
    pagination_class = LargeResultsPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['destination', 'accommodation_type']
    search_fields = ['name', 'address']
    ordering_fields = ['price_per_night', 'name']
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        queryset = Accommodation.objects.select_related('destination').order_by('name')
        if 'destination_pk' in self.kwargs:
            queryset = queryset.filter(destination_id=self.kwargs['destination_pk'])
        return queryset


class ActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse activities. Also nested at /destinations/<destination_pk>/activities/."""
    serializer_class = ActivitySerializer
    permission_classes = [AllowAny]
    pagination_class = LargeResultsPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['destination']
    search_fields = ['title', 'description']
    ordering_fields = ['price', 'title', 'booking_count']
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        queryset = Activity.objects.select_related('destination').annotate(
            booking_count=Count('bookings', filter=~Q(bookings__status=Booking.Status.CANCELLED))
        ).order_by('title')
        if 'destination_pk' in self.kwargs:
            queryset = queryset.filter(destination_id=self.kwargs['destination_pk'])
        return queryset
