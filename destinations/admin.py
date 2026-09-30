from django.contrib import admin

from .models import Category, Destination, SearchPreference


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'country', 'category', 'climate', 'average_cost_per_day')
    list_filter = ('climate', 'category', 'country')
    search_fields = ('name', 'city', 'country')


@admin.register(SearchPreference)
class SearchPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'scope', 'name', 'query', 'created_at')
    list_filter = ('scope',)
