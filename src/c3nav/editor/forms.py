import json
import operator
from collections import OrderedDict
from functools import reduce

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.forms import BooleanField, CharField, ModelForm, MultipleChoiceField, ValidationError
from django.forms.widgets import HiddenInput
from django.utils.translation import ugettext_lazy as _
from shapely.geometry.geo import mapping

from c3nav.editor.models import ChangeSet, ChangeSetUpdate


class EditorFormBase(ModelForm):
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
            LocationGroupCategory = self.request.changeset.wrap_model('LocationGroupCategory')

            kwargs = {'allow_'+self._meta.model._meta.default_related_name: True}
            categories = LocationGroupCategory.objects.filter(**kwargs).prefetch_related('groups')
            instance_groups = set(self.instance.groups.values_list('pk', flat=True)) if self.instance.pk else set()

            self.fields.pop('groups')

            for category in categories:
                choices = tuple((str(group.pk), group.title) for group in category.groups.all())
                initial = instance_groups & set(group.pk for group in category.groups.all())
                initial = tuple(str(s) for s in initial)
                field = MultipleChoiceField(label=category.title, required=False, initial=initial, choices=choices)
                self.fields['groups_'+category.name] = field
                self.fields.move_to_end('groups_'+category.name, last=False)

        if 'category' in self.fields:
            self.fields['category'].label_from_instance = lambda obj: obj.title

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

        if 'name' in self.fields:
            self.fields.move_to_end('name', last=False)

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

        LocationSlug = self.request.changeset.wrap_model('LocationSlug')
        qs = LocationSlug.objects.filter(slug__in=self.add_redirect_slugs)

        if self.cleaned_data['slug'] in self.add_redirect_slugs:
            raise ValidationError(
                _('Can not add redirecting slug “%s”: it\'s the slug of this object.') % self.cleaned_data['slug']
            )
        else:
            qs = qs.exclude(pk=self.instance.pk)

        for slug in qs.values_list('slug', flat=True)[:1]:
            raise ValidationError(
                _('Can not add redirecting slug “%s”: it is already used elsewhere.') % slug
            )

    def clean(self):
        if 'geometry' in self.fields:
            if not self.cleaned_data.get('geometry'):
                raise ValidationError('Missing geometry.')

        super().clean()

    def _save_m2m(self):
        super()._save_m2m()
        try:
            field = self._meta.model._meta.get_field('groups')
        except FieldDoesNotExist:
            pass
        else:
            if field.many_to_many:
                groups = reduce(operator.or_, (set(value) for name, value in self.cleaned_data.items()
                                               if name.startswith('groups_')), set())
                groups = tuple((int(val) if val.isdigit() else val) for val in groups)
                self.instance.groups.set(groups)


def create_editor_form(editor_model):
    possible_fields = ['slug', 'name', 'altitude', 'category', 'width', 'groups', 'color', 'public',
                       'can_search', 'can_describe', 'outside', 'stuffed', 'geometry',
                       'priority', 'single', 'allow_levels', 'allow_spaces', 'allow_areas', 'allow_pois',
                       'left', 'top', 'right', 'bottom']
    field_names = [field.name for field in editor_model._meta.get_fields() if not field.one_to_many]
    existing_fields = [name for name in possible_fields if name in field_names]

    class EditorForm(EditorFormBase, ModelForm):
        class Meta:
            model = editor_model
            fields = existing_fields

    EditorForm.__name__ = editor_model.__name__+'EditorForm'
    return EditorForm


class ChangeSetForm(ModelForm):
    class Meta:
        model = ChangeSet
        fields = ('title', 'description')


class RejectForm(ModelForm):
    final = BooleanField(label=_('Final rejection'), required=False)

    class Meta:
        model = ChangeSetUpdate
        fields = ('comment', )
