import json
import operator
from collections import OrderedDict
from functools import reduce

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.forms import (BooleanField, CharField, ChoiceField, Form, ModelChoiceField, ModelForm, MultipleChoiceField,
                          ValidationError)
from django.forms.widgets import HiddenInput
from django.utils.text import format_lazy
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language_info
from shapely.geometry.geo import mapping

from c3nav.editor.models import ChangeSet, ChangeSetUpdate
from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models import GraphEdge


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
            categories = LocationGroupCategory.objects.filter(**kwargs).prefetch_related('groups').order_by('priority')
            if self.instance.pk:
                instance_groups = tuple(self.instance.groups.values_list('pk', flat=True))
            else:
                instance_groups = ()

            self.fields.pop('groups')

            for category in categories:
                choices = tuple((str(group.pk), group.title) for group in category.groups.all())
                category_groups = set(group.pk for group in category.groups.all())
                initial = tuple(str(pk) for pk in instance_groups if pk in category_groups)
                if category.single:
                    name = 'group_'+category.name
                    initial = initial[0] if initial else ''
                    choices = (('', '---'), )+choices
                    field = ChoiceField(label=category.title, required=False, initial=initial, choices=choices)
                else:
                    name = 'groups_'+category.name
                    field = MultipleChoiceField(label=category.title, required=False, initial=initial, choices=choices)
                self.fields[name] = field
                self.fields.move_to_end(name, last=False)

        if 'category' in self.fields:
            self.fields['category'].label_from_instance = lambda obj: obj.title

        if 'access_restriction' in self.fields:
            AccessRestriction = self.request.changeset.wrap_model('AccessRestriction')

            self.fields['access_restriction'].label_from_instance = lambda obj: obj.title
            self.fields['access_restriction'].queryset = AccessRestriction.qs_for_request(self.request)

        # parse titles
        self.titles = None
        if hasattr(self.instance, 'titles'):
            titles = OrderedDict((lang_code, '') for lang_code, language in settings.LANGUAGES)
            if self.instance is not None and self.instance.pk:
                titles.update(self.instance.titles)

            for language in reversed(titles.keys()):
                new_title = self.data.get('title_' + language)
                if new_title is not None:
                    titles[language] = new_title
                language_info = get_language_info(language)
                field_title = format_lazy(_('Title ({lang})'), lang=language_info['name_translated'])
                self.fields['title_' + language] = CharField(label=field_title,
                                                             required=False,
                                                             initial=titles[language].strip(), max_length=50)
                self.fields.move_to_end('title_' + language, last=False)
            self.titles = titles

        if 'short_label' in self.fields:
            self.fields.move_to_end('short_label', last=False)

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

        if 'from_node' in self.fields:
            self.fields['from_node'].widget = HiddenInput()

        if 'to_node' in self.fields:
            self.fields['to_node'].widget = HiddenInput()

    def clean_redirect_slugs(self):
        old_redirect_slugs = set(self.redirect_slugs)
        new_redirect_slugs = set(s for s in (s.strip() for s in self.cleaned_data['redirect_slugs'].split(',')) if s)

        self.add_redirect_slugs = new_redirect_slugs - old_redirect_slugs
        self.remove_redirect_slugs = old_redirect_slugs - new_redirect_slugs

        for slug in self.add_redirect_slugs:
            self.fields['slug'].run_validators(slug)

        LocationSlug = self.request.changeset.wrap_model('LocationSlug')
        qs = LocationSlug.objects.filter(slug__in=self.add_redirect_slugs)

        if 'slug' in self.cleaned_data and self.cleaned_data['slug'] in self.add_redirect_slugs:
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
                groups |= set(value for name, value in self.cleaned_data.items() if name.startswith('group_') and value)
                groups = tuple((int(val) if val.isdigit() else val) for val in groups)
                self.instance.groups.set(groups)


