from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('destination', 'user', 'rating', 'created_at')
    list_filter = ('rating',)
    search_fields = ('destination__name', 'user__username', 'comment')
