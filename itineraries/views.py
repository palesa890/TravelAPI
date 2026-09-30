# itineraries/views.py
import io
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import (
    Case, Count, DecimalField, F, IntegerField, Prefetch, Q, Sum, Value, When,
)
from django.db.models.functions import Coalesce
from django.http import Http404
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample, OpenApiParameter, extend_schema, extend_schema_view, inline_serializer,
)
from rest_framework import serializers
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from bookings.models import Activity, Booking
from budgets.models import Budget
from destinations.models import SearchPreference
from destinations.serializers import SearchPreferenceSerializer
from travel_api.notifications import notify_user
from travel_api.pagination import paginated_response

from .filters import ItineraryFilter
from .models import Collaboration, DailyPlan, Itinerary, TripDocument
from .permissions import CanEditItinerary, IsTripOwner, IsTripOwnerOrCollaborator
from .serializers import (
    CollaboratorSerializer,
    ItineraryBudgetStatusSerializer,
    DailyPlanSerializer,
    ItineraryCreateSerializer,
    ItineraryDetailSerializer,
    ItineraryListSerializer,
    ItineraryUpdateSerializer,
    TripDocumentSerializer,
)

User = get_user_model()
logger = logging.getLogger(__name__)


class PDFGenerationError(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = 'Could not generate the PDF for this itinerary.'
    default_code = 'pdf_generation_failed'


def accessible_itineraries(user):
    """
    Itineraries the user owns or collaborates on.

    Uses a subquery instead of a join on collaborators so rows are never duplicated,
    which keeps Sum/Count annotations on this queryset correct.
    """
    shared = Collaboration.objects.filter(user=user).values('itinerary_id')
    return Itinerary.objects.filter(Q(owner=user) | Q(pk__in=shared))


def parse_date_param(value, name):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError({name: 'Use the YYYY-MM-DD format.'})


TRIP_SEARCH_PARAMS = [
    OpenApiParameter('q', str, description='Free text matched against title, description and destination.'),
    OpenApiParameter('status', str, description='PLANNING, BOOKED, ONGOING, COMPLETED or CANCELLED.'),
    OpenApiParameter('destination', int, description='Destination ID.'),
    OpenApiParameter('country', str, description='Destination country (partial match).'),
    OpenApiParameter('start_after', OpenApiTypes.DATE, description='Trips starting on or after this date.'),
    OpenApiParameter('start_before', OpenApiTypes.DATE, description='Trips starting on or before this date.'),
    OpenApiParameter('upcoming', bool, description='Only trips that have not started yet.'),
]


# --- FBV 1: Trip search & saved search preferences ---
@extend_schema(methods=['GET'], parameters=TRIP_SEARCH_PARAMS, responses=ItineraryListSerializer(many=True))
@extend_schema(
    methods=['POST'], request=SearchPreferenceSerializer, responses={201: SearchPreferenceSerializer},
    examples=[OpenApiExample('Save a search', value={'name': 'Summer beaches', 'query': 'beach', 'max_budget': '2000'},
                             request_only=True)],
)
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def trip_search(request):
    """
    GET: Search the user's trips with filters and ranking.
         Params: q, status, destination, country, start_after, start_before, upcoming=true
         Ranking: exact title match > title contains > destination match, then upcoming trips first.
    POST: Save the search as a preference.

    Example:
        GET /api/v1/trips/search/?q=paris&upcoming=true
        -> {"count": 1, "next": null, "previous": null,
            "results": [{"id": 4, "title": "Paris in spring", "destination_name": "Paris", ...}]}
    """
    if request.method == 'GET':
        params = request.query_params
        query = params.get('q', '').strip()
        queryset = accessible_itineraries(request.user).select_related('destination', 'owner')

        if query:
            queryset = queryset.filter(
                Q(title__icontains=query) | Q(description__icontains=query)
                | Q(destination__name__icontains=query) | Q(destination__city__icontains=query)
                | Q(destination__country__icontains=query)
            )
        if params.get('status'):
            queryset = queryset.filter(status__iexact=params['status'])
        if params.get('destination'):
            queryset = queryset.filter(destination_id=params['destination'])
        if params.get('country'):
            queryset = queryset.filter(destination__country__icontains=params['country'])
        if params.get('start_after'):
            queryset = queryset.filter(start_date__gte=parse_date_param(params['start_after'], 'start_after'))
        if params.get('start_before'):
            queryset = queryset.filter(start_date__lte=parse_date_param(params['start_before'], 'start_before'))
        if params.get('upcoming', '').lower() == 'true':
            queryset = queryset.filter(start_date__gte=timezone.now().date())

        # Ranking: title matches beat destination matches; upcoming trips come first.
        today = timezone.now().date()
        if query:
            relevance = Case(
                When(title__iexact=query, then=Value(100)),
                When(title__icontains=query, then=Value(50)),
                When(destination__name__icontains=query, then=Value(30)),
                default=Value(10),
                output_field=IntegerField(),
            )
        else:
            relevance = Value(0, output_field=IntegerField())
        queryset = queryset.annotate(
            relevance=relevance,
            is_future=Case(When(start_date__gte=today, then=Value(1)), default=Value(0), output_field=IntegerField()),
        ).order_by('-relevance', '-is_future', 'start_date')

        return paginated_response(request, queryset, ItineraryListSerializer)

    serializer = SearchPreferenceSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    serializer.save(user=request.user, scope=SearchPreference.Scope.TRIP)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


# --- FBV 2: Trip summary report ---
@extend_schema(
    responses=OpenApiTypes.OBJECT,
    examples=[OpenApiExample('Report', response_only=True, value={
        'trip_id': 4, 'title': 'Paris in spring', 'status': 'PLANNING',
        'dates': {'start_date': '2026-04-01', 'end_date': '2026-04-05', 'duration_days': 5},
        'bookings': {'total_cost': '640.00', 'by_type': {'ACCOMMODATION': {'count': 1, 'total': '600.00'}}},
        'budget': {'total_budget': '2000.00', 'total_spent': '740.00', 'remaining_balance': '1260.00'},
    })],
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def generate_trip_report(request, trip_id):
    """
    Comprehensive trip report combining itinerary, bookings, budget and expenses.
    Available to the owner and collaborators.

    Example:
        GET /api/v1/trips/4/report/
        -> {"trip_id": 4, "title": "Paris in spring",
            "bookings": {"total_cost": "640.00", "by_status": {"CONFIRMED": 2}},
            "budget": {"total_budget": "2000.00", "remaining_balance": "1260.00", "percent_used": 37.0},
            "daily_plans": [{"day": 1, "date": "2026-04-01", "activities": ["Louvre tour"]}], ...}
    """
    itinerary = (
        accessible_itineraries(request.user)
        .select_related('destination', 'owner')
        .prefetch_related('daily_plans__activities', 'collaborations__user')
        .filter(pk=trip_id)
        .first()
    )
    if itinerary is None:
        raise NotFound('Itinerary not found or access denied.')

    active_bookings = itinerary.bookings.exclude(status=Booking.Status.CANCELLED)
    bookings_by_type = {
        row['booking_type']: {'count': row['count'], 'total': row['total']}
        for row in active_bookings.values('booking_type').annotate(count=Count('id'), total=Sum('total_price'))
    }
    bookings_by_status = {
        row['status']: row['count']
        for row in itinerary.bookings.values('status').annotate(count=Count('id'))
    }
    total_booking_cost = active_bookings.aggregate(total=Sum('total_price'))['total'] or 0

    budget = Budget.objects.filter(itinerary=itinerary).first()
    if budget:
        total_expenses = budget.total_expenses()
        total_spent = total_expenses + total_booking_cost
        budget_data = {
            'total_budget': budget.total_budget,
            'currency': budget.currency,
            'total_booking_cost': total_booking_cost,
            'total_expenses': total_expenses,
            'total_spent': total_spent,
            'remaining_balance': budget.total_budget - total_spent,
            'percent_used': (
                round(float(total_spent) / float(budget.total_budget) * 100, 1) if budget.total_budget else None
            ),
            'expenses_by_category': budget.spending_by_category(),
        }
    else:
        budget_data = None

    days = itinerary.duration_days
    report = {
        'trip_id': itinerary.id,
        'title': itinerary.title,
        'status': itinerary.status,
        'owner': itinerary.owner.username,
        'destination': {
            'id': itinerary.destination.id,
            'name': itinerary.destination.name,
            'city': itinerary.destination.city,
            'country': itinerary.destination.country,
        },
        'dates': {
            'start_date': itinerary.start_date,
            'end_date': itinerary.end_date,
            'duration_days': days,
            'days_until_start': (itinerary.start_date - timezone.now().date()).days,
        },
        'travelers': itinerary.travelers,
        'bookings': {
            'total_cost': total_booking_cost,
            'by_type': bookings_by_type,
            'by_status': bookings_by_status,
        },
        'budget': budget_data,
        'estimated_daily_cost': round(float(total_booking_cost) / days, 2) if days else None,
        'daily_plans': [
            {
                'day': plan.day_number,
                'date': plan.date,
                'title': plan.title,
                'activities': [a.title for a in plan.activities.all()],
            }
            for plan in itinerary.daily_plans.all()
        ],
        'collaborators': [
            {'username': c.user.username, 'role': c.role} for c in itinerary.collaborations.all()
        ],
        'generated_at': timezone.now(),
    }
    return Response(report, status=status.HTTP_200_OK)


# --- CBV 3: Itinerary list and create ---
class ItineraryListCreateView(generics.ListCreateAPIView):
    """
    GET: List itineraries owned by the logged-in user.
    POST: Create a new itinerary.
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ItineraryFilter
    search_fields = ['title', 'description', 'destination__name', 'destination__country']
    ordering_fields = ['start_date', 'created_at', 'title']

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ItineraryCreateSerializer
        return ItineraryListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Itinerary.objects.none()

        queryset = (
            Itinerary.objects.filter(owner=self.request.user)
            .select_related('destination', 'owner', 'budget')
            .annotate(total_activities=Count('daily_plans__activities', distinct=True))
            .order_by('start_date', 'id')
        )
        if self.request.method == 'GET':
            # The list serializer never shows descriptions, so don't load them.
            queryset = queryset.defer('description')
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


# --- CBV 4: Trip collaboration management ---
@extend_schema_view(
    get=extend_schema(operation_id='trips_collaborators_retrieve', responses=CollaboratorSerializer(many=True)),
    post=extend_schema(request=CollaboratorSerializer, responses={201: CollaboratorSerializer}),
    patch=extend_schema(request=CollaboratorSerializer, responses=CollaboratorSerializer),
    delete=extend_schema(responses={204: None}),
)
class TripCollaborationView(APIView):
    """
    GET: List collaborators.
    POST: Add collaborator with a role.
    PATCH: Update a collaborator's role.
    DELETE: Remove a collaborator.
    """
    permission_classes = [IsAuthenticated, IsTripOwner]

    def get_itinerary(self, trip_id):
        itinerary = get_object_or_404(Itinerary.objects.select_related('owner'), pk=trip_id)
        self.check_object_permissions(self.request, itinerary)
        return itinerary

    def get_collaboration(self, itinerary, user_id):
        if user_id is None:
            raise ValidationError({'detail': 'A user id is required in the URL.'})
        return get_object_or_404(
            Collaboration.objects.select_related('user', 'invited_by'), itinerary=itinerary, user_id=user_id
        )

    def get(self, request, trip_id, user_id=None):
        itinerary = self.get_itinerary(trip_id)
        collaborations = itinerary.collaborations.select_related('user', 'invited_by')
        if user_id is not None:
            collaborations = collaborations.filter(user_id=user_id)
        return Response(CollaboratorSerializer(collaborations, many=True).data)

    def post(self, request, trip_id, user_id=None):
        itinerary = self.get_itinerary(trip_id)
        serializer = CollaboratorSerializer(
            data=request.data, context={'request': request, 'itinerary': itinerary}
        )
        serializer.is_valid(raise_exception=True)
        collaboration = serializer.save()
        notify_user(
            collaboration.user,
            f'You were added to "{itinerary.title}"',
            f'{request.user.username} added you as {collaboration.get_role_display()} on "{itinerary.title}".',
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def patch(self, request, trip_id, user_id=None):
        itinerary = self.get_itinerary(trip_id)
        collaboration = self.get_collaboration(itinerary, user_id)
        serializer = CollaboratorSerializer(
            collaboration, data=request.data, partial=True,
            context={'request': request, 'itinerary': itinerary},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, trip_id, user_id=None):
        itinerary = self.get_itinerary(trip_id)
        collaboration = self.get_collaboration(itinerary, user_id)
        collaboration.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    get=extend_schema(operation_id='trips_collaborators_list', responses=CollaboratorSerializer(many=True)),
    post=extend_schema(operation_id='trips_collaborators_create', request=CollaboratorSerializer,
                       responses={201: CollaboratorSerializer}),
)
class TripCollaboratorListView(TripCollaborationView):
    """
    GET: List a trip's collaborators.
    POST: Add a collaborator, e.g. {"user": 7, "role": "EDITOR"}. The user is emailed.
    """
    http_method_names = ['get', 'post', 'head', 'options']


# --- ViewSet: full CRUD itineraries ---
@extend_schema_view(
    export_pdf=extend_schema(responses={(200, 'application/pdf'): OpenApiTypes.BINARY}),
    share_with_user=extend_schema(
        request=inline_serializer('ShareRequest', {
            'user_id': serializers.IntegerField(required=False),
            'username': serializers.CharField(required=False),
            'role': serializers.ChoiceField(choices=Collaboration.Role.choices, required=False),
        }),
        responses={201: OpenApiTypes.OBJECT},
    ),
    duplicate=extend_schema(request=inline_serializer('DuplicateRequest', {
        'start_date': serializers.DateField(required=False),
        'title': serializers.CharField(required=False),
    })),
    budget_status=extend_schema(parameters=[
        OpenApiParameter('over_budget', bool), OpenApiParameter('at_risk', bool),
    ]),
    upcoming_trips=extend_schema(parameters=[OpenApiParameter('within_days', int)]),
)
class ItineraryViewSet(viewsets.ModelViewSet):
    """
    CRUD for itineraries the user owns or collaborates on, plus custom actions.

    Permissions: any trip member can read; owners and EDITOR collaborators can update;
    only the owner can delete or share.

    Example:
        POST /api/v1/itineraries/
        {"title": "Paris in spring", "destination": 2, "start_date": "2026-04-01",
         "end_date": "2026-04-05", "generate_daily_plans": true}
        -> 201 {"id": 4, "title": "Paris in spring", "owner": 1, "status": "PLANNING", ...}
    """
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ItineraryFilter
    search_fields = ['title', 'description', 'destination__name']
    ordering_fields = ['created_at', 'start_date', 'budget__total_budget']
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Itinerary.objects.none()

        queryset = accessible_itineraries(self.request.user).select_related(
            'destination', 'destination__category', 'owner', 'budget'
        )
        if self.action in ('list', 'upcoming_trips'):
            return queryset.defer('description').annotate(
                total_activities=Count('daily_plans__activities', distinct=True),
            ).order_by('start_date', 'id')
        return queryset.prefetch_related(
            Prefetch(
                'daily_plans',
                queryset=DailyPlan.objects.order_by('day_number').prefetch_related(
                    Prefetch('activities', queryset=Activity.objects.annotate(
                        booking_count=Count('bookings', filter=~Q(bookings__status=Booking.Status.CANCELLED)),
                    )),
                ),
            ),
            Prefetch(
                'bookings',
                queryset=Booking.objects.exclude(status=Booking.Status.CANCELLED)
                .select_related('accommodation', 'activity'),
                to_attr='active_bookings',
            ),
            Prefetch(
                'collaborations',
                queryset=Collaboration.objects.filter(user__is_active=True).select_related('user', 'invited_by'),
            ),
        )

    def get_serializer_class(self):
        if self.action in ('list', 'upcoming_trips'):
            return ItineraryListSerializer
        if self.action in ('retrieve', 'duplicate'):
            return ItineraryDetailSerializer
        if self.action == 'create':
            return ItineraryCreateSerializer
        return ItineraryUpdateSerializer

    def get_permissions(self):
        if self.action in ('update', 'partial_update'):
            return [IsAuthenticated(), CanEditItinerary()]
        if self.action in ('destroy', 'share_with_user'):
            return [IsAuthenticated(), IsTripOwner()]
        if self.action in ('retrieve', 'export_pdf', 'duplicate'):
            return [IsAuthenticated(), IsTripOwnerOrCollaborator()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """
        Clone an itinerary with its daily plans and budget.
        Optional body: {"start_date": "YYYY-MM-DD", "title": "..."} to shift dates.
        """
        original = self.get_object()
        new_start = request.data.get('start_date')
        new_start = parse_date_param(new_start, 'start_date') if new_start else original.start_date
        shift = new_start - original.start_date

        with transaction.atomic():
            copy = Itinerary.objects.create(
                title=request.data.get('title') or f"Copy of {original.title}",
                description=original.description,
                owner=request.user,
                destination=original.destination,
                start_date=original.start_date + shift,
                end_date=original.end_date + shift,
                travelers=original.travelers,
                status=Itinerary.Status.PLANNING,
            )
            for plan in original.daily_plans.all():
                new_plan = DailyPlan.objects.create(
                    itinerary=copy, day_number=plan.day_number, date=plan.date + shift,
                    title=plan.title, notes=plan.notes,
                )
                new_plan.activities.set(plan.activities.all())
            original_budget = Budget.objects.filter(itinerary=original).first()
            if original_budget:
                Budget.objects.create(
                    itinerary=copy, total_budget=original_budget.total_budget, currency=original_budget.currency
                )

        copy = self.get_queryset().get(pk=copy.pk)
        serializer = self.get_serializer(copy)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def export_pdf(self, request, pk=None):
        """Download the itinerary as a PDF document."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

        itinerary = self.get_object()
        styles = getSampleStyleSheet()
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, title=itinerary.title)

        story = [
            Paragraph(itinerary.title, styles['Title']),
            Paragraph(
                f"{itinerary.destination.name} - {itinerary.destination.city}, {itinerary.destination.country}",
                styles['Heading3'],
            ),
            Paragraph(
                f"{itinerary.start_date:%d %b %Y} to {itinerary.end_date:%d %b %Y} "
                f"({itinerary.duration_days} days, {itinerary.travelers} traveler(s))",
                styles['Normal'],
            ),
            Spacer(1, 12),
        ]
        if itinerary.description:
            story += [Paragraph(itinerary.description, styles['Normal']), Spacer(1, 12)]

        story.append(Paragraph('Daily plan', styles['Heading2']))
        plans = itinerary.daily_plans.all()
        if plans:
            for plan in plans:
                activities = ', '.join(a.title for a in plan.activities.all()) or 'No activities'
                story.append(Paragraph(
                    f"<b>Day {plan.day_number} ({plan.date:%a %d %b})</b> {plan.title} - {activities}",
                    styles['Normal'],
                ))
                if plan.notes:
                    story.append(Paragraph(plan.notes, styles['Italic']))
        else:
            story.append(Paragraph('No daily plans yet.', styles['Normal']))

        story += [Spacer(1, 12), Paragraph('Bookings', styles['Heading2'])]
        rows = [['Type', 'Item', 'Status', 'Price']]
        for booking in itinerary.bookings.select_related('accommodation', 'activity'):
            rows.append([
                booking.get_booking_type_display(), booking.item_name,
                booking.get_status_display(), f"{booking.total_price}",
            ])
        story.append(Table(rows) if len(rows) > 1 else Paragraph('No bookings yet.', styles['Normal']))

        budget = Budget.objects.filter(itinerary=itinerary).first()
        if budget:
            story += [
                Spacer(1, 12),
                Paragraph('Budget', styles['Heading2']),
                Paragraph(
                    f"Total: {budget.total_budget} {budget.currency} | Spent: {budget.total_spent()} | "
                    f"Remaining: {budget.remaining()}",
                    styles['Normal'],
                ),
            ]

        try:
            doc.build(story)
        except Exception as exc:
            # Bad markup in user-entered text (e.g. an unclosed "<b>") makes reportlab raise;
            # report it as a clean 500 instead of a stack trace.
            logger.exception('PDF export failed for itinerary %s', itinerary.pk)
            raise PDFGenerationError() from exc
        buffer.seek(0)
        filename = f"itinerary-{itinerary.pk}.pdf"
        return FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/pdf')

    @action(detail=True, methods=['post'], url_path='share')
    def share_with_user(self, request, pk=None):
        """
        Share with another user. Body: {"user_id": 5} or {"username": "bob"}, optional "role".
        """
        itinerary = self.get_object()
        user_id = request.data.get('user_id')
        username = request.data.get('username')
        if not user_id and not username:
            raise ValidationError({'user_id': 'Provide user_id or username.'})
        target = User.objects.filter(pk=user_id).first() if user_id else User.objects.filter(username=username).first()
        if target is None:
            raise NotFound('User not found.')

        serializer = CollaboratorSerializer(
            data={'user': target.pk, 'role': request.data.get('role', Collaboration.Role.VIEWER)},
            context={'request': request, 'itinerary': itinerary},
        )
        serializer.is_valid(raise_exception=True)
        collaboration = serializer.save()
        email_sent = notify_user(
            target,
            f'"{itinerary.title}" was shared with you',
            f'{request.user.username} shared the trip "{itinerary.title}" with you '
            f'as {collaboration.get_role_display()}.',
        )
        return Response(
            {
                'message': 'Itinerary shared successfully.',
                'collaboration': serializer.data,
                'notification_sent': email_sent,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['get'], url_path='budget-status')
    def budget_status(self, request):
        """
        Budget vs actual spend for every trip that has a budget.

        ?over_budget=true  trips whose bookings exceed the budget, or cost more than 5000
        ?at_risk=true      trips that have used 80% or more of their budget

        Example response item:
            {"id": 3, "title": "Rome", "total_budget": "2000.00",
             "total_cost": "2150.00", "budget_variance": "-150.00"}
        """
        active = ~Q(bookings__status=Booking.Status.CANCELLED)
        money = DecimalField(max_digits=12, decimal_places=2)
        queryset = (
            accessible_itineraries(request.user)
            .filter(budget__isnull=False)
            .select_related('budget', 'destination')
            .only('id', 'title', 'start_date', 'destination__name', 'budget__total_budget', 'budget__currency')
            .annotate(
                total_cost=Coalesce(
                    Sum('bookings__total_price', filter=active), Value(Decimal('0')), output_field=money,
                ),
            )
            .annotate(budget_variance=F('budget__total_budget') - F('total_cost'))
            .order_by('budget_variance')
        )
        if request.query_params.get('over_budget', '').lower() == 'true':
            queryset = queryset.filter(
                Q(total_cost__gt=F('budget__total_budget')) | Q(total_cost__gt=Decimal('5000'))
            )
        if request.query_params.get('at_risk', '').lower() == 'true':
            queryset = queryset.filter(total_cost__gte=F('budget__total_budget') * Decimal('0.8'))

        page = self.paginate_queryset(queryset)
        serializer = ItineraryBudgetStatusSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=['get'], url_path='upcoming')
    def upcoming_trips(self, request):
        """The user's future trips, soonest first."""
        today = timezone.now().date()
        days = request.query_params.get('within_days')
        upcoming = self.get_queryset().filter(start_date__gte=today).exclude(status=Itinerary.Status.CANCELLED)
        if days:
            if not days.isdigit():
                raise ValidationError({'within_days': 'Must be a positive integer.'})
            upcoming = upcoming.filter(start_date__lte=today + timedelta(days=int(days)))
        upcoming = upcoming.order_by('start_date')
        page = self.paginate_queryset(upcoming)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class TripNestedMixin:
    """
    Shared behaviour for resources nested under /trips/<trip_id>/.

    Resolves the trip once per request, returns 404 when the user has no access
    (so trip ids aren't leaked), and applies the view's object permissions
    (e.g. CanEditItinerary) to the trip itself.
    """
    permission_classes = [IsAuthenticated, CanEditItinerary]

    def get_itinerary(self):
        if not hasattr(self, '_itinerary'):
            itinerary = accessible_itineraries(self.request.user).filter(pk=self.kwargs['trip_id']).first()
            if itinerary is None:
                raise NotFound('Itinerary not found or access denied.')
            self.check_object_permissions(self.request, itinerary)
            self._itinerary = itinerary
        return self._itinerary

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False) and 'trip_id' in self.kwargs:
            context['itinerary'] = self.get_itinerary()
        return context

    def perform_create(self, serializer):
        serializer.save(itinerary=self.get_itinerary())


