import json
from collections import OrderedDict

from django.conf import settings
from django.forms import CharField, ModelForm, ValidationError
from django.forms.widgets import HiddenInput
from django.utils.translation import ugettext_lazy as _
from shapely.geometry.geo import mapping

from c3nav.mapdata.models.locations import LocationSlug


class MapitemFormMixin(ModelForm):
    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        creating = not self.instance.pk

        if 'level' in self.fields:
            # hide level widget
            self.fields['level'].widget = HiddenInput()

        if 'space' in self.fields:
            # hide space widget
            self.fields['space'].widget = HiddenInput()

        if 'geometry' in self.fields:
            # hide geometry widget
            self.fields['geometry'].widget = HiddenInput()
            if not creating:
                self.initial['geometry'] = json.dumps(mapping(self.instance.geometry), separators=(',', ':'))

        if 'groups' in self.fields:
            self.fields['groups'].label_from_instance = lambda obj: obj.title_for_forms

        # parse titles
        self.titles = None
        if hasattr(self.instance, 'titles'):
            titles = OrderedDict((lang_code, '') for lang_code, language in settings.LANGUAGES)
            if self.instance is not None and self.instance.pk:
                titles.update(self.instance.titles)

            language_titles = dict(settings.LANGUAGES)
            for language in reversed(titles.keys()):
                new_title = self.data.get('title_' + language)
                if new_title is not None:
                    titles[language] = new_title
                self.fields['title_' + language] = CharField(label=language_titles.get(language, language),
                                                             required=False,
                                                             initial=titles[language].strip(), max_length=50)
                self.fields.move_to_end('title_' + language, last=False)
            self.titles = titles

        self.redirect_slugs = None
        self.add_redirect_slugs = None
        self.remove_redirect_slugs = None
        if 'slug' in self.fields:
            self.redirect_slugs = sorted(self.instance.redirects.values_list('slug', flat=True))
            self.fields['redirect_slugs'] = CharField(label=_('Redirecting Slugs (comma seperated)'), required=False,
                                                      initial=','.join(self.redirect_slugs))
            self.fields.move_to_end('redirect_slugs', last=False)
            self.fields.move_to_end('slug', last=False)

    def clean_redirect_slugs(self):
        old_redirect_slugs = set(self.redirect_slugs)
        new_redirect_slugs = set(s for s in (s.strip() for s in self.cleaned_data['redirect_slugs'].split(',')) if s)

        self.add_redirect_slugs = new_redirect_slugs - old_redirect_slugs
        self.remove_redirect_slugs = old_redirect_slugs - new_redirect_slugs

        for slug in self.add_redirect_slugs:
            self.fields['slug'].run_validators(slug)

        for slug in LocationSlug.objects.filter(slug__in=self.add_redirect_slugs).values_list('slug', flat=True)[:1]:
            raise ValidationError(
                _('Can not add redirecting slug “%s”: it is already used elsewhere.') % slug
            )

    def clean(self):
        if 'geometry' in self.fields:
            if not self.cleaned_data.get('geometry'):
                raise ValidationError('Missing geometry.')

        if hasattr(self.instance, 'titles') and not any(self.titles.values()):
            raise ValidationError(
                _('You have to select a title in at least one language.')
            )

        super().clean()


def create_editor_form(editor_model):
    possible_fields = ['slug', 'name', 'altitude', 'category', 'width', 'groups', 'color', 'public',
                       'can_search', 'can_describe', 'outside', 'stuffed', 'geometry',
                       'left', 'top', 'right', 'bottom']
    field_names = [field.name for field in editor_model._meta.get_fields()]
    existing_fields = [name for name in possible_fields if name in field_names]

    class EditorForm(MapitemFormMixin, ModelForm):
        class Meta:
            model = editor_model
            fields = existing_fields

    editor_model.EditorForm = EditorForm


def create_editor_forms():
    from c3nav.mapdata.models.base import EDITOR_FORM_MODELS
    for mapitemtype in EDITOR_FORM_MODELS.values():
        create_editor_form(mapitemtype)
