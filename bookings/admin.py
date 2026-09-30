from django.contrib import admin

from .models import Accommodation, Activity, Booking


@admin.register(Accommodation)
class AccommodationAdmin(admin.ModelAdmin):
    list_display = ('name', 'destination', 'accommodation_type', 'price_per_night')
    list_filter = ('accommodation_type',)
    search_fields = ('name',)


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('title', 'destination', 'price', 'duration_hours')
    search_fields = ('title',)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'itinerary', 'booking_type', 'status', 'total_price', 'booking_date')
    list_filter = ('status', 'booking_type')
