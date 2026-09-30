from django.contrib import admin

from .models import Collaboration, DailyPlan, Itinerary


class DailyPlanInline(admin.TabularInline):
    model = DailyPlan
    extra = 0


class CollaborationInline(admin.TabularInline):
    model = Collaboration
    fk_name = 'itinerary'
    extra = 0


@admin.register(Itinerary)
class ItineraryAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'destination', 'start_date', 'end_date', 'status')
    list_filter = ('status',)
    search_fields = ('title', 'destination__name', 'owner__username')
    inlines = [DailyPlanInline, CollaborationInline]


@admin.register(Collaboration)
class CollaborationAdmin(admin.ModelAdmin):
    list_display = ('itinerary', 'user', 'role', 'created_at')
    list_filter = ('role',)
