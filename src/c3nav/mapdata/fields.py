import json

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely import validation
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from c3nav.mapdata.utils.geometry import clean_geometry
from c3nav.mapdata.utils.json import format_geojson

validate_bssid_lines = RegexValidator(regex=r'^([0-9a-f]{2}(:[0-9a-f]{2}){5}(\n[0-9a-f]{2}(:[0-9a-f]{2}){5})*)?$',
                                      message=_('please enter a newline seperated lowercase list of BSSIDs'))


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
