import json

from django.db import models
from shapely.geometry import mapping, shape

from .utils import sort_geojson


class GeometryField(models.TextField):
    def from_db_value(self, value, expression, connection, context):
        if value is None:
            return value
        return shape(json.loads(value))

    def to_python(self, value):
        return shape(json.loads(value))

    def get_prep_value(self, value):
        return json.dumps(sort_geojson(mapping(value)))


class JSONField(models.TextField):
    def from_db_value(self, value, expression, connection, context):
        if value is None:
            return value
        return json.loads(value)

    def to_python(self, value):
        return json.loads(value)

    def get_prep_value(self, value):
        return json.dumps(value)
