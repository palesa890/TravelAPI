"""
Role-based itinerary permissions.

Roles on a trip:
    OWNER  - created the trip; full control.
    EDITOR - collaborator who can edit the trip and its plans, bookings, budget.
    VIEWER - collaborator with read-only access.
"""
from rest_framework import permissions

from .models import Collaboration


def _get_itinerary(obj):
    """Accept an Itinerary or any object with an `itinerary` attribute."""
    return obj if hasattr(obj, 'owner_id') else getattr(obj, 'itinerary', None)


class IsTripOwner(permissions.BasePermission):
    """Only the trip owner may proceed."""
    message = 'Only the trip owner can perform this action.'

    def has_object_permission(self, request, view, obj):
        itinerary = _get_itinerary(obj)
        return itinerary is not None and itinerary.owner_id == request.user.id


class IsTripOwnerOrCollaborator(permissions.BasePermission):
    """
    Owner or any collaborator can read; only the owner can write.
    """
    message = 'You do not have access to this itinerary.'

    def has_object_permission(self, request, view, obj):
        itinerary = _get_itinerary(obj)
        if itinerary is None:
            return False
        if request.method in permissions.SAFE_METHODS:
            return itinerary.get_role(request.user) is not None
        return itinerary.owner_id == request.user.id


class CanEditItinerary(permissions.BasePermission):
    """
    Owner can always edit; collaborators need the EDITOR role.
    Read access is granted to anyone with a role on the trip.
    """
    message = 'You need editor access to modify this itinerary.'
    EDIT_ROLES = ('OWNER', Collaboration.Role.EDITOR)

    def has_object_permission(self, request, view, obj):
        itinerary = _get_itinerary(obj)
        if itinerary is None:
            return False
        role = itinerary.get_role(request.user)
        if request.method in permissions.SAFE_METHODS:
            return role is not None
        return role in self.EDIT_ROLES
