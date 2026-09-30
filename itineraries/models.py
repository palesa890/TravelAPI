from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from destinations.models import Destination
from travel_api.uploads import UniqueUploadPath
from travel_api.validators import validate_document_file, validate_file_size


class Itinerary(models.Model):
    class Status(models.TextChoices):
        PLANNING = 'PLANNING', 'Planning'
        BOOKED = 'BOOKED', 'Booked'
        ONGOING = 'ONGOING', 'Ongoing'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_itineraries'
    )
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='itineraries')
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    travelers = models.PositiveSmallIntegerField(default=1)
    is_public = models.BooleanField(default=False)
    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='Collaboration',
        through_fields=('itinerary', 'user'),
        related_name='shared_itineraries',
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_date']
        verbose_name_plural = 'itineraries'
        indexes = [
            models.Index(fields=['owner', 'start_date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date cannot be before start date.'})
        if self.travelers is not None and self.travelers < 1:
            raise ValidationError({'travelers': 'At least one traveler is required.'})

    @property
    def duration_days(self):
        if not (self.start_date and self.end_date):
            return 0
        return (self.end_date - self.start_date).days + 1

    def is_upcoming(self):
        return self.start_date >= timezone.now().date()

    def total_booking_cost(self):
        from bookings.models import Booking
        prefetched = getattr(self, 'active_bookings', None)
        if prefetched is not None:
            return sum((b.total_price for b in prefetched), 0)
        total = (
            self.bookings.exclude(status=Booking.Status.CANCELLED)
            .aggregate(total=Sum('total_price'))['total']
        )
        return total or 0

    def get_role(self, user):
        """Return 'OWNER', a Collaboration role, or None for the given user."""
        if not user or not user.is_authenticated:
            return None
        if self.owner_id == user.id:
            return 'OWNER'
        # Iterating .all() reuses prefetched collaborations when the queryset has them.
        collab = next((c for c in self.collaborations.all() if c.user_id == user.id), None)
        return collab.role if collab else None

    def can_edit(self, user):
        return self.get_role(user) in ('OWNER', Collaboration.Role.EDITOR)

    def can_view(self, user):
        return self.is_public or self.get_role(user) is not None

    def add_collaborator(self, user, role=None, invited_by=None):
        """Add (or update the role of) a collaborator. Role is case-insensitive."""
        role = (role or Collaboration.Role.VIEWER).upper()
        if role not in Collaboration.Role.values:
            raise ValidationError({'role': f'Role must be one of {", ".join(Collaboration.Role.values)}.'})
        if user.pk == self.owner_id:
            raise ValidationError({'user': 'The trip owner cannot be added as a collaborator.'})
        collaboration, _ = Collaboration.objects.update_or_create(
            itinerary=self, user=user, defaults={'role': role, 'invited_by': invited_by},
        )
        return collaboration

    def generate_daily_plans(self):
        """Create an empty DailyPlan for each day of the trip that doesn't have one."""
        existing = set(self.daily_plans.values_list('day_number', flat=True))
        plans = [
            DailyPlan(itinerary=self, day_number=i + 1, date=self.start_date + timedelta(days=i))
            for i in range(self.duration_days)
            if i + 1 not in existing
        ]
        return DailyPlan.objects.bulk_create(plans)


class DailyPlan(models.Model):
    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='daily_plans')
    day_number = models.PositiveIntegerField()
    date = models.DateField()
    title = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    activities = models.ManyToManyField('bookings.Activity', related_name='daily_plans', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['day_number']
        unique_together = ('itinerary', 'day_number')

    def __str__(self):
        return f"{self.itinerary.title} - Day {self.day_number}"

    def clean(self):
        super().clean()
        if self.itinerary_id and self.date:
            itinerary = self.itinerary
            if not (itinerary.start_date <= self.date <= itinerary.end_date):
                raise ValidationError({'date': 'Date must fall within the itinerary dates.'})
            if self.day_number and self.day_number > itinerary.duration_days:
                raise ValidationError({'day_number': 'Day number exceeds the trip length.'})


class Collaboration(models.Model):
    """Through model linking users to itineraries they collaborate on."""

    class Role(models.TextChoices):
        EDITOR = 'EDITOR', 'Editor'
        VIEWER = 'VIEWER', 'Viewer'

    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='collaborations')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='collaborations'
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sent_invitations',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        unique_together = ('itinerary', 'user')

    def __str__(self):
        return f"{self.user} - {self.itinerary} ({self.role})"

    def clean(self):
        super().clean()
        if self.itinerary_id and self.user_id and self.itinerary.owner_id == self.user_id:
            raise ValidationError({'user': 'The trip owner cannot be added as a collaborator.'})


class TripDocument(models.Model):
    """A file attached to a trip: tickets, reservations, visas, insurance (PDF or image)."""

    class DocumentType(models.TextChoices):
        TICKET = 'TICKET', 'Ticket'
        RESERVATION = 'RESERVATION', 'Reservation'
        VISA = 'VISA', 'Visa'
        INSURANCE = 'INSURANCE', 'Insurance'
        OTHER = 'OTHER', 'Other'

    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=255)
    document_type = models.CharField(max_length=20, choices=DocumentType.choices, default=DocumentType.OTHER)
    file = models.FileField(
        upload_to=UniqueUploadPath('itineraries/documents'),
        validators=[validate_file_size, validate_document_file],
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='trip_documents',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.itinerary.title})"

    @property
    def extension(self) -> str:
        return self.file.name.rsplit('.', 1)[-1].lower() if self.file else ''
