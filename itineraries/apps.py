from django.apps import AppConfig


class ItinerariesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'itineraries'

    def ready(self):
        from travel_api.uploads import register_file_cleanup

        from .models import TripDocument
        register_file_cleanup(TripDocument, 'file')
