# budgets/urls.py  (mounted at /api/v1/budgets/)
from django.urls import path

from .views import ExpenseDetailView, budget_expenses

app_name = 'budgets'

urlpatterns = [
    path('<int:budget_id>/expenses/', budget_expenses, name='budget-expenses'),
    path('<int:budget_id>/expenses/<int:pk>/', ExpenseDetailView.as_view(), name='expense-detail'),
]
