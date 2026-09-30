from django.apps import AppConfig


class DestinationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'destinations'

    def ready(self):
        from travel_api.uploads import register_file_cleanup

        from .models import Destination, DestinationPhoto
        register_file_cleanup(Destination, 'cover_image')
        register_file_cleanup(DestinationPhoto, 'image')
