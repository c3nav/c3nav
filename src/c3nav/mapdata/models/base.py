from collections import OrderedDict

from django.db import models
from django.db.models.base import ModelBase
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language

from c3nav.mapdata.lastupdate import set_last_mapdata_update

MAPITEM_TYPES = OrderedDict()


class MapItemMeta(ModelBase):
    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        if not cls._meta.abstract and name != 'Source':
            MAPITEM_TYPES[name.lower()] = cls
        return cls


class MapItem(models.Model, metaclass=MapItemMeta):
    name = models.SlugField(_('Name'), unique=True, max_length=50)

    EditorForm = None

    @property
    def title(self):
        if not hasattr(self, 'titles'):
            return self.name
        lang = get_language()
        if lang in self.titles:
            return self.titles[lang]
        return next(iter(self.titles.values())) if self.titles else self.name

    def save(self, *args, **kwargs):
        with set_last_mapdata_update():
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with set_last_mapdata_update():
            super().delete(*args, **kwargs)

    class Meta:
        abstract = True
