import json

from django.core.exceptions import ValidationError
from django.db import models
from shapely import validation
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from c3nav.mapdata.utils import clean_geometry, format_geojson


def validate_geometry(geometry):
    if not isinstance(geometry, BaseGeometry):
        raise ValidationError('GeometryField expexted a Shapely BaseGeometry child-class.')

    if not geometry.is_valid:
        raise ValidationError('Invalid geometry: %s' % validation.explain_validity(geometry))


class GeometryField(models.TextField):
    default_validators = [validate_geometry]

    def from_db_value(self, value, expression, connection, context):
        if value is None:
            return value
        return shape(json.loads(value))

    def to_python(self, value):
        return clean_geometry(shape(json.loads(value)))

    def get_prep_value(self, value):
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
