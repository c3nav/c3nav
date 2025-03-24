from django.apps import AppConfig


class RoutingConfig(AppConfig):
    name = 'c3nav.routing'

    def ready(self):
        import c3nav.routing.updatejobs  # noqa
