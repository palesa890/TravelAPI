from django.contrib import admin

from .models import Budget, Expense


class ExpenseInline(admin.TabularInline):
    model = Expense
    extra = 0


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('itinerary', 'total_budget', 'currency')
    inlines = [ExpenseInline]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'budget', 'category', 'amount', 'date')
    list_filter = ('category',)
