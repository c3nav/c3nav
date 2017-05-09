from django.apps import AppConfig
from django.db import models


class MapdataConfig(AppConfig):
    name = 'c3nav.mapdata'

    def _get_submodels(self, cls: type):
        submodels = []
        for subcls in cls.__subclasses__():
            if issubclass(subcls, models.Model):
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

        from c3nav.mapdata.models.geometry.section import SectionGeometryMixin, SECTION_MODELS
        for cls in self._get_submodels(SectionGeometryMixin):
            SECTION_MODELS[cls.__name__] = cls

        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin, SPACE_MODELS
        for cls in self._get_submodels(SpaceGeometryMixin):
            SPACE_MODELS[cls.__name__] = cls
