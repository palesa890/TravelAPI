from typing import Optional

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from destinations.serializers import DestinationListSerializer

User = get_user_model()


class UserSummarySerializer(serializers.ModelSerializer):
    """Compact user representation used when nesting users in other responses."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'full_name')
        read_only_fields = fields

    def get_full_name(self, obj) -> str:
        return obj.get_full_name() or obj.username


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    password2 = serializers.CharField(
        write_only=True, required=False, style={'input_type': 'password'},
        help_text='Optional password confirmation.',
    )

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'password', 'password2', 'first_name', 'last_name',
            'bio', 'home_country', 'travel_style', 'travel_preferences',
        )
        read_only_fields = ('id',)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('A user with that username already exists.')
        return value

    def validate_email(self, value):
        if value and User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with that email already exists.')
        return value.lower()

    def validate(self, attrs):
        password2 = attrs.pop('password2', None)
        if password2 is not None and password2 != attrs['password']:
            raise serializers.ValidationError({'password2': 'Passwords do not match.'})
        candidate = User(username=attrs.get('username'), email=attrs.get('email', ''))
        validate_password(attrs['password'], user=candidate)
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
    favorite_destinations = DestinationListSerializer(many=True, read_only=True)
    trip_count = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'bio', 'profile_picture',
            'date_of_birth', 'age', 'home_country', 'travel_style', 'travel_preferences',
            'favorite_destinations', 'trip_count', 'date_joined', 'updated_at',
        )
        read_only_fields = ('id', 'username', 'email', 'date_joined', 'updated_at')

    def get_trip_count(self, obj) -> int:
        return obj.owned_itineraries.count()

    def get_age(self, obj) -> Optional[int]:
        return obj.age

    def validate_travel_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Travel preferences must be a JSON object.')
        return value

    def update(self, instance, validated_data):
        # Merge preferences instead of replacing the whole object.
        preferences = validated_data.pop('travel_preferences', None)
        if preferences is not None:
            instance.travel_preferences = {**(instance.travel_preferences or {}), **preferences}
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.full_clean(exclude=['password'])
        instance.save()
        return instance


class PublicUserSerializer(serializers.ModelSerializer):
    """What other users can see about someone."""
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'bio', 'home_country', 'travel_style', 'review_count', 'date_joined')
        read_only_fields = fields

    def get_review_count(self, obj) -> int:
        return obj.reviews.count()


class LoginSerializer(TokenObtainPairSerializer):
    """Returns the JWT pair plus basic user info."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSummarySerializer(self.user).data
        return data


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    new_password2 = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate_old_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({'new_password2': 'Passwords do not match.'})
        if attrs['new_password'] == attrs['old_password']:
            raise serializers.ValidationError({'new_password': 'New password must differ from the current one.'})
        validate_password(attrs['new_password'], user=self.context['request'].user)
        return attrs

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def get_user(self):
        return User.objects.filter(email__iexact=self.validated_data['email'], is_active=True).first()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    new_password2 = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(attrs['uid'])))
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            raise serializers.ValidationError({'uid': 'Invalid reset link.'})
        if not default_token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError({'token': 'Reset link is invalid or has expired.'})
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({'new_password2': 'Passwords do not match.'})
        validate_password(attrs['new_password'], user=user)
        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user
