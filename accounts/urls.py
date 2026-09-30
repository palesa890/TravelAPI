from django.urls import path
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView, TokenVerifyView

from .views import (
    ChangePasswordView,
    LoginView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ProfileView,
    PublicProfileView,
    RegisterView,
)

app_name = 'accounts'

urlpatterns = [
    # Registration & JWT
    path('register/', RegisterView.as_view(), name='auth-register'),
    path('login/', LoginView.as_view(), name='token-obtain-pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token-verify'),
    path('logout/', TokenBlacklistView.as_view(), name='logout'),

    # Profile
    path('me/', ProfileView.as_view(), name='auth-profile'),
    path('users/<str:username>/', PublicProfileView.as_view(), name='public-profile'),

    # Passwords
    path('password/change/', ChangePasswordView.as_view(), name='password-change'),
    path('password/reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password/reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
]
