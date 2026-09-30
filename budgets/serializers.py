from datetime import timedelta
from decimal import Decimal

from rest_framework import serializers

from travel_api.serializers import BaseModelSerializer

from .models import Budget, Expense


class ExpenseSerializer(BaseModelSerializer):
    class Meta:
        model = Expense
        fields = ('id', 'budget', 'title', 'amount', 'category', 'date', 'notes', 'created_at', 'updated_at')
        read_only_fields = ('budget',)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Expense amount must be greater than zero.')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        budget = self.context.get('budget') or getattr(self.instance, 'budget', None)
        date = attrs.get('date')
        # Pre-trip expenses (flights, deposits) are fine; post-trip ones must be within 30 days.
        if budget and date and date > budget.itinerary.end_date + timedelta(days=30):
            raise serializers.ValidationError({'date': 'Expense date is too long after the trip ended.'})
        return attrs


class BudgetSerializer(BaseModelSerializer):
    expenses = ExpenseSerializer(many=True, read_only=True)
    itinerary_title = serializers.CharField(source='itinerary.title', read_only=True)
    total_expenses = serializers.SerializerMethodField()
    total_booked = serializers.SerializerMethodField()
    remaining_balance = serializers.SerializerMethodField()
    is_over_budget = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = (
            'id', 'itinerary', 'itinerary_title', 'total_budget', 'currency', 'total_expenses',
            'total_booked', 'remaining_balance', 'is_over_budget', 'expenses', 'created_at', 'updated_at',
        )
        extra_kwargs = {
            'itinerary': {'help_text': 'Trip to budget for; one budget per trip.'},
            'total_budget': {'help_text': 'Planned spend for the whole trip.'},
            'currency': {'help_text': 'ISO 4217 code, e.g. USD or EUR.'},
        }

    def get_total_expenses(self, obj) -> Decimal:
        return obj.total_expenses()

    def get_total_booked(self, obj) -> Decimal:
        return obj.total_booked()

    def get_remaining_balance(self, obj) -> Decimal:
        return obj.remaining()

    def get_is_over_budget(self, obj) -> bool:
        return obj.is_over_budget()

    def validate_total_budget(self, value):
        if value < 0:
            raise serializers.ValidationError('Total budget cannot be negative.')
        return value

    def validate_currency(self, value):
        return value.upper()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        itinerary = attrs.get('itinerary')
        if self.instance is not None and itinerary and itinerary != self.instance.itinerary:
            raise serializers.ValidationError({'itinerary': 'A budget cannot be moved to another itinerary.'})
        if itinerary and request and not itinerary.can_edit(request.user):
            raise serializers.ValidationError({'itinerary': 'You cannot manage the budget of this itinerary.'})
        return attrs


class BudgetSummarySerializer(BaseModelSerializer):
    """Compact budget used when nesting inside an itinerary."""
    total_spent = serializers.SerializerMethodField()
    remaining_balance = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = ('id', 'total_budget', 'currency', 'total_spent', 'remaining_balance')

    def _spent(self, obj):
        # Both fields need the same total; compute it once per budget.
        cache = self.__dict__.setdefault('_spent_cache', {})
        if obj.pk not in cache:
            cache[obj.pk] = obj.total_spent()
        return cache[obj.pk]

    def get_total_spent(self, obj) -> Decimal:
        return self._spent(obj)

    def get_remaining_balance(self, obj) -> Decimal:
        return obj.total_budget - self._spent(obj)
