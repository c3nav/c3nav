from django.apps import AppConfig


class MapdataConfig(AppConfig):
    name = 'c3nav.mapdata'

    def ready(self):
        import c3nav.mapdata.metrics  # noqa
        import c3nav.mapdata.updatejobs  # noqa
