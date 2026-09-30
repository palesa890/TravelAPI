"""Small helper for sending user notifications by email."""
from django.conf import settings
from django.core.mail import send_mail


def notify_user(user, subject, message):
    """Send an email to the user if they have an address. Never raises."""
    if not getattr(user, 'email', None):
        return False
    return bool(send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    ))
