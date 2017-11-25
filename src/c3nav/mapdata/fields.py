import json
import logging
import typing

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely import validation
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

from c3nav.mapdata.utils.geometry import clean_geometry
from c3nav.mapdata.utils.json import format_geojson

validate_bssid_lines = RegexValidator(regex=r'^([0-9a-f]{2}(:[0-9a-f]{2}){5}(\r?\n[0-9a-f]{2}(:[0-9a-f]{2}){5})*)?$',
                                      message=_('please enter a newline seperated lowercase list of BSSIDs'))

logger = logging.getLogger('c3nav')


def validate_geometry(geometry: BaseGeometry):
    if not isinstance(geometry, BaseGeometry):
        raise ValidationError('GeometryField expected a Shapely BaseGeometry child-class.')

    if not geometry.is_valid:
        raise ValidationError('Invalid geometry: %s' % validation.explain_validity(geometry))


shapely_logger = logging.getLogger('shapely.geos')


class GeometryField(models.TextField):
    default_validators = [validate_geometry]

    def __init__(self, geomtype=None, default=None, null=False):
        if geomtype == 'polyline':
            geomtype = 'linestring'
        if geomtype not in (None, 'polygon', 'multipolygon', 'linestring', 'point'):
            raise ValueError('GeometryField.geomtype has to be '
                             'None, "polygon", "multipolygon", "linestring" or "point"')
        self.geomtype = geomtype
        super().__init__(default=default, null=null)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.geomtype is not None:
            kwargs['geomtype'] = self.geomtype
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection, context):
        if value is None:
            return value
        return shape(json.loads(value))

    def to_python(self, value):
        if value is None or value == '':
            return None
        try:
            geometry = shape(json.loads(value))
        except Exception:
            raise ValidationError(_('Invalid GeoJSON.'))
        self._validate_geomtype(geometry)
        try:
            geometry = clean_geometry(geometry)
        except Exception:
            raise ValidationError(_('Could not clean geometry.'))
        self._validate_geomtype(geometry)
        return geometry

    @cached_property
    def classes(self):
        return {
            'polygon': (Polygon, ),
            'multipolygon': (Polygon, MultiPolygon),
            'linestring': (LineString, ),
            'point': (Point, )
        }[self.geomtype]

    def _validate_geomtype(self, value, exception: typing.Type[Exception]=ValidationError):
        if not isinstance(value, self.classes):
            raise exception('Expected %s instance, got %s instead.' % (' or '.join(c.__name__ for c in self.classes),
                                                                       repr(value)))

    def get_final_value(self, value, as_json=False):
        json_value = format_geojson(mapping(value))
        rounded_value = shape(json_value)

        shapely_logger.setLevel('ERROR')
        if rounded_value.is_valid:
            return json_value if as_json else rounded_value
        shapely_logger.setLevel('INFO')

        rounded_value = rounded_value.buffer(0)
        if not rounded_value.is_empty:
            value = rounded_value
        else:
            logging.debug('Fixing rounded geometry failed, saving it to the database without rounding.')

        return format_geojson(mapping(value), round=False) if as_json else value

    def get_prep_value(self, value):
        if value is None:
            return None
        self._validate_geomtype(value, exception=TypeError)
        return json.dumps(self.get_final_value(value, as_json=True))

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return self.get_prep_value(value)


class JSONField(models.TextField):
    def from_db_value(self, value, expression, connection, context):
        if value is None:
            return value
        return json.loads(value)

    def to_python(self, value):
        return json.loads(value)

    def get_prep_value(self, value):
        return json.dumps(value)

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return self.get_prep_value(value)
