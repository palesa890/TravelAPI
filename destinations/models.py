from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Avg
from django.utils.text import slugify

from travel_api.uploads import UniqueUploadPath
from travel_api.validators import validate_file_size, validate_image_file


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Destination(models.Model):
    class Climate(models.TextChoices):
        TROPICAL = 'TROPICAL', 'Tropical'
        DRY = 'DRY', 'Dry / Desert'
        TEMPERATE = 'TEMPERATE', 'Temperate'
        MEDITERRANEAN = 'MEDITERRANEAN', 'Mediterranean'
        CONTINENTAL = 'CONTINENTAL', 'Continental'
        POLAR = 'POLAR', 'Polar'

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    description = models.TextField()
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='destinations'
    )
    climate = models.CharField(max_length=20, choices=Climate.choices, default=Climate.TEMPERATE)
    average_cost_per_day = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    cover_image = models.ImageField(
        upload_to=UniqueUploadPath('destinations/covers'), blank=True, null=True,
        validators=[validate_file_size, validate_image_file],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['country', 'city']),
            models.Index(fields=['climate']),
        ]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.country})"

    def clean(self):
        super().clean()
        for field in ('name', 'country', 'city'):
            value = getattr(self, field) or ''
            if not value.strip():
                raise ValidationError({field: 'This field cannot be blank.'})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.build_unique_slug()
        super().save(*args, **kwargs)

    def build_unique_slug(self):
        base = slugify(f"{self.name}-{self.city}")[:280] or 'destination'
        slug, n = base, 2
        while Destination.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    def average_rating(self):
        avg = self.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(avg, 2) if avg is not None else None

    def estimated_trip_cost(self, days, travelers=1):
        """Rough cost estimate for a stay of `days` days."""
        return self.average_cost_per_day * max(int(days), 0) * max(int(travelers), 1)


class DestinationPhoto(models.Model):
    """User-contributed photo of a destination."""
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(
        upload_to=UniqueUploadPath('destinations/photos'),
        validators=[validate_file_size, validate_image_file],
    )
    caption = models.CharField(max_length=255, blank=True, default='')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='destination_photos',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Photo of {self.destination.name}"


class SearchPreference(models.Model):
    """A saved search a user can re-run later (destinations or trips)."""

    class Scope(models.TextChoices):
        DESTINATION = 'DESTINATION', 'Destination search'
        TRIP = 'TRIP', 'Trip search'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='search_preferences'
    )
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.DESTINATION)
    name = models.CharField(max_length=100, blank=True, default='')
    query = models.CharField(max_length=255, blank=True, default='')
    country = models.CharField(max_length=100, blank=True, default='')
    climate = models.CharField(max_length=20, choices=Destination.Climate.choices, blank=True, default='')
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='search_preferences'
    )
    min_budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'scope'])]

    def __str__(self):
        return f"{self.user} - {self.name or self.query or self.get_scope_display()}"

    def clean(self):
        super().clean()
        if self.min_budget is not None and self.min_budget < 0:
            raise ValidationError({'min_budget': 'Minimum budget cannot be negative.'})
        if (
            self.min_budget is not None and self.max_budget is not None
            and self.min_budget > self.max_budget
        ):
            raise ValidationError({'max_budget': 'Maximum budget must be greater than minimum budget.'})
