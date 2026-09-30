# destinations/views.py
from django.db.models import Avg, Case, Count, IntegerField, Prefetch, Q, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view, inline_serializer
from rest_framework import filters, generics, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView

from bookings.models import Activity, Booking
from bookings.serializers import ActivitySerializer
from reviews.models import Review
from travel_api.pagination import LargeResultsPagination, paginated_response
from travel_api.permissions import IsUploaderOrAdmin

from .filters import DestinationFilter
from .models import Category, Destination, DestinationPhoto, SearchPreference
from .serializers import (
    CategorySerializer,
    DestinationDetailSerializer,
    DestinationListSerializer,
    DestinationPhotoSerializer,
    DestinationSerializer,
    SearchPreferenceSerializer,
)

# Seasonal guidance returned by the weather_info action.
CLIMATE_INFO = {
    Destination.Climate.TROPICAL: {
        'average_temp_celsius': 28,
        'best_months': ['December', 'January', 'February', 'March'],
        'rainy_season': 'May - October',
    },
    Destination.Climate.DRY: {
        'average_temp_celsius': 30,
        'best_months': ['November', 'December', 'January', 'February'],
        'rainy_season': 'Rare rainfall',
    },
    Destination.Climate.TEMPERATE: {
        'average_temp_celsius': 16,
        'best_months': ['May', 'June', 'September'],
        'rainy_season': 'Spread throughout the year',
    },
    Destination.Climate.MEDITERRANEAN: {
        'average_temp_celsius': 20,
        'best_months': ['April', 'May', 'September', 'October'],
        'rainy_season': 'November - February',
    },
    Destination.Climate.CONTINENTAL: {
        'average_temp_celsius': 10,
        'best_months': ['June', 'July', 'August'],
        'rainy_season': 'Summer storms',
    },
    Destination.Climate.POLAR: {
        'average_temp_celsius': -10,
        'best_months': ['June', 'July'],
        'rainy_season': 'Snow most of the year',
    },
}


def annotated_destinations():
    return Destination.objects.select_related('category').annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews', distinct=True),
    ).order_by('name')


# --- CBV 1: Advanced destination search with ranking ---
@extend_schema_view(
    get=extend_schema(
        parameters=[
            OpenApiParameter('q', str, description='Matched against name, city, country and description.'),
            OpenApiParameter('country', str), OpenApiParameter('city', str),
            OpenApiParameter('climate', str, enum=Destination.Climate.values),
            OpenApiParameter('category', str, description='Category ID or name.'),
            OpenApiParameter('min_cost', float), OpenApiParameter('max_cost', float),
            OpenApiParameter('min_rating', float),
        ],
        responses=DestinationListSerializer(many=True),
    ),
    post=extend_schema(request=SearchPreferenceSerializer, responses={201: SearchPreferenceSerializer}),
)
class DestinationSearchView(APIView):
    """
    GET: Search destinations with filters and a relevance ranking.
         Params: q, country, city, climate, category, min_cost, max_cost, min_rating
         Ranking: exact name > name contains > city/country > description, then rating, then popularity.
    POST: Save the search as a user preference (login required).

    Example:
        GET /api/v1/destinations/search/?q=bali&climate=TROPICAL&max_cost=120
        -> {"count": 1, "results": [{"id": 1, "name": "Bali", "slug": "bali-denpasar",
                                     "average_rating": 4.5, "average_cost_per_day": "80.00", ...}]}
    """
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request):
        params = request.query_params
        query = params.get('q', '').strip()
        queryset = annotated_destinations().annotate(
            popularity=Count('itineraries', distinct=True),
        )

        filters_q = Q()
        if query:
            filters_q &= (
                Q(name__icontains=query) | Q(city__icontains=query)
                | Q(country__icontains=query) | Q(description__icontains=query)
            )
        if params.get('country'):
            filters_q &= Q(country__icontains=params['country'])
        if params.get('city'):
            filters_q &= Q(city__icontains=params['city'])
        if params.get('climate'):
            filters_q &= Q(climate__iexact=params['climate'])
        if params.get('category'):
            category = params['category']
            filters_q &= Q(category_id=category) if category.isdigit() else Q(category__name__iexact=category)
        try:
            if params.get('min_cost'):
                filters_q &= Q(average_cost_per_day__gte=float(params['min_cost']))
            if params.get('max_cost'):
                filters_q &= Q(average_cost_per_day__lte=float(params['max_cost']))
            min_rating = float(params['min_rating']) if params.get('min_rating') else None
        except ValueError:
            raise ValidationError({'detail': 'min_cost, max_cost and min_rating must be numbers.'})

        queryset = queryset.filter(filters_q)
        if min_rating is not None:
            queryset = queryset.filter(avg_rating__gte=min_rating)

        # Ranking: text relevance first, then rating, then popularity.
        if query:
            queryset = queryset.annotate(
                relevance=Case(
                    When(name__iexact=query, then=Value(100)),
                    When(name__icontains=query, then=Value(50)),
                    When(Q(city__icontains=query) | Q(country__icontains=query), then=Value(30)),
                    default=Value(10),
                    output_field=IntegerField(),
                )
            )
        else:
            queryset = queryset.annotate(relevance=Value(0, output_field=IntegerField()))
        queryset = queryset.order_by('-relevance', Coalesce('avg_rating', 0.0).desc(), '-popularity', 'name')

        return paginated_response(request, queryset, DestinationListSerializer, view=self)

    def post(self, request):
        serializer = SearchPreferenceSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user, scope=SearchPreference.Scope.DESTINATION)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


