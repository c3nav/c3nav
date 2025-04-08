import json
import logging
import re
import typing
from itertools import chain

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.functional import cached_property, lazy
from django.utils.text import format_lazy
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from shapely import validation
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.geometry.multipoint import MultiPoint

from c3nav.mapdata.utils.geometry import WrappedGeometry, clean_geometry
from c3nav.mapdata.utils.json import format_geojson

logger = logging.getLogger('c3nav')

if "en-UW" in settings.SELECTED_LANGUAGES:
    from uwuipy import Uwuipy
    uwu = Uwuipy(
        stutter_chance=0,
        face_chance=0,
        action_chance=0,
        exclamation_chance=0,
        nsfw_actions=False,
        power=4,
    )
    uwu_more = Uwuipy(
        stutter_chance=0,
        action_chance=0,
        exclamation_chance=0,
        power=4,
    )
    uwu_most = Uwuipy(
        stutter_chance=0,
        action_chance=0.05,
        face_chance=0.1,
        nsfw_actions=False,
        power=4,
    )


def validate_geometry(geometry: BaseGeometry):
    if not isinstance(geometry, BaseGeometry):
        raise ValidationError('GeometryField expected a Shapely BaseGeometry child-class.')

    if not geometry.is_valid:
        raise ValidationError('Invalid geometry: %s' % validation.explain_validity(geometry))


shapely_logger = logging.getLogger('shapely.geos')


class GeometryField(models.JSONField):
    # todo: could this use django-pydantic-field? should it?
    default_validators = [validate_geometry]

    def __init__(self, geomtype=None, default=None, null=False, blank=False, help_text=None):
        if geomtype == 'polyline':
            geomtype = 'linestring'
        if geomtype not in (None, 'polygon', 'multipolygon', 'linestring', 'multipoint', 'point'):
            raise ValueError('GeometryField.geomtype has to be '
                             'None, "polygon", "multipolygon", "linestring", "multipoint" or "point"')
        self.geomtype = geomtype
        super().__init__(default=default, null=null, blank=blank, help_text=help_text)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.geomtype is not None:
            kwargs['geomtype'] = self.geomtype
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        if value is None or value == '' or value == "null":
            return None
        return WrappedGeometry(super().from_db_value(value, expression, connection))

    def to_python(self, value):
        if value is None or value == '':
            return None
        if isinstance(value, str):
            # todo: would be nice to not need this oh god
            value = json.loads(value)
        try:
            geometry = shape(value)
        except Exception:
            raise ValidationError(_('Invalid GeoJSON.'))
        self._validate_geomtype(geometry)
        try:
            geometry = clean_geometry(geometry)
        except Exception:
            raise ValidationError(_('Could not clean geometry.'))
        self._validate_geomtype(geometry)
        return geometry

    def validate(self, value, model_instance):
        super().validate(mapping(value), model_instance)

    @cached_property
    def classes(self):
        return {
            'polygon': (Polygon, ),
            'multipolygon': (Polygon, MultiPolygon),
            'linestring': (LineString, ),
            'multipoint': (MultiPoint, ),
            'point': (Point, )
        }.get(self.geomtype, None)

    def _validate_geomtype(self, value, exception: typing.Type[Exception] = ValidationError):
        if self.classes is not None and not isinstance(value, self.classes):
            # if you get this error with wrappedgeometry, looked into wrapped_geom
            raise TypeError('Expected %s instance, got %s, %s instead.' % (
                ' or '.join(c.__name__ for c in self.classes),
                repr(value), value.wrapped_geom
            ))

    def get_final_value(self, value, as_json=False):
        json_value = format_geojson(mapping(value))
        if value.is_empty:
            return json_value
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

        return format_geojson(mapping(value), rounded=False) if as_json else value

    def get_prep_value(self, value):
        if value is None or value == '':
            return None
        self._validate_geomtype(value, exception=TypeError)
        if value.is_empty:
            raise Exception('Cannot save empty geometry.')
        return self.get_final_value(value, as_json=True)

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return json.dumps(self.get_prep_value(value))


