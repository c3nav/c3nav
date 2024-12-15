from collections import OrderedDict

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.models import MapUpdate, WayType

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


class RouteOptions(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True)
    data = models.JSONField(default=dict)

    class Meta:
        verbose_name = _('Route options')
        verbose_name_plural = _('Route options')
        default_related_name = 'routeoptions'

    fields_cached = LocalContext()

    @classmethod
    def build_fields(cls):
        fields = OrderedDict()
        fields['mode'] = forms.ChoiceField(
            label=_('Routing mode'),
            choices=(('fastest', _('fastest')), ('shortest', _('shortest'))),
            initial='fastest'
        )
        fields['walk_speed'] = forms.ChoiceField(
            label=_('Walk speed'),
            choices=(('slow', _('slow')), ('default', _('default')), ('fast', _('fast'))),
            initial='default'
        )

        for waytype in WayType.objects.all():
            choices = []
            choices.append(('allow', _('allow')))
            if waytype.up_separate:
                choices.append(('avoid_up', _('avoid upwards')))
                choices.append(('avoid_down', _('avoid downwards')))
                choices.append(('avoid', _('avoid completely')))
            else:
                choices.append(('avoid', _('avoid')))
            fields['waytype_%d' % waytype.pk] = forms.ChoiceField(
                label=waytype.title_plural,
                choices=tuple(choices),
                initial='avoid' if waytype.avoid_by_default else 'allow',
            )

        fields['restrictions'] = forms.ChoiceField(
            label=_('Access restrictions'),
            choices=(('avoid', _('avoid')), ('normal', _('use normally')), ('prefer', _('prefer'))),
            initial='normal'
        )

        return fields

    @classmethod
    def get_fields(cls):
        cache_key = MapUpdate.current_cache_key()
        if getattr(cls.fields_cached, 'key', None) != cache_key:
            cls.fields_cached.key = cache_key
            cls.fields_cached.data = cls.build_fields()
        return cls.fields_cached.data

    @staticmethod
    def get_cache_key(pk):
        return 'routing:options:user:%d' % pk

    @classmethod
    def get_for_user(cls, user):
        cache_key = cls.get_cache_key(user.pk)
        result = cache.get(cache_key, None)
        if result:
            return result

        try:
            result = user.routeoptions
        except AttributeError:
            result = None

        if result:
            cache.set(cache_key, result, 900)

        return result

    @classmethod
    def get_for_request(cls, request):
        if 'route_options' in request.session:
            session_options = cls(request=request)
            session_options.update(request.session.get('route_options'), ignore_errors=True)
        else:
            session_options = None
        user_options = None
        if request.user.is_authenticated:
            user_options = cls.get_for_user(request.user)

            if user_options is not None:
                user_options.request = request
                user_options.clean_data()
            elif session_options:
                user_options = session_options
                user_options.user = request.user
                user_options.save()
                request.session.pop('route_options')

        return user_options or session_options or cls(request=request)

    def clean_data(self):
        new_data = OrderedDict()
        for name, field in self.get_fields().items():
            value = self.data.get(name)
            if value is None or value not in dict(field.choices):
                value = field.initial
            new_data[name] = value
        self.data = new_data

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clean_data()

        self.request = request

    def __getitem__(self, key):
        try:
            return self.data[key]
        except AttributeError:
            return self.get_fields()[key].initial

    def update(self, value_dict, ignore_errors=False, ignore_unknown=False):
        if not value_dict:
            return
        if isinstance(value_dict, RouteOptions):
            value_dict = value_dict.data
        fields = self.get_fields()
        for key, value in value_dict.items():
            field = fields.get(key)
            if not field:
                if ignore_errors or ignore_unknown:
                    continue
                raise ValidationError(_('Unknown route option: %s') % key)
            if value is None or value not in dict(field.choices):
                if ignore_errors:
                    continue
                raise ValidationError(_('Invalid value for route option %s.') % key)
            self.data[key] = value

    def __setitem__(self, key, value):
        self.update({key: value})

    @property
    def walk_factor(self):
        return {'slow': 0.8, 'default': 1, 'fast': 1.2}[self['walk_speed']]

    def get(self, key, default):
        try:
            return self[key]
        except AttributeError:
            return default

    def serialize(self):
        return [
            {
                'name': name,
                'type': field.widget.input_type,
                'label': str(field.label),
                'choices': [
                    {
                        'name': choice_name,
                        'title': str(choice_title),
                    }
                    for choice_name, choice_title in field.choices
                ],
                'value': self[name],
                'value_display': str(dict(field.choices)[self[name]]),
            }
            for name, field in self.get_fields().items()
        ]

    def serialize_string(self):
        return ','.join('%s=%s' % (key, val) for key, val in self.data.items())

    @classmethod
    def unserialize_string(cls, data):
        return RouteOptions(
            data=dict(item.split('=') for item in data.split(','))
        )

    def save(self, *args, **kwargs):
        if self.request is None or self.request.user.is_authenticated:
            self.user = self.request.user
            return super().save(*args, **kwargs)

        self.request.session['route_options'] = self.data

    def items(self):
        yield from self.data.items()
