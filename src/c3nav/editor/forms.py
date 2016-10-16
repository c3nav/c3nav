import json
from collections import OrderedDict

from django.conf import settings
from django.forms import CharField, ModelForm
from django.forms.models import ModelChoiceField
from django.forms.widgets import HiddenInput
from shapely.geometry.geo import mapping

from c3nav.mapdata.models import Package
from c3nav.mapdata.models.features import Door, Inside, Obstacle, Room
from c3nav.mapdata.permissions import get_unlocked_packages


class FeatureFormMixin(ModelForm):
    def __init__(self, *args, feature_type, request=None, **kwargs):
        self.feature_type = feature_type
        self.request = request
        super().__init__(*args, **kwargs)
        creating = not self.instance.pk

        # disable name on non-direct editing
        if not creating and not settings.DIRECT_EDITING:
            self.fields['name'].disabled = True

        # restrict package choices and field_name
        if not creating:
            if not settings.DIRECT_EDITING:
                self.fields['package'].widget = HiddenInput()
                self.fields['package'].disabled = True
            self.initial['package'] = self.instance.package.name
        elif not settings.DIRECT_EDITING:
            unlocked_packages = get_unlocked_packages(request)
            if len(unlocked_packages) == 1:
                self.fields['package'].widget = HiddenInput()
                self.fields['package'].initial = next(iter(unlocked_packages))
                self.fields['package'].disabled = True
            else:
                self.fields['package'] = ModelChoiceField(
                    queryset=Package.objects.filter(name__in=unlocked_packages),
                )
        self.fields['package'].to_field_name = 'name'

        # hide level widget and set field_name
        self.fields['level'].widget = HiddenInput()
        self.fields['level'].to_field_name = 'name'
        if not creating:
            self.initial['level'] = self.instance.level.name

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


def create_editor_form(feature_model, add_fields=None):
    class EditorForm(FeatureFormMixin, ModelForm):
        class Meta:
            model = feature_model
            fields = ['name', 'package', 'level', 'geometry'] + (add_fields if add_fields is not None else [])

    feature_model.EditorForm = EditorForm


def create_editor_forms():
    create_editor_form(Inside)
    create_editor_form(Room)
    create_editor_form(Obstacle, ['height'])
    create_editor_form(Door)
