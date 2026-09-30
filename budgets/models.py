from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from itineraries.models import Itinerary


class Budget(models.Model):
    itinerary = models.OneToOneField(Itinerary, on_delete=models.CASCADE, related_name='budget')
    total_budget = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))]
    )
    currency = models.CharField(max_length=3, default='USD')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Budget for {self.itinerary.title}"

    def clean(self):
        super().clean()
        if self.currency:
            self.currency = self.currency.upper()
            if len(self.currency) != 3 or not self.currency.isalpha():
                raise ValidationError({'currency': 'Currency must be a 3-letter ISO code.'})

    def total_expenses(self):
        return self.expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    def total_booked(self):
        return Decimal(self.itinerary.total_booking_cost())

    def total_spent(self):
        return self.total_expenses() + self.total_booked()

    def remaining(self):
        return self.total_budget - self.total_spent()

    def is_over_budget(self):
        return self.remaining() < 0

    def spending_by_category(self):
        return {
            row['category']: row['total']
            for row in self.expenses.values('category').annotate(total=Sum('amount'))
        }


class Expense(models.Model):
    class Category(models.TextChoices):
        FOOD = 'FOOD', 'Food & Dining'
        TRANSPORT = 'TRANSPORT', 'Transportation'
        ACCOMMODATION = 'ACCOMMODATION', 'Accommodation'
        ACTIVITIES = 'ACTIVITIES', 'Activities'
        SHOPPING = 'SHOPPING', 'Shopping'
        OTHER = 'OTHER', 'Other'

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='expenses')
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [models.Index(fields=['budget', 'category'])]

    def __str__(self):
        return f"{self.title} - {self.amount}"

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({'amount': 'Expense amount must be greater than zero.'})
