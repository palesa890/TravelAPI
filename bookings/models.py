from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from destinations.models import Destination
from itineraries.models import Itinerary


class Accommodation(models.Model):
    class Type(models.TextChoices):
        HOTEL = 'HOTEL', 'Hotel'
        HOSTEL = 'HOSTEL', 'Hostel'
        APARTMENT = 'APARTMENT', 'Apartment'
        RESORT = 'RESORT', 'Resort'
        GUESTHOUSE = 'GUESTHOUSE', 'Guesthouse'

    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='accommodations')
    name = models.CharField(max_length=255)
    accommodation_type = models.CharField(max_length=20, choices=Type.choices, default=Type.HOTEL)
    address = models.TextField()
    price_per_night = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['destination', 'price_per_night'])]

    def __str__(self):
        return self.name

    def price_for_stay(self, nights, rooms=1):
        return self.price_per_night * max(int(nights), 1) * max(int(rooms), 1)


class Activity(models.Model):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='activities')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))]
    )
    duration_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']
        verbose_name_plural = 'activities'

    def __str__(self):
        return self.title


class Booking(models.Model):
    class BookingType(models.TextChoices):
        ACCOMMODATION = 'ACCOMMODATION', 'Accommodation'
        ACTIVITY = 'ACTIVITY', 'Activity'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='bookings')
    booking_type = models.CharField(max_length=20, choices=BookingType.choices)
    accommodation = models.ForeignKey(
        Accommodation, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings'
    )
    activity = models.ForeignKey(
        Activity, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    check_in = models.DateField(null=True, blank=True)
    check_out = models.DateField(null=True, blank=True)
    quantity = models.PositiveSmallIntegerField(default=1, help_text='Rooms or tickets.')
    total_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))]
    )
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    booking_date = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-booking_date']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['booking_date']),
        ]

    def __str__(self):
        return f"{self.get_booking_type_display()} - {self.item_name} ({self.user})"

    def clean(self):
        super().clean()
        if self.booking_type == self.BookingType.ACCOMMODATION:
            if not self.accommodation_id:
                raise ValidationError({'accommodation': 'Accommodation bookings require an accommodation.'})
            if self.activity_id:
                raise ValidationError({'activity': 'Accommodation bookings cannot include an activity.'})
        elif self.booking_type == self.BookingType.ACTIVITY:
            if not self.activity_id:
                raise ValidationError({'activity': 'Activity bookings require an activity.'})
            if self.accommodation_id:
                raise ValidationError({'accommodation': 'Activity bookings cannot include an accommodation.'})
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValidationError({'check_out': 'Check-out must be after check-in.'})

    @property
    def item(self):
        return self.accommodation if self.booking_type == self.BookingType.ACCOMMODATION else self.activity

    @property
    def item_name(self):
        item = self.item
        return str(item) if item else 'Unknown item'

    @property
    def nights(self):
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return None

    def calculate_total_price(self):
        """Price from the booked item: nights x rooms, or tickets x price."""
        qty = self.quantity or 1
        if self.booking_type == self.BookingType.ACCOMMODATION and self.accommodation:
            return self.accommodation.price_for_stay(self.nights or 1, qty)
        if self.booking_type == self.BookingType.ACTIVITY and self.activity:
            return self.activity.price * qty
        return Decimal('0.00')

    def calculate_refund(self, on_date=None):
        """
        Refund policy based on days before the trip starts:
        14+ days: 100%, 7-13 days: 50%, 2-6 days: 25%, otherwise nothing.
        """
        if self.status == self.Status.CANCELLED:
            return Decimal('0.00')
        on_date = on_date or timezone.now().date()
        start = self.check_in or self.itinerary.start_date
        days_before = (start - on_date).days
        if days_before >= 14:
            rate = Decimal('1.00')
        elif days_before >= 7:
            rate = Decimal('0.50')
        elif days_before >= 2:
            rate = Decimal('0.25')
        else:
            rate = Decimal('0.00')
        return (self.total_price * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def confirm(self):
        if self.status != self.Status.PENDING:
            raise ValidationError(f'Only pending bookings can be confirmed (current: {self.status}).')
        self.status = self.Status.CONFIRMED
        self.confirmed_at = timezone.now()
        self.save(update_fields=['status', 'confirmed_at', 'updated_at'])

    def cancel(self):
        if self.status == self.Status.CANCELLED:
            raise ValidationError('Booking is already cancelled.')
        self.refund_amount = self.calculate_refund()
        self.status = self.Status.CANCELLED
        self.cancelled_at = timezone.now()
        self.save(update_fields=['status', 'refund_amount', 'cancelled_at', 'updated_at'])
        return self.refund_amount
