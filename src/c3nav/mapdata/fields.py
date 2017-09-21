import json
import typing

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely import validation
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

from c3nav.mapdata.utils.geometry import clean_geometry
from c3nav.mapdata.utils.json import format_geojson

validate_bssid_lines = RegexValidator(regex=r'^([0-9a-f]{2}(:[0-9a-f]{2}){5}(\r?\n[0-9a-f]{2}(:[0-9a-f]{2}){5})*)?$',
                                      message=_('please enter a newline seperated lowercase list of BSSIDs'))


def validate_geometry(geometry: BaseGeometry):
    if not isinstance(geometry, BaseGeometry):
        raise ValidationError('GeometryField expected a Shapely BaseGeometry child-class.')

    if not geometry.is_valid:
        raise ValidationError('Invalid geometry: %s' % validation.explain_validity(geometry))


class GeometryField(models.TextField):
    default_validators = [validate_geometry]

    def __init__(self, geomtype=None, default=None):
        if geomtype == 'polyline':
            geomtype = 'linestring'
        if geomtype not in (None, 'polygon', 'multipolygon', 'linestring', 'point'):
            raise ValueError('GeometryField.geomtype has to be '
                             'None, "polygon", "multipolygon", "linestring" or "point"')
        self.geomtype = geomtype
        super().__init__(default=default)

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
        except:
            raise ValidationError(_('Invalid GeoJSON.'))
        self._validate_geomtype(geometry)
        try:
            geometry = clean_geometry(geometry)
        except:
            raise ValidationError(_('Could not clean geometry.'))
        self._validate_geomtype(geometry)
        return geometry

    def _validate_geomtype(self, value, exception: typing.Type[Exception]=ValidationError):
        if self.geomtype == 'polygon' and not isinstance(value, Polygon):
            raise exception('Expected Polygon instance, got %s instead.' % repr(value))
        if self.geomtype == 'multipolygon' and not isinstance(value, (Polygon, MultiPolygon)):
            raise exception('Expected Polygon or MultiPolygon instance, got %s instead.' % repr(value))
        elif self.geomtype == 'linestring' and not isinstance(value, LineString):
            raise exception('Expected LineString instance, got %s instead.' % repr(value))
        elif self.geomtype == 'point' and not isinstance(value, Point):
            raise exception('Expected Point instance, got %s instead.' % repr(value))

    def get_prep_value(self, value):
        if value is None:
            return None
        self._validate_geomtype(value, exception=TypeError)
        json_value = format_geojson(mapping(value))
        rounded_value = shape(json_value)
        if not rounded_value.is_valid:
            json_value = format_geojson(mapping(rounded_value.buffer(0)))
        return json.dumps(json_value)


class JSONField(models.TextField):
    def from_db_value(self, value, expression, connection, context):
        if value is None:
            return value
        return json.loads(value)

    def to_python(self, value):
        return json.loads(value)

    def get_prep_value(self, value):
        return json.dumps(value)
