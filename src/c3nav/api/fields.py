from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from shapely.geometry import mapping, shape


class GeometryField(serializers.DictField):
    """
    shapely geometry objects serialized using GeoJSON
    """
    default_error_messages = {
        'invalid': _('Invalid GeoJSON.')
    }

    def to_representation(self, obj):
        geojson = mapping(obj)
        return super().to_representation(geojson)

    def to_internal_value(self, data):
        geojson = super().to_internal_value(data)
        try:
            return shape(geojson)
        except:
            raise ValidationError(_('Invalid GeoJSON.'))
