"""
Select the settings module from the DJANGO_ENV environment variable
(development | production | test). Defaults to development.
"""
from decouple import config

DJANGO_ENV = config('DJANGO_ENV', default='development')

if DJANGO_ENV == 'production':
    from .production import *  # noqa: F401,F403
elif DJANGO_ENV == 'test':
    from .test import *  # noqa: F401,F403
else:
    from .development import *  # noqa: F401,F403
