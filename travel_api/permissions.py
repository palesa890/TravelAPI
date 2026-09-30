from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """Anyone can read; only staff users can write."""
    message = 'Only administrators can modify this resource.'

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


class IsUploaderOrAdmin(permissions.BasePermission):
    """The user who uploaded a file (obj.uploaded_by) or a staff member."""
    message = 'Only the uploader or an administrator can remove this file.'

    def has_object_permission(self, request, view, obj):
        return request.user.is_staff or obj.uploaded_by_id == request.user.id
