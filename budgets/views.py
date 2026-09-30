# budgets/views.py
from decimal import Decimal

from django.db.models import Avg, Count, F, Q, Sum
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bookings.models import Booking
from itineraries.models import Itinerary
from itineraries.permissions import CanEditItinerary
from travel_api.pagination import paginated_response

from .models import Budget, Expense
from .serializers import BudgetSerializer, ExpenseSerializer


def accessible_budgets(user):
    return Budget.objects.filter(
        Q(itinerary__owner=user) | Q(itinerary__collaborators=user)
    ).distinct()


# --- FBV 4: List & add expenses for a budget ---
@extend_schema(methods=['GET'], operation_id='budgets_expenses_list', responses=ExpenseSerializer(many=True),
               parameters=[OpenApiParameter('category', str, enum=Expense.Category.values)])
@extend_schema(methods=['POST'], operation_id='budgets_expenses_create', request=ExpenseSerializer,
               responses={201: ExpenseSerializer})
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def budget_expenses(request, budget_id):
    """
    GET: List a budget's expenses (filter with ?category=FOOD) plus totals.
    POST: Add an expense (owners and editors only).
    """
    budget = get_object_or_404(
        accessible_budgets(request.user).select_related('itinerary'), pk=budget_id
    )

    if request.method == 'GET':
        expenses = budget.expenses.all()
        category = request.query_params.get('category')
        if category:
            if category.upper() not in Expense.Category.values:
                raise ValidationError({'category': f'Choose one of: {", ".join(Expense.Category.values)}.'})
            expenses = expenses.filter(category=category.upper())
        response = paginated_response(request, expenses, ExpenseSerializer)
        response.data['summary'] = {
            'total_budget': budget.total_budget,
            'total_expenses': budget.total_expenses(),
            'remaining_balance': budget.remaining(),
            'by_category': budget.spending_by_category(),
        }
        return response

    if not budget.itinerary.can_edit(request.user):
        raise PermissionDenied('Only the trip owner or editors can add expenses.')
    serializer = ExpenseSerializer(data=request.data, context={'request': request, 'budget': budget})
    serializer.is_valid(raise_exception=True)
    serializer.save(budget=budget)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


# --- CBV: single expense nested under its budget ---
class ExpenseDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    /budgets/<budget_id>/expenses/<pk>/ - trip members can read;
    owners and editors can update or delete.
    """
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, CanEditItinerary]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Expense.objects.none()
        return Expense.objects.filter(
            budget_id=self.kwargs['budget_id'],
            budget__in=accessible_budgets(self.request.user),
        ).select_related('budget__itinerary')

    def check_object_permissions(self, request, obj):
        # Permissions are defined on the itinerary the expense belongs to.
        super().check_object_permissions(request, obj.budget.itinerary)


# --- ViewSet: budgets ---
class BudgetViewSet(viewsets.ModelViewSet):
    """
    CRUD for budgets attached to itineraries the user can access.
    """
    serializer_class = BudgetSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['itinerary', 'currency']
    search_fields = ['itinerary__title']
    ordering_fields = ['total_budget', 'created_at']
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Budget.objects.none()

        return (
            accessible_budgets(self.request.user)
            .select_related('itinerary')
            .prefetch_related('expenses')
        )

    def perform_destroy(self, instance):
        if instance.itinerary.owner_id != self.request.user.id:
            raise PermissionDenied('Only the trip owner can delete its budget.')
        instance.delete()


# --- ViewSet: custom analytics ---
@extend_schema_view(
    list=extend_schema(responses=OpenApiTypes.OBJECT),
    budget_summary=extend_schema(responses=OpenApiTypes.OBJECT),
    destination_preferences=extend_schema(responses=OpenApiTypes.OBJECT),
)
class TripAnalyticsViewSet(viewsets.ViewSet):
    """
    Aggregate trip and spending analytics for the current user.
    """
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Overall trip statistics."""
        if getattr(self, "swagger_fake_view", False):
            return Response([])

        trips = Itinerary.objects.filter(owner=request.user)
        active_bookings = Booking.objects.filter(user=request.user).exclude(status=Booking.Status.CANCELLED)

        durations = [trip.duration_days for trip in trips.only('start_date', 'end_date')]
        total_trips = len(durations)
        total_spent = active_bookings.aggregate(total=Sum('total_price'))['total'] or Decimal('0')

        return Response({
            'total_trips': total_trips,
            'trips_by_status': {
                row['status']: row['count'] for row in trips.values('status').annotate(count=Count('id'))
            },
            'total_days_traveling': sum(durations),
            'average_trip_length_days': round(sum(durations) / total_trips, 1) if total_trips else 0,
            'countries_visited': trips.values('destination__country').distinct().count(),
            'total_bookings': active_bookings.count(),
            'total_spent': total_spent,
            'average_spent_per_trip': round(total_spent / total_trips, 2) if total_trips else 0,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def budget_summary(self, request):
        """Spending by category and budget vs actual for each trip."""
        if getattr(self, "swagger_fake_view", False):
            return Response({})

        bookings = Booking.objects.filter(user=request.user).exclude(status=Booking.Status.CANCELLED)
        by_booking_type = bookings.values('booking_type').annotate(
            total_spent=Sum('total_price'), booking_count=Count('id')
        )
        expenses = Expense.objects.filter(budget__itinerary__owner=request.user)
        by_expense_category = expenses.values('category').annotate(
            total_spent=Sum('amount'), expense_count=Count('id')
        ).order_by('-total_spent')

        trips = []
        budgets = Budget.objects.filter(itinerary__owner=request.user).select_related('itinerary')
        for budget in budgets:
            spent = budget.total_spent()
            trips.append({
                'itinerary_id': budget.itinerary_id,
                'title': budget.itinerary.title,
                'budget': budget.total_budget,
                'spent': spent,
                'difference': budget.total_budget - spent,
                'over_budget': spent > budget.total_budget,
            })

        return Response({
            'spending_by_booking_type': list(by_booking_type),
            'spending_by_expense_category': list(by_expense_category),
            'budget_vs_actual': trips,
            'trips_over_budget': sum(1 for t in trips if t['over_budget']),
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def destination_preferences(self, request):
        """Which countries, climates and categories the user travels to most."""
        if getattr(self, "swagger_fake_view", False):
            return Response({})

        trips = Itinerary.objects.filter(owner=request.user)
        by_country = trips.values(country=F('destination__country')).annotate(
            visit_count=Count('id')
        ).order_by('-visit_count')
        by_climate = trips.values(climate=F('destination__climate')).annotate(
            visit_count=Count('id')
        ).order_by('-visit_count')
        by_category = trips.exclude(destination__category__isnull=True).values(
            category=F('destination__category__name')
        ).annotate(visit_count=Count('id')).order_by('-visit_count')
        avg_rating_given = request.user.reviews.aggregate(avg=Avg('rating'))['avg']

        return Response({
            'by_country': list(by_country),
            'by_climate': list(by_climate),
            'by_category': list(by_category),
            'favorite_country': by_country[0]['country'] if by_country else None,
            'average_rating_given': round(avg_rating_given, 2) if avg_rating_given else None,
        }, status=status.HTTP_200_OK)
