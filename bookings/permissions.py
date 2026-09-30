# bookings/permissions.py
from rest_framework import permissions


class IsBookingOwner(permissions.BasePermission):
    """
    Custom permission to only allow owners of a booking to view or edit it.
    """
    message = 'You can only manage your own bookings.'

    def has_object_permission(self, request, view, obj):
        return obj.user_id == request.user.id
