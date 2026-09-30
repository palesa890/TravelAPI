from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'travel_style', 'is_staff')
    list_filter = UserAdmin.list_filter + ('travel_style',)
    fieldsets = UserAdmin.fieldsets + (
        ('Travel profile', {
            'fields': ('bio', 'profile_picture', 'date_of_birth', 'home_country',
                       'travel_style', 'travel_preferences', 'favorite_destinations'),
        }),
    )
    filter_horizontal = UserAdmin.filter_horizontal + ('favorite_destinations',)
