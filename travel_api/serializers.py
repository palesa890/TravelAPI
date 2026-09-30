"""Shared serializer base classes used across apps."""
import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


class BaseModelSerializer(serializers.ModelSerializer):
    """
    Base ModelSerializer for the project.

    - Forces id / created_at / updated_at to be read-only.
    - Runs the model's clean() during validation, so model-level business rules
      are enforced for API writes too.
    """
    ALWAYS_READ_ONLY = ('id', 'created_at', 'updated_at')

    def get_extra_kwargs(self):
        extra_kwargs = super().get_extra_kwargs()
        for field_name in self.ALWAYS_READ_ONLY:
            kwargs = extra_kwargs.get(field_name, {}).copy()
            kwargs['read_only'] = True
            extra_kwargs[field_name] = kwargs
        return extra_kwargs

    def validate(self, attrs):
        attrs = super().validate(attrs)
        self.run_model_clean(attrs)
        return attrs

    def run_model_clean(self, attrs):
        model = self.Meta.model
        instance = copy.copy(self.instance) if self.instance is not None else model()
        concrete = {f.name for f in model._meta.concrete_fields}
        for key, value in attrs.items():
            if key in concrete:
                setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(serializers.as_serializer_error(exc))
