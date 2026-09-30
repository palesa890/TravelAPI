from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from budgets.models import Budget, Expense
from itineraries.models import Collaboration

pytestmark = pytest.mark.django_db

LIST = reverse('budget-list')


def detail(pk):
    return reverse('budget-detail', kwargs={'pk': pk})


def expenses_url(budget):
    return reverse('budgets:budget-expenses', kwargs={'budget_id': budget.id})


def expense_url(expense):
    return reverse('budgets:expense-detail', kwargs={'budget_id': expense.budget_id, 'pk': expense.id})


@pytest.fixture
def budget(itinerary):
    return Budget.objects.create(itinerary=itinerary, total_budget=Decimal('1000.00'))


@pytest.fixture
def expense(budget):
    return Expense.objects.create(budget=budget, title='Dinner', amount=Decimal('60.00'), category='FOOD')


class TestBudgetViewSet:
    def test_create_uppercases_currency(self, authenticated_client, itinerary):
        response = authenticated_client.post(LIST, {'itinerary': itinerary.id, 'total_budget': 500, 'currency': 'eur'})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['currency'] == 'EUR'

    @pytest.mark.parametrize('payload', [
        {'total_budget': -1},
        {'total_budget': 10, 'currency': 'US1'},
    ])
    def test_create_validation(self, authenticated_client, itinerary, payload):
        response = authenticated_client.post(LIST, {'itinerary': itinerary.id, **payload})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_one_budget_per_itinerary(self, authenticated_client, budget, itinerary):
        response = authenticated_client.post(LIST, {'itinerary': itinerary.id, 'total_budget': 5})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_budget_someone_elses_trip(self, other_client, itinerary, add_collaborator, other_user):
        payload = {'itinerary': itinerary.id, 'total_budget': 5}
        assert other_client.post(LIST, payload).status_code == status.HTTP_400_BAD_REQUEST
        add_collaborator(itinerary, other_user, Collaboration.Role.VIEWER)
        assert other_client.post(LIST, payload).status_code == status.HTTP_400_BAD_REQUEST

    def test_only_owner_can_delete(
            self, client_for, make_user, budget, itinerary, add_collaborator, authenticated_client):
        editor = make_user('editor')
        add_collaborator(itinerary, editor, Collaboration.Role.EDITOR)
        assert client_for(editor).get(detail(budget.id)).status_code == status.HTTP_200_OK
        assert client_for(editor).delete(detail(budget.id)).status_code == status.HTTP_403_FORBIDDEN
        assert authenticated_client.delete(detail(budget.id)).status_code == status.HTTP_204_NO_CONTENT

    def test_list_filters(self, authenticated_client, budget, other_client):
        assert authenticated_client.get(f'{LIST}?currency=USD&search=bali').data['count'] == 1
        assert authenticated_client.get(f'{LIST}?currency=EUR').data['count'] == 0
        assert other_client.get(LIST).data['count'] == 0


class TestExpenses:
    def test_add_expense(self, authenticated_client, budget):
        response = authenticated_client.post(expenses_url(budget), {'title': 'Museum', 'amount': '15.00',
                                                                    'category': 'ACTIVITIES'})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['budget'] == budget.id

    def test_stranger_gets_404(self, other_client, budget):
        assert other_client.get(expenses_url(budget)).status_code == status.HTTP_404_NOT_FOUND


class TestAnalytics:
    def test_empty(self, authenticated_client):
        data = authenticated_client.get(reverse('analytics-list')).data
        assert data['total_trips'] == 0 and data['average_trip_length_days'] == 0


class TestModels:
    def test_methods(self, budget, expense):
        assert str(budget) == 'Budget for Bali Trip'
        assert str(expense) == 'Dinner - 60.00'
        assert budget.remaining() == Decimal('940.00')
        assert not budget.is_over_budget()
        assert budget.spending_by_category() == {'FOOD': Decimal('60.00')}
