from django.apps import AppConfig


class MapdataConfig(AppConfig):
    name = 'c3nav.mapdata'

    def ready(self):
        from c3nav.mapdata.utils.cache.changes import register_signals
        register_signals()
        import c3nav.mapdata.metrics  # noqa
        import c3nav.mapdata.updatejobs  # noqa
