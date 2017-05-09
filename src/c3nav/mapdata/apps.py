from typing import List

from django.apps import AppConfig
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.translation import ugettext_lazy as _


class MapdataConfig(AppConfig):
    name = 'c3nav.mapdata'

    def _get_submodels(self, cls: type) -> List[models.Model]:
        submodels = []
        for subcls in cls.__subclasses__():
            if issubclass(subcls, models.Model) and not subcls._meta.abstract:
                submodels.append(subcls)
            submodels.extend(self._get_submodels(subcls))
        return submodels

    def ready(self):
        from c3nav.mapdata.models.base import EditorFormMixin, EDITOR_FORM_MODELS
        for cls in self._get_submodels(EditorFormMixin):
            EDITOR_FORM_MODELS[cls.__name__] = cls

        from c3nav.mapdata.models.geometry.base import GeometryMixin, GEOMETRY_MODELS
        for cls in self._get_submodels(GeometryMixin):
            GEOMETRY_MODELS[cls.__name__] = cls
            geometry = None
            try:
                geometry = cls._meta.get_field('geometry')
            except FieldDoesNotExist:
                pass

            if geometry is None:
                raise TypeError(_('Model %s has GeometryMixin as base class but has no geometry field.') % cls)

        from c3nav.mapdata.models.geometry.section import SectionGeometryMixin, SECTION_MODELS
        for cls in self._get_submodels(SectionGeometryMixin):
            SECTION_MODELS[cls.__name__] = cls

        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin, SPACE_MODELS
        for cls in self._get_submodels(SpaceGeometryMixin):
            SPACE_MODELS[cls.__name__] = cls