def create_editor_form(editor_model):
    possible_fields = ['slug', 'name', 'ordering', 'category', 'width', 'groups', 'color', 'priority', 'base_altitude',
                       'waytype', 'access_restriction', 'height', 'default_height', 'can_search', 'can_describe',
                       'outside', 'geometry', 'single', 'allow_levels', 'allow_spaces', 'allow_areas', 'allow_pois',
                       'altitude', 'short_label', 'left', 'top', 'right', 'bottom']
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


class GraphEdgeSettingsForm(ModelForm):
    class Meta:
        model = GraphEdge
        fields = ('waytype', 'access_restriction', )

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

        WayType = self.request.changeset.wrap_model('WayType')
        self.fields['waytype'].label_from_instance = lambda obj: obj.title
        self.fields['waytype'].queryset = WayType.objects.all()
        self.fields['waytype'].to_field_name = None

        AccessRestriction = self.request.changeset.wrap_model('AccessRestriction')
        self.fields['access_restriction'].label_from_instance = lambda obj: obj.title
        self.fields['access_restriction'].queryset = AccessRestriction.qs_for_request(self.request)


class GraphEditorActionForm(Form):
    def __init__(self, *args, request=None, allow_clicked_position=False, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)

        GraphNode = self.request.changeset.wrap_model('GraphNode')
        graph_node_qs = GraphNode.objects.all()
        self.fields['active_node'] = ModelChoiceField(graph_node_qs, widget=HiddenInput(), required=False)
        self.fields['clicked_node'] = ModelChoiceField(graph_node_qs, widget=HiddenInput(), required=False)

        if allow_clicked_position:
            self.fields['clicked_position'] = CharField(widget=HiddenInput(), required=False)

        Space = self.request.changeset.wrap_model('Space')
        space_qs = Space.objects.all()
        self.fields['goto_space'] = ModelChoiceField(space_qs, widget=HiddenInput(), required=False)

    def clean_clicked_position(self):
        return GeometryField(geomtype='point').to_python(self.cleaned_data['clicked_position'])


class GraphEditorSettingsForm(Form):
    node_click = ChoiceField(label=_('when clicking on an existing node…'), choices=(
        ('connect_or_toggle', _('connect if possible, otherwise toggle')),
        ('connect', _('connect if possible')),
        ('activate', _('activate')),
        ('deactivate', _('deactivate')),
        ('toggle', _('toggle')),
        ('delete', _('delete node')),
        ('noop', _('do nothing')),
    ), initial='connect_or_toggle')

    click_anywhere = ChoiceField(label=_('when clicking anywhere…'), choices=(
        ('create_node', _('create node')),
        ('create_node_if_none_active', _('create node if no node is active')),
        ('create_node_if_other_active', _('create node if another node is active')),
        ('noop', _('do nothing')),
    ), initial='create_node')

    after_create_node = ChoiceField(label=_('after creating a new node…'), choices=(
        ('connect', _('connect to active node if possible')),
        ('activate', _('activate node')),
        ('deactivate', _('deactivate active node')),
        ('noop', _('do nothing')),
    ), initial='connect')

    connect_nodes = ChoiceField(label=_('when connecting two nodes…'), choices=(
        ('bidirectional', _('create edge in both directions')),
        ('unidirectional', _('create edge in one direction')),
        ('unidirectional_force', _('create edge, delete other direction')),
        ('delete_bidirectional', _('delete edges in both directions')),
        ('delete_unidirectional', _('delete edge in one direction')),
    ), initial='bidirectional')

    create_existing_edge = ChoiceField(label=_('when creating an already existing edge…'), choices=(
        ('overwrite_toggle', _('overwrite if not identical, otherwise delete')),
        ('overwrite_always', _('overwrite')),
        ('overwrite_waytype', _('overwrite waytype')),
        ('overwrite_access', _('overwrite access restriction')),
        ('delete', _('delete')),
    ), initial='overwrite_toggle')

    after_connect_nodes = ChoiceField(label=_('after connecting two nodes…'), choices=(
        ('reset', _('deactivate active node')),
        ('keep_first_active', _('keep first node active')),
        ('set_second_active', _('set second node as active')),
    ), initial='reset')
