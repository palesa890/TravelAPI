from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from destinations.models import Destination


class Review(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=255, blank=True, default='')
    comment = models.TextField()
    visited_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'destination')
        indexes = [models.Index(fields=['destination', 'rating'])]

    def __str__(self):
        return f"{self.destination.name} - {self.rating} Stars"

    def clean(self):
        super().clean()
        if self.visited_on and self.visited_on > timezone.now().date():
            raise ValidationError({'visited_on': 'Visit date cannot be in the future.'})

    def is_positive(self):
        return self.rating >= 4