# --- ViewSet: daily plans nested under a trip ---
class DailyPlanViewSet(TripNestedMixin, viewsets.ModelViewSet):
    """
    /trips/<trip_id>/daily-plans/ - any trip member can read;
    owners and editors can create, update and delete.
    """
    serializer_class = DailyPlanSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['date', 'day_number']
    search_fields = ['title', 'notes']
    ordering_fields = ['day_number', 'date']

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DailyPlan.objects.none()
        return self.get_itinerary().daily_plans.prefetch_related('activities')


# --- ViewSet: documents (PDFs / images) attached to a trip ---
@extend_schema_view(
    create=extend_schema(request={'multipart/form-data': TripDocumentSerializer}),
    download=extend_schema(responses={(200, 'application/octet-stream'): OpenApiTypes.BINARY}),
)
class TripDocumentViewSet(TripNestedMixin, viewsets.ModelViewSet):
    """
    /trips/<trip_id>/documents/ - tickets, reservations, visas etc.

    Trip members can list and download; owners and editors can upload and delete.
    Uploads are multipart/form-data; files are validated by size and by content.

    Example:
        curl -X POST -H "Authorization: Bearer <token>" \
             -F title="Flight to Paris" -F document_type=TICKET -F file=@ticket.pdf \
             /api/v1/trips/4/documents/
        -> 201 {"id": 1, "title": "Flight to Paris", "extension": "pdf", "size_bytes": 48213,
                "download_url": "http://.../api/v1/trips/4/documents/1/download/", ...}
    """
    serializer_class = TripDocumentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['document_type']
    ordering_fields = ['created_at', 'title']

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TripDocument.objects.none()
        return self.get_itinerary().documents.select_related('uploaded_by', 'itinerary')

    def perform_create(self, serializer):
        serializer.save(itinerary=self.get_itinerary(), uploaded_by=self.request.user)

    @action(detail=True, methods=['get'])
    def download(self, request, trip_id=None, pk=None):
        """Stream the file to an authorised trip member."""
        document = self.get_object()
        try:
            handle = document.file.open('rb')
        except FileNotFoundError:
            # The database row survived but the file is gone (e.g. storage was cleaned up).
            raise Http404('The file for this document is missing.')
        filename = f"{document.title}.{document.extension}".replace('/', '-')
        return FileResponse(handle, as_attachment=True, filename=filename)
