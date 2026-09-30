from rest_framework import permissions


class IsAccountOwner(permissions.BasePermission):
    message = 'You can only access your own account.'

    def has_object_permission(self, request, view, obj):
        return obj == request.user
