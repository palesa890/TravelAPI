"""
Guard the select_related / prefetch_related work: query counts must not grow with the data.
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from bookings.models import Booking
from budgets.models import Budget
from itineraries.models import Itinerary

pytestmark = pytest.mark.django_db


@pytest.fixture
def many_trips(user, destination, accommodation, activity, make_user, add_collaborator, trip_dates):
    start, end = trip_dates
    for i in range(5):
        trip = Itinerary.objects.create(title=f'Trip {i}', owner=user, destination=destination,
                                        start_date=start, end_date=end)
        trip.generate_daily_plans()
        for plan in trip.daily_plans.all():
            plan.activities.add(activity)
        Budget.objects.create(itinerary=trip, total_budget=Decimal('1000'))
        Booking.objects.create(user=user, itinerary=trip, booking_type='ACCOMMODATION',
                               accommodation=accommodation, total_price=Decimal('300'))
        add_collaborator(trip, make_user(f'friend{i}'))
    return Itinerary.objects.filter(owner=user)


def test_itinerary_list_query_count_is_constant(authenticated_client, many_trips, django_assert_max_num_queries):
    with django_assert_max_num_queries(4):
        response = authenticated_client.get(reverse('itinerary-list'))
    assert response.data['count'] == 5
    assert response.data['results'][0]['total_activities'] == 1


def test_itinerary_detail_uses_prefetches(authenticated_client, many_trips, django_assert_max_num_queries):
    trip = many_trips.first()
    with django_assert_max_num_queries(7):
        response = authenticated_client.get(reverse('itinerary-detail', kwargs={'pk': trip.id}))
    assert response.data['booking_count'] == 1
    assert response.data['total_booking_cost'] == Decimal('300.00')
    assert len(response.data['daily_plans']) == 6


def test_budget_status_uses_f_expressions(authenticated_client, many_trips, user, accommodation):
    over = many_trips.first()
    Booking.objects.create(user=user, itinerary=over, booking_type='ACCOMMODATION',
                           accommodation=accommodation, total_price=Decimal('900'))
    url = reverse('itinerary-budget-status')
    everything = authenticated_client.get(url).data['results']
    assert len(everything) == 5
    assert everything[0]['budget_variance'] == '-200.00'
    assert [t['id'] for t in authenticated_client.get(f'{url}?over_budget=true').data['results']] == [over.id]
    assert len(authenticated_client.get(f'{url}?at_risk=true').data['results']) == 1