FavoriteStatusSerializer = inline_serializer('FavoriteStatus', {
    'destination': serializers.IntegerField(),
    'is_favorite': serializers.BooleanField(),
    'favorite_count': serializers.IntegerField(),
})
MessageSerializer = inline_serializer('Message', {'message': serializers.CharField()})


# --- CBV 2: Favorite destinations ---
@extend_schema_view(
    get=extend_schema(responses=FavoriteStatusSerializer),
    post=extend_schema(request=None, responses={201: MessageSerializer}),
    delete=extend_schema(responses={204: None}),
)
class DestinationFavoriteView(APIView):
    """
    GET: Whether the destination is in the user's favorites.
    POST: Add destination to favorites.
    DELETE: Remove destination from favorites.
    """
    permission_classes = [IsAuthenticated]

    def get_destination(self, pk):
        # Only the id and name are needed here.
        return get_object_or_404(Destination.objects.only('id', 'name'), pk=pk)

    def get(self, request, pk):
        destination = self.get_destination(pk)
        return Response({
            'destination': destination.id,
            'is_favorite': request.user.favorite_destinations.filter(pk=destination.pk).exists(),
            'favorite_count': destination.favorited_by.count(),
        })

    def post(self, request, pk):
        destination = self.get_destination(pk)
        request.user.favorite_destinations.add(destination)
        return Response({'message': f'{destination.name} added to favorites.'}, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        destination = self.get_destination(pk)
        request.user.favorite_destinations.remove(destination)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- CBV 3: Destination lookup by slug ---
class DestinationBySlugView(generics.RetrieveAPIView):
    """GET: Destination detail by its URL slug, e.g. /destinations/slug/bali-denpasar/."""
    serializer_class = DestinationDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return annotated_destinations().prefetch_related('accommodations')


# --- ViewSet: read-only categories ---
class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse destination categories."""
    queryset = Category.objects.annotate(destination_count=Count('destinations')).order_by('name')
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'destination_count']
    lookup_value_regex = r'\d+'


# --- ViewSet: destinations ---
class DestinationViewSet(viewsets.ModelViewSet):
    """
    Browse destinations (anyone), create (authenticated users),
    update/delete (admins only), plus stats and weather actions.
    """
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DestinationFilter
    search_fields = ['name', 'description', 'country', 'city']
    ordering_fields = ['name', 'average_cost_per_day', 'created_at', 'avg_rating']
    pagination_class = LargeResultsPagination
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        queryset = annotated_destinations()
        if self.action == 'retrieve':
            queryset = queryset.prefetch_related(
                'accommodations',
                Prefetch(
                    'reviews',
                    queryset=Review.objects.select_related('user').order_by('-created_at'),
                    to_attr='prefetched_reviews',
                ),
            )
        return queryset

    def get_serializer_class(self):
        if self.action in ('list', 'favorites'):
            return DestinationListSerializer
        if self.action == 'retrieve':
            return DestinationDetailSerializer
        return DestinationSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'popular_activities', 'weather_info'):
            return [AllowAny()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsAdminUser()]
        return [IsAuthenticated()]

    @action(detail=True, methods=['get'])
    def popular_activities(self, request, pk=None):
        """Activities at this destination ranked by number of active bookings."""
        destination = self.get_object()
        activities = (
            Activity.objects.filter(destination=destination)
            .annotate(booking_count=Count('bookings', filter=~Q(bookings__status=Booking.Status.CANCELLED)))
            .order_by('-booking_count', 'title')[:10]
        )
        return Response({
            'destination': destination.name,
            'popular_activities': ActivitySerializer(activities, many=True, context={'request': request}).data,
        })

    @action(detail=True, methods=['get'])
    def weather_info(self, request, pk=None):
        """Seasonal weather guidance based on the destination's climate."""
        destination = self.get_object()
        info = CLIMATE_INFO.get(destination.climate, CLIMATE_INFO[Destination.Climate.TEMPERATE])
        return Response({
            'destination': destination.name,
            'climate': destination.get_climate_display(),
            **info,
        })

    @action(detail=False, methods=['get'])
    def favorites(self, request):
        """The current user's favorite destinations."""
        queryset = self.get_queryset().filter(favorited_by=request.user)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)


# --- ViewSet: destination photo uploads (nested) ---
@extend_schema_view(create=extend_schema(request={'multipart/form-data': DestinationPhotoSerializer}))
class DestinationPhotoViewSet(viewsets.ModelViewSet):
    """
    /destinations/<destination_pk>/photos/

    Anyone can browse photos; logged-in users can upload (multipart/form-data);
    only the uploader or an admin can delete.

    Example:
        curl -X POST -H "Authorization: Bearer <token>" -F image=@beach.jpg -F caption="Sunset" \
             /api/v1/destinations/1/photos/
    """
    serializer_class = DestinationPhotoSerializer
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_destination(self):
        return get_object_or_404(Destination.objects.only('id', 'name'), pk=self.kwargs['destination_pk'])

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DestinationPhoto.objects.none()
        return DestinationPhoto.objects.filter(destination=self.get_destination()).select_related('uploaded_by')

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        if self.action == 'destroy':
            return [IsAuthenticated(), IsUploaderOrAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(destination=self.get_destination(), uploaded_by=self.request.user)
