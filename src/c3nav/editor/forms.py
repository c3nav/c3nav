import json
import time
from collections import OrderedDict

from django.conf import settings
from django.forms import CharField, ModelForm, ValidationError
from django.forms.widgets import HiddenInput
from django.utils.translation import ugettext_lazy as _
from shapely.geometry.geo import mapping


class MapitemFormMixin(ModelForm):
    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        creating = not self.instance.pk

        # disable name on non-direct editing
        if not creating and not settings.DIRECT_EDITING:
            self.fields['name'].disabled = True

        if creating:
            self.fields['name'].initial = hex(int(time.time()*1000000))[2:]

        if 'section' in self.fields:
            # hide section widget
            self.fields['section'].widget = HiddenInput()

        if 'groups' in self.fields:
            # set field_name
            self.fields['groups'].to_field_name = 'name'

        if 'geometry' in self.fields:
            # hide geometry widget
            self.fields['geometry'].widget = HiddenInput()
            if not creating:
                self.initial['geometry'] = json.dumps(mapping(self.instance.geometry), separators=(',', ':'))

        # parse titles
        self.titles = None
        if hasattr(self.instance, 'titles'):
            titles = OrderedDict((lang_code, '') for lang_code, language in settings.LANGUAGES)
            if self.instance is not None and self.instance.pk:
                titles.update(self.instance.titles)

            language_titles = dict(settings.LANGUAGES)
            for language in titles.keys():
                new_title = self.data.get('title_' + language)
                if new_title is not None:
                    titles[language] = new_title
                self.fields['title_' + language] = CharField(label=language_titles.get(language, language),
                                                             required=False,
                                                             initial=titles[language].strip(), max_length=50)
            self.titles = titles

    def clean(self):
        if 'geometry' in self.fields:
            if not self.cleaned_data.get('geometry'):
                raise ValidationError('Missing geometry.')

        if hasattr(self.instance, 'titles') and not any(self.titles.values()):
            raise ValidationError(
                _('You have to select a title in at least one language.')
            )
        super().clean()


def create_editor_form(mapitemtype):
    possible_fields = ['name', 'public', 'altitude', 'level', 'levels', 'geometry', 'width', 'groups', 'color',
                       'location_type', 'can_search', 'can_describe', 'routing_inclusion', 'compiled_room', 'bssids',
                       'category', 'layer']
    existing_fields = [field.name for field in mapitemtype._meta.get_fields() if field.name in possible_fields]

    class EditorForm(MapitemFormMixin, ModelForm):
        class Meta:
            model = mapitemtype
            fields = existing_fields

    mapitemtype.EditorForm = EditorForm


def create_editor_forms():
    from c3nav.mapdata.models.base import FEATURE_TYPES
    for mapitemtype in FEATURE_TYPES.values():
        create_editor_form(mapitemtype)
