from django.apps import AppConfig


class MapdataConfig(AppConfig):
    name = 'c3nav.mapdata'

    def ready(self):
        from c3nav.mapdata.render.cache import register_signals
        register_signals()
