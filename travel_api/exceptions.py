"""
Project-wide exception handling so every error response has the same shape:

    {
        "error": {
            "status_code": 400,
            "message": "Validation failed.",
            "details": {...}
        }
    }
"""
import logging

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The request conflicts with existing data.'
    default_code = 'conflict'


def custom_exception_handler(exc, context):
    # Translate model-level errors into DRF exceptions so they return 4xx, not 500.
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(as_serializer_error(exc))
    elif isinstance(exc, IntegrityError):
        exc = Conflict()

    response = exception_handler(exc, context)
    if response is None:
        # Unexpected error. In DEBUG let Django show its debug page; otherwise log it
        # and return the same JSON shape as every other error, without internals.
        if settings.DEBUG:
            return None
        view = context.get('view')
        logger.exception('Unhandled error in %s', view.__class__.__name__ if view else 'unknown view')
        return Response(
            {'error': {'status_code': 500, 'message': 'An unexpected error occurred.', 'details': {}}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    details = response.data
    if isinstance(details, dict) and set(details.keys()) == {'detail'}:
        message = str(details['detail'])
    elif isinstance(exc, ValidationError):
        message = 'Validation failed.'
    else:
        message = str(getattr(exc, 'detail', 'An error occurred.'))

    response.data = {
        'error': {
            'status_code': response.status_code,
            'message': message,
            'details': details,
        }
    }
    return response
