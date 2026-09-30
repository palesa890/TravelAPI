from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        from travel_api.uploads import register_file_cleanup

        from .models import User
        register_file_cleanup(User, 'profile_picture')
