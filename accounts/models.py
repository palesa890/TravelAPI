from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from travel_api.uploads import UniqueUploadPath
from travel_api.validators import validate_file_size, validate_image_file


class User(AbstractUser):
    class TravelStyle(models.TextChoices):
        BUDGET = 'BUDGET', 'Budget'
        COMFORT = 'COMFORT', 'Comfort'
        LUXURY = 'LUXURY', 'Luxury'
        ADVENTURE = 'ADVENTURE', 'Adventure'

    bio = models.TextField(blank=True, default='')
    profile_picture = models.ImageField(
        upload_to=UniqueUploadPath('profiles'), blank=True, null=True,
        validators=[validate_file_size, validate_image_file],
    )
    date_of_birth = models.DateField(blank=True, null=True)
    home_country = models.CharField(max_length=100, blank=True, default='')
    travel_style = models.CharField(max_length=20, choices=TravelStyle.choices, default=TravelStyle.COMFORT)
    travel_preferences = models.JSONField(default=dict, blank=True)
    favorite_destinations = models.ManyToManyField(
        'destinations.Destination', related_name='favorited_by', blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['username']

    def __str__(self):
        return self.username

    def clean(self):
        super().clean()
        if self.date_of_birth and self.date_of_birth > timezone.now().date():
            raise ValidationError({'date_of_birth': 'Date of birth cannot be in the future.'})
        if not isinstance(self.travel_preferences, dict):
            raise ValidationError({'travel_preferences': 'Travel preferences must be a JSON object.'})

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.now().date()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def upcoming_trips(self):
        return self.owned_itineraries.filter(start_date__gte=timezone.now().date()).order_by('start_date')

    def total_spent(self):
        from bookings.models import Booking
        total = (
            self.bookings.exclude(status=Booking.Status.CANCELLED)
            .aggregate(total=Sum('total_price'))['total']
        )
        return total or 0
