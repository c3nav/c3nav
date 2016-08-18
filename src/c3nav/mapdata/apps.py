from django.apps import AppConfig


class MapdataConfig(AppConfig):
    name = 'c3nav.mapdata'
    verbose_name = 'map data manager'

    def ready(self):
        pass
