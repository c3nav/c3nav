from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.fields import GeometryField, I18nField
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
from c3nav.mapdata.utils.geometry import smart_mapping


class GraphNode(SpaceGeometryMixin, models.Model):
    """
    A graph node
    """
    geometry = GeometryField('point')

    class Meta:
        verbose_name = _('Graph Node')
        verbose_name_plural = _('Graph Nodes')
        default_related_name = 'graphnodes'

    def get_geojson_properties(self, *args, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        return result

    @property
    def coords(self):
        return smart_mapping(self.geometry)['coordinates']


class WayType(models.Model):
    """
    A special way type
    """
    title = I18nField(_('Title'), plural_name='titles', fallback_any=True)
    title_plural = I18nField(_('Title (Plural)'), plural_name='titles_plural', fallback_any=True)
    join_edges = models.BooleanField(_('join consecutive edges'), default=True)
    up_separate = models.BooleanField(_('upwards separately'), default=True)
    walk = models.BooleanField(_('walking'), default=False)
    color = models.CharField(max_length=32, verbose_name=_('edge color'))
    avoid_by_default = models.BooleanField(_('avoid by default'), default=False)
    icon_name = models.CharField(_('icon name'), max_length=32, null=True, blank=True)
    extra_seconds = models.PositiveSmallIntegerField(_('extra seconds per edge'), default=0)
    speed = models.DecimalField(_('speed (m/s)'), max_digits=3, decimal_places=1, default=1,
                                validators=[MinValueValidator(Decimal('0.1'))])
    description = I18nField(_('description (downwards or general)'), fallback_any=True)
    speed_up = models.DecimalField(_('speed upwards (m/s)'), max_digits=3, decimal_places=1, default=1,
                                   validators=[MinValueValidator(Decimal('0.1'))])
    description_up = I18nField(_('description upwards'), fallback_any=True)
    level_change_description = I18nField(_('level change description'))

    class Meta:
        verbose_name = _('Way Type')
        verbose_name_plural = _('Way Types')
        default_related_name = 'waytypes'


class GraphEdge(AccessRestrictionMixin, models.Model):
    """
    A directed edge connecting two graph nodes
    """
    from_node = models.ForeignKey(GraphNode, on_delete=models.PROTECT, related_name='edges_from_here',
                                  verbose_name=_('from node'))
    to_node = models.ForeignKey(GraphNode, on_delete=models.PROTECT, related_name='edges_to_here',
                                verbose_name=_('to node'))
    waytype = models.ForeignKey(WayType, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_('Way Type'))

    class Meta:
        verbose_name = _('Graph Edge')
        verbose_name_plural = _('Graph Edges')
        default_related_name = 'graphedges'
        unique_together = (('from_node', 'to_node'), )

    def to_geojson(self) -> dict:
        result = {
            'type': 'Feature',
            'properties': {
                'id': self.pk,
                'type': 'graphedge',
                'from_node': self.from_node_id,
                'to_node': self.to_node_id,
            },
            'geometry': {
                'type': 'LineString',
                'coordinates': (self.from_node.coords, self.to_node.coords),
            },
        }
        if self.waytype_id is not None:
            result['properties']['color'] = self.waytype.color
        return result

    def get_geojson_key(self):
        return (self.__class__.__name__.lower(), self.pk)
