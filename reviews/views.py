from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from destinations.models import Destination
from travel_api.pagination import ReviewPagination

from .filters import ReviewFilter
from .models import Review
from .permissions import IsReviewAuthorOrReadOnly
from .serializers import ReviewCreateSerializer, ReviewSerializer, ReviewUpdateSerializer


class ReviewViewSet(viewsets.ModelViewSet):
    """
    Destination reviews. Anyone can read; authenticated users can post one review
    per destination; only the author can edit or delete.
    """
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ReviewFilter
    search_fields = ['title', 'comment', 'destination__name']
    ordering_fields = ['created_at', 'rating']
    pagination_class = ReviewPagination
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        return Review.objects.select_related('user', 'destination')

    def get_serializer_class(self):
        if self.action == 'create':
            return ReviewCreateSerializer
        if self.action in ('update', 'partial_update'):
            return ReviewUpdateSerializer
        return ReviewSerializer

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsReviewAuthorOrReadOnly()]
        if self.action == 'mine':
            return [IsAuthenticated()]
        return [IsAuthenticatedOrReadOnly()]

    @action(detail=False, methods=['get'])
    def mine(self, request):
        """Reviews written by the current user."""
        queryset = self.filter_queryset(self.get_queryset().filter(user=request.user))
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class DestinationReviewListCreateView(generics.ListCreateAPIView):
    """
    /destinations/<destination_pk>/reviews/
    GET: Reviews for one destination. POST: Review it (destination taken from the URL).
    """
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = ReviewPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = ReviewFilter
    ordering_fields = ['created_at', 'rating']

    def get_destination(self):
        return get_object_or_404(Destination, pk=self.kwargs['destination_pk'])

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        return Review.objects.filter(destination=self.get_destination()).select_related('user', 'destination')

    def get_serializer_class(self):
        return ReviewCreateSerializer if self.request.method == 'POST' else ReviewSerializer

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data['destination'] = self.get_destination().pk
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UserReviewListView(generics.ListAPIView):
    """/reviews/by-user/<username>/ - all reviews written by a user."""
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = ReviewPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        return Review.objects.filter(
            user__username=self.kwargs['username']
        ).select_related('user', 'destination')
