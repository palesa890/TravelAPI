from rest_framework import permissions


class IsReviewAuthorOrReadOnly(permissions.BasePermission):
    """
    Anyone may read reviews; only the author may edit or delete one.
    """
    message = 'You can only modify your own reviews.'

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.user_id == request.user.id
