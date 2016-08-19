from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Warning, register

from . import mapmanager


@register()
def has_map_data_check(app_configs, **kwargs):
    if not settings.MAP_DIRS:
        return [Warning(
            'There are no map data directories configured.',
            hint='Add mapdirs=/path/to/directory to your c3nav.cfg.',
            id='mapdata.W001',
        )]
    return []


class MapdataConfig(AppConfig):
    name = 'c3nav.mapdata'
    verbose_name = 'map data manager'

    def ready(self):
        for map_dir in settings.MAP_DIRS:
            mapmanager.add_map_dir(map_dir)
