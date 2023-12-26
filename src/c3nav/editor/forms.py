import json
import operator
import os
from functools import reduce
from itertools import chain
from operator import attrgetter

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.forms import (BooleanField, CharField, ChoiceField, DecimalField, Form, JSONField, ModelChoiceField,
                          ModelForm, MultipleChoiceField, Select, ValidationError)
from django.forms.widgets import HiddenInput
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from shapely.geometry.geo import mapping

from c3nav.editor.models import ChangeSet, ChangeSetUpdate
from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.forms import I18nModelFormMixin
from c3nav.mapdata.models import GraphEdge
from c3nav.mapdata.models.access import AccessPermission
from c3nav.routing.schemas import LocateRequestPeerSchema


class EditorFormBase(I18nModelFormMixin, ModelForm):
    def __init__(self, *args, space_id=None, request=None, geometry_editable=False, is_json=False, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        creating = not self.instance.pk

        if hasattr(self.instance, 'author_id'):
            if self.instance.author_id is None:
                self.instance.author = request.user

        if 'geometry' in self.fields:
            if not geometry_editable:
                # can't see this geometry in editor
                self.fields.pop('geometry')
            else:
                # hide geometry widget
                self.fields['geometry'].widget = HiddenInput()
                if not creating:
                    self.initial['geometry'] = mapping(self.instance.geometry)

        if 'main_point' in self.fields:
            if not geometry_editable:
                # can't see this geometry in editor
                self.fields.pop('main_point')
            else:
                # hide geometry widget
                self.fields['main_point'].widget = HiddenInput()
                if not creating:
                    self.initial['main_point'] = (
                        mapping(self.instance.main_point)
                        if self.instance.main_point and not self.instance.main_point.is_empty
                        else None
                    )

        if self._meta.model.__name__ == 'Source' and self.request.user.is_superuser:
            Source = self.request.changeset.wrap_model('Source')

            sources = {s['name']: s for s in Source.objects.all().values('name', 'access_restriction_id',
                                                                         'left', 'bottom', 'right', 'top')}
            used_names = set(sources.keys())
            all_names = set(os.listdir(settings.SOURCES_ROOT))
            if not creating:
                used_names.remove(self.instance.name)
                all_names.add(self.instance.name)
            self.fields['name'].widget = Select(choices=tuple((s, s) for s in sorted(all_names-used_names)))

            if creating:
                for s in sources.values():
                    s['access_restriction'] = s['access_restriction_id']
                    del s['access_restriction_id']
                self.fields['copy_from'] = ChoiceField(
                    choices=tuple((('', '---------'), ))+tuple(
                        (json.dumps(sources[name], separators=(',', ':'), cls=DjangoJSONEncoder), name)
                        for name in sorted(used_names)
                    ),
                    required=False
                )

            self.fields['fixed_x'] = DecimalField(label='fixed x', required=False,
                                                  max_digits=7, decimal_places=3, initial=0)
            self.fields['fixed_y'] = DecimalField(label='fixed y', required=False,
                                                  max_digits=7, decimal_places=3, initial=0)
            self.fields['scale_x'] = DecimalField(label='scale x (m/px)', required=False,
                                                  max_digits=7, decimal_places=3, initial=1)
            self.fields['scale_y'] = DecimalField(label='scale y (m/px)', required=False,
                                                  max_digits=7, decimal_places=3, initial=1)
            self.fields['lock_aspect'] = BooleanField(label='lock aspect ratio', required=False, initial=True)
            self.fields['lock_scale'] = BooleanField(label='lock scale (for moving)', required=False, initial=True)

            self.fields.move_to_end('lock_scale', last=False)
            self.fields.move_to_end('lock_aspect', last=False)
            self.fields.move_to_end('scale_y', last=False)
            self.fields.move_to_end('scale_x', last=False)
            self.fields.move_to_end('fixed_y', last=False)
            self.fields.move_to_end('fixed_x', last=False)
            self.fields.move_to_end('access_restriction', last=False)
            if creating:
                self.fields.move_to_end('copy_from', last=False)
            self.fields.move_to_end('name', last=False)

        if self._meta.model.__name__ == 'AccessRestriction':
            AccessRestrictionGroup = self.request.changeset.wrap_model('AccessRestrictionGroup')

            self.fields['groups'].label_from_instance = lambda obj: obj.title
            self.fields['groups'].queryset = AccessRestrictionGroup.qs_for_request(self.request)

        elif 'groups' in self.fields:
            LocationGroupCategory = self.request.changeset.wrap_model('LocationGroupCategory')

            kwargs = {'allow_'+self._meta.model._meta.default_related_name: True}
            categories = LocationGroupCategory.objects.filter(**kwargs).prefetch_related('groups')
            if self.instance.pk:
                instance_groups = tuple(self.instance.groups.values_list('pk', flat=True))
            else:
                instance_groups = ()

            self.fields.pop('groups')

            for category in categories:
                choices = tuple((str(group.pk), group.title)
                                for group in sorted(category.groups.all(), key=self.sort_group))
                category_groups = set(group.pk for group in category.groups.all())
                initial = tuple(str(pk) for pk in instance_groups if pk in category_groups)
                if category.single:
                    name = 'group_'+category.name
                    initial = initial[0] if initial else ''
                    choices = (('', '---'), )+choices
                    field = ChoiceField(label=category.title, required=False, initial=initial, choices=choices,
                                        help_text=category.help_text)
                else:
                    name = 'groups_'+category.name
                    field = MultipleChoiceField(label=category.title_plural, required=False,
                                                initial=initial, choices=choices,
                                                help_text=category.help_text)
                self.fields[name] = field

            if 'label_settings' in self.fields:
                self.fields.move_to_end('label_settings')

            for field in tuple(self.fields.keys()):
                if field.startswith('label_override'):
                    self.fields.move_to_end(field)

        if 'category' in self.fields:
            self.fields['category'].label_from_instance = attrgetter('title')

        if 'groundaltitude' in self.fields:
            self.fields['groundaltitude'].label_from_instance = attrgetter('choice_label')

        if 'label_settings' in self.fields:
            self.fields['label_settings'].label_from_instance = attrgetter('title')

        if 'access_restriction' in self.fields:
            AccessRestriction = self.request.changeset.wrap_model('AccessRestriction')

            self.fields['access_restriction'].label_from_instance = lambda obj: obj.title
            self.fields['access_restriction'].queryset = AccessRestriction.qs_for_request(self.request).order_by(
                "titles__"+get_language(), "titles__en"
            )

        if 'base_mapdata_accessible' in self.fields:
            if not request.user.is_superuser:
                self.fields['base_mapdata_accessible'].disabled = True

        if space_id and 'target_space' in self.fields:
            Space = self.request.changeset.wrap_model('Space')

            GraphNode = self.request.changeset.wrap_model('GraphNode')
            GraphEdge = self.request.changeset.wrap_model('GraphEdge')

            cache_key = 'editor:neighbor_spaces:%s:%s%d' % (
                self.request.changeset.raw_cache_key_by_changes,
                AccessPermission.cache_key_for_request(request, with_update=False),
                space_id
            )
            other_spaces = cache.get(cache_key, None)
            if other_spaces is None:
                AccessPermission.cache_key_for_request(request, with_update=False) + ':' + str(request.user.pk or 0)
                space_nodes = set(GraphNode.objects.filter(space_id=space_id).values_list('pk', flat=True))
                space_edges = GraphEdge.objects.filter(
                    Q(from_node_id__in=space_nodes) | Q(to_node_id__in=space_nodes)
                ).values_list('from_node_id', 'to_node_id')
                other_nodes = set(chain(*space_edges)) - space_nodes
                other_spaces = set(GraphNode.objects.filter(pk__in=other_nodes).values_list('space_id', flat=True))
                other_spaces.discard(space_id)
                cache.set(cache_key, other_spaces, 900)

            for space_field in ('origin_space', 'target_space'):
                other_space_id = getattr(self.instance, space_field+'_id', None)
                if other_space_id:
                    other_spaces.add(other_space_id)

            space_qs = Space.qs_for_request(self.request).filter(pk__in=other_spaces)

            for space_field in ('origin_space', 'target_space'):
                if space_field in self.fields:
                    self.fields[space_field].label_from_instance = lambda obj: obj.title
                    self.fields[space_field].queryset = space_qs

        self.redirect_slugs = None
        self.add_redirect_slugs = None
        self.remove_redirect_slugs = None
        if 'slug' in self.fields:
            self.redirect_slugs = (sorted(self.instance.redirects.values_list('slug', flat=True))
                                   if self.instance.pk else [])
            self.fields['redirect_slugs'] = CharField(label=_('Redirecting Slugs (comma separated)'), required=False,
                                                      initial=','.join(self.redirect_slugs))
            self.fields.move_to_end('redirect_slugs', last=False)
            self.fields.move_to_end('slug', last=False)

        if 'from_node' in self.fields:
            self.fields['from_node'].widget = HiddenInput()

        if 'to_node' in self.fields:
            self.fields['to_node'].widget = HiddenInput()

        if 'data' in self.fields and 'data' in self.initial:
            self.initial['data'] = json.dumps(self.initial['data'])

        self.is_json = is_json
        self.missing_fields = tuple((name, field) for name, field in self.fields.items()
                                    if name not in self.data and not field.required)

    @staticmethod
    def sort_group(group):
        return (-group.priority, group.title)

    def clean_redirect_slugs(self):
        old_redirect_slugs = set(self.redirect_slugs)
        new_redirect_slugs = set(s for s in (s.strip() for s in self.cleaned_data['redirect_slugs'].split(',')) if s)

        self.add_redirect_slugs = new_redirect_slugs - old_redirect_slugs
        self.remove_redirect_slugs = old_redirect_slugs - new_redirect_slugs

        model_slug_field = self._meta.model._meta.get_field('slug')
        for slug in self.add_redirect_slugs:
            self.fields['slug'].run_validators(slug)
            model_slug_field.run_validators(slug)

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

    def clean_data(self):
        try:
            data = json.loads(self.cleaned_data['data'])
        except json.JSONDecodeError:
            raise ValidationError(_('Invalid JSON.'))

        if not isinstance(data, list):
            raise ValidationError(_('Scan data is not a list.'))

        for item in data:
            # todo: catch pydantic validation error
            LocateRequestPeerSchema.model_validate(item)
        return data

    def clean(self):
        if self.is_json:
            for name, field in self.missing_fields:
                self.add_error(name, field.error_messages['required'])

        if 'geometry' in self.fields:
            if not self.cleaned_data.get('geometry'):
                raise ValidationError('Missing geometry.')

        super().clean()

    def _save_m2m(self):
        super()._save_m2m()
        if self._meta.model.__name__ != 'AccessRestriction':
            try:
                field = self._meta.model._meta.get_field('groups')
            except FieldDoesNotExist:
                pass
            else:
                if field.many_to_many:
                    groups = reduce(operator.or_, (set(value) for name, value in self.cleaned_data.items()
                                                   if name.startswith('groups_')), set())
                    groups |= set(value for name, value in self.cleaned_data.items()
                                  if name.startswith('group_') and value)
                    groups = tuple((int(val) if val.isdigit() else val) for val in groups)
                    self.instance.groups.set(groups)


def create_editor_form(editor_model):
    possible_fields = ['slug', 'name', 'title', 'title_plural', 'help_text', 'position_secret',
                       'icon', 'join_edges', 'up_separate', 'bssid', 'main_point', 'external_url', 'hub_import_type',
                       'walk', 'ordering', 'category', 'width', 'groups', 'height', 'color', 'priority', 'hierarchy',
                       'icon_name', 'base_altitude', 'waytype', 'access_restriction', 'default_height', 'door_height',
                       'outside', 'can_search', 'can_describe', 'geometry', 'single', 'altitude', 'short_label',
                       'origin_space', 'target_space', 'data', 'comment', 'slow_down_factor', 'groundaltitude',
                       'extra_seconds', 'speed', 'description', 'speed_up', 'description_up', 'enter_description',
                       'level_change_description', 'base_mapdata_accessible', 'can_report_missing',
                       'label_settings', 'label_override', 'min_zoom', 'max_zoom', 'font_size',
                       'allow_levels', 'allow_spaces', 'allow_areas', 'allow_pois', 'allow_dynamic_locations',
                       'left', 'top', 'right', 'bottom', 'public',
                       'import_tag', 'import_block_data', 'import_block_geom']
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
    oneway = BooleanField(label=_('create one way edges'), required=False)
    activate_next = BooleanField(label=_('activate next node after connecting'), required=False)

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
            self.fields['clicked_position'] = JSONField(widget=HiddenInput(), required=False)

        Space = self.request.changeset.wrap_model('Space')
        space_qs = Space.objects.all()
        self.fields['goto_space'] = ModelChoiceField(space_qs, widget=HiddenInput(), required=False)

    def clean_clicked_position(self):
        return GeometryField(geomtype='point').to_python(self.cleaned_data['clicked_position'])
