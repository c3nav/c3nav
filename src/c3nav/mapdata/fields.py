import json

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely import validation
from shapely.geometry import LineString, Point, Polygon, mapping, shape
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
        if geomtype not in (None, 'polygon', 'linestring', 'point'):
            raise ValueError('GeometryField.geomtype has to be None, "polygon", "linestring", "point"')
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
        if value is None:
            return None
        return clean_geometry(shape(json.loads(value)))

    def get_prep_value(self, value):
        if value is None:
            return None
        elif self.geomtype == 'polygon' and not isinstance(value, Polygon):
            raise TypeError('Expected Polygon instance, got %s instead.' % repr(value))
        elif self.geomtype == 'linestring' and not isinstance(value, LineString):
            raise TypeError('Expected LineString instance, got %s instead.' % repr(value))
        elif self.geomtype == 'point' and not isinstance(value, Point):
            raise TypeError('Expected Point instance, got %s instead.' % repr(value))
        return json.dumps(format_geojson(mapping(value)))


class JSONField(models.TextField):
    def from_db_value(self, value, expression, connection, context):
        if value is None:
            return value
        return json.loads(value)

    def to_python(self, value):
        return json.loads(value)

    def get_prep_value(self, value):
        return json.dumps(value)