class JSONField(models.TextField):
    # todo: get rid of this
    # Deprecated
    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return json.loads(value)

    def to_python(self, value):
        if isinstance(value, str):
            return json.loads(value)
        return value

    def get_prep_value(self, value):
        return json.dumps(value, cls=DjangoJSONEncoder)

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return self.get_prep_value(value)


special_pattern = r'(%%|%(\([^)]*\))?[^a-z]*[a-z]|<[^>]*>|\{[^}]*\})'


def get_i18n_value(i18n_dict, *, fallback_language, fallback_any, fallback_value):
    lang = get_language()
    if i18n_dict:
        if lang in i18n_dict:
            return i18n_dict[lang]
        if lang == "en-uw" and "en" in i18n_dict:
            owiginal = i18n_dict["en"]
            stripped_owiginal = re.sub(special_pattern, '{}', owiginal)
            specials = [item[0] for item in re.findall(special_pattern, owiginal)]
            num_wowds = len(stripped_owiginal.split("(")[0].split())
            if num_wowds >= 8:
                twanslated = uwu_most.uwuify(stripped_owiginal)
            elif num_wowds >= 3:
                twanslated = uwu_more.uwuify(stripped_owiginal)
            else:
                twanslated = uwu.uwuify(stripped_owiginal)
            twanslated = twanslated.replace('***', '*').replace(r'\<', '<').replace(r'\>', '>')
            if specials:
                twanslated = ''.join(chain(*zip(twanslated.split('{}'), specials + [""])))
            return twanslated
        if fallback_language in i18n_dict:
            return i18n_dict[fallback_language]
        if fallback_any:
            return next(iter(i18n_dict.values()))
    return None if fallback_value is None else str(fallback_value)


lazy_get_i18n_value = lazy(get_i18n_value, str)


class I18nDescriptor:
    def __init__(self, field):
        self.field = field

    def __get__(self, instance, cls=None):
        if instance is None:
            return self

        fallback_value = self.field.fallback_value
        if fallback_value is not None:
            fallback_value = format_lazy(fallback_value, model=instance._meta.verbose_name, pk=instance.pk)
        return lazy_get_i18n_value(getattr(instance, self.field.attname),
                                   fallback_language=self.field.fallback_language,
                                   fallback_any=self.field.fallback_any,
                                   fallback_value=fallback_value)

    def __set__(self, instance, value):
        # this is only implemented to make sure loaddata works
        if not isinstance(value, dict):
            raise AttributeError('can\'t set attribute')
        setattr(instance, self.field.attname, value)


class I18nField(models.JSONField):
    def __init__(self, verbose_name=None, plural_name=None, max_length=None, default=None,
                 fallback_language=settings.LANGUAGE_CODE, fallback_any=False, fallback_value=None, **kwargs):
        self.i18n_max_length = max_length
        self.plural_name = plural_name
        self.fallback_language = fallback_language
        self.fallback_any = fallback_any
        self.fallback_value = fallback_value
        kwargs.pop('null', None)
        super().__init__(verbose_name=verbose_name, default=(dict(default) if default else dict), null=False, **kwargs)

    def get_default(self):
        if callable(self.default):
            return self.default()
        return self.default.copy()

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.default == {} or self.default == dict:
            kwargs.pop('default')
        if self.plural_name is not None:
            kwargs['plural_name'] = self.plural_name
        if self.i18n_max_length is not None:
            kwargs['max_length'] = self.i18n_max_length
        if self.fallback_language != settings.LANGUAGE_CODE:
            kwargs['fallback_language'] = self.fallback_language
        if self.fallback_any:
            kwargs['fallback_any'] = self.fallback_any
        if self.fallback_value is not None:
            kwargs['fallback_value'] = self.fallback_value
        return name, path, args, kwargs

    def contribute_to_class(self, cls, name, *args, **kwargs):
        super().contribute_to_class(cls, name, *args, **kwargs)
        setattr(cls, self.name, I18nDescriptor(self))

    def get_attname(self):
        return self.name+'_i18n' if self.plural_name is None else self.plural_name
