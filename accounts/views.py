from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from travel_api.notifications import notify_user

from .permissions import IsAccountOwner
from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PublicUserSerializer,
    UserProfileSerializer,
    UserRegisterSerializer,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """POST: Register a new user account."""
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


class LoginView(TokenObtainPairView):
    """POST: Exchange username/password for access and refresh tokens."""
    serializer_class = LoginSerializer


class ProfileView(generics.RetrieveUpdateAPIView):
    """GET / PUT / PATCH the current user's profile."""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsAccountOwner]

    def get_object(self):
        user = (
            User.objects.prefetch_related('favorite_destinations__category')
            .get(pk=self.request.user.pk)
        )
        self.check_object_permissions(self.request, user)
        return user


class PublicProfileView(generics.RetrieveAPIView):
    """GET: Public profile of any user by username."""
    queryset = User.objects.filter(is_active=True)
    serializer_class = PublicUserSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'username'


class ChangePasswordView(APIView):
    """POST: Change the current user's password (requires the old password)."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password updated successfully.'}, status=status.HTTP_200_OK)


class PasswordResetRequestView(APIView):
    """
    POST {"email": ...}: Email a reset link. Always returns 200 so the
    endpoint can't be used to discover which emails are registered.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = PasswordResetRequestSerializer

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.get_user()
        if user is not None:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
            notify_user(
                user,
                'Reset your password',
                f'Use this link to reset your password: {link}\n\n'
                f'Or send uid={uid} and token={token} to the password reset confirm endpoint.',
            )
        return Response(
            {'message': 'If an account with that email exists, a reset link has been sent.'},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """POST {"uid", "token", "new_password", "new_password2"}: Set a new password."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password has been reset.'}, status=status.HTTP_200_OK)
