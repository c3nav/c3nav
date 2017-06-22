from django.apps import AppConfig
from django.core.exceptions import FieldDoesNotExist
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.utils.models import get_submodels


class MapdataConfig(AppConfig):
    name = 'c3nav.mapdata'

    def ready(self):
        from c3nav.mapdata.models.geometry.base import GeometryMixin, GEOMETRY_MODELS
        for cls in get_submodels(GeometryMixin):
            GEOMETRY_MODELS[cls.__name__] = cls
            try:
                cls._meta.get_field('geometry')
            except FieldDoesNotExist:
                raise TypeError(_('Model %s has GeometryMixin as base class but has no geometry field.') % cls)

        from c3nav.mapdata.models.locations import Location, LOCATION_MODELS
        LOCATION_MODELS.extend(get_submodels(Location))

        from c3nav.mapdata.models.geometry.level import LevelGeometryMixin, LEVEL_MODELS
        LEVEL_MODELS.extend(get_submodels(LevelGeometryMixin))

        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin, SPACE_MODELS
        SPACE_MODELS.extend(get_submodels(SpaceGeometryMixin))
