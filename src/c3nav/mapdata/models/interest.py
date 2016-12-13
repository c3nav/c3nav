from collections import OrderedDict

from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import JSONField
from c3nav.mapdata.models.base import MapItem
from c3nav.mapdata.models.geometry import GeometryMapItemWithLevel


# noinspection PyUnresolvedReferences
class MapItemOfInterestMixin:
    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['titles'] = OrderedDict(sorted(self.titles.items()))
        return result

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'titles' not in data:
            raise ValueError('missing titles.')
        titles = data['titles']
        if not isinstance(titles, dict):
            raise ValueError('Invalid titles format.')
        if any(not isinstance(lang, str) for lang in titles.keys()):
            raise ValueError('titles: All languages have to be strings.')
        if any(not isinstance(title, str) for title in titles.values()):
            raise ValueError('titles: All titles have to be strings.')
        if any(not title for title in titles.values()):
            raise ValueError('titles: Titles must not be empty strings.')
        kwargs['titles'] = titles
        return kwargs

    def tofile(self):
        result = super().tofile()
        result['titles'] = OrderedDict(sorted(self.titles.items()))
        return result


class GroupOfInterest(MapItem, MapItemOfInterestMixin):
    titles = JSONField()

    class Meta:
        verbose_name = _('Group of Interest')
        verbose_name_plural = _('Groups of Interest')
        default_related_name = 'groupsofinterest'


class AreaOfInterest(GeometryMapItemWithLevel, MapItemOfInterestMixin):
    titles = JSONField()
    groups = models.ManyToManyField(GroupOfInterest, verbose_name=_('Groups of Interest'), blank=True)

    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Area of Interest')
        verbose_name_plural = _('Areas of Interest')
        default_related_name = 'areasofinterest'

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        groups = data.get('groups', [])
        if not isinstance(groups, list):
            raise TypeError('groups has to be a list')
        kwargs['groups'] = groups

        return kwargs

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['groups'] = tuple(self.groups.all().order_by('name').values_list('name', flat=True))
        return result

    def tofile(self):
        result = super().tofile()
        result['groups'] = sorted(self.groups.all().order_by('name').values_list('name', flat=True))
        result.move_to_end('geometry')
        return result

    def __str__(self):
        return self.title
