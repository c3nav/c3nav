import json

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import ugettext_lazy as _

from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import sidebar_view
from c3nav.editor.wrappers import is_created_pk
from c3nav.mapdata.models.locations import LocationRedirect, LocationSlug


@sidebar_view
def changeset_detail(request, pk):
    if str(pk) != str(request.changeset.pk):
        changeset = get_object_or_404(ChangeSet.qs_for_request(request), pk=pk)
    else:
        changeset = request.changeset

    # collect pks of relevant objects
    object_pks = {}
    for change in changeset.changes.all():
        object_pks.setdefault(change.model_class, set()).add(change.obj_pk)
        model = None
        if change.action == 'update':
            if change.model_class == LocationRedirect:
                if change.field_name == 'target':
                    object_pks.setdefault(LocationSlug, set()).add(json.loads(change.field_value))
                    continue
            elif not change.field_name.startswith('title_'):
                field = change.model_class._meta.get_field(change.field_name)
                model = getattr(field, 'related_model', None)
        if change.action in ('m2m_add', 'm2m_remove'):
            model = change.model_class._meta.get_field(change.field_name).related_model
        if model is not None:
            object_pks.setdefault(model, set()).add(json.loads(change.field_value))

    # retrieve relevant objects
    objects = {}
    for model, pks in object_pks.items():
        created_pks = set(pk for pk in pks if is_created_pk(pk))
        existing_pks = pks-created_pks
        model_objects = {}
        if existing_pks:
            for obj in model.objects.filter(pk__in=existing_pks):
                if model == LocationSlug:
                    obj = obj.get_child()
                model_objects[obj.pk] = obj
        if created_pks:
            for pk in created_pks:
                model_objects[pk] = changeset.get_created_object(model, pk, allow_deleted=True)._obj
                model_objects[pk].titles = {}
        objects[model] = model_objects

    grouped_changes = []
    changes = []
    last_obj = None
    for change in changeset.changes.all():
        pk = change.obj_pk
        obj = objects[change.model_class][pk]
        if change.model_class == LocationRedirect:
            if change.action not in ('create', 'delete'):
                continue
            change.action = 'm2m_add' if change.action == 'create' else 'm2m_remove'
            change.field_name = 'redirects'
            change.field_value = obj.slug
            pk = obj.target_id
            obj = objects[LocationSlug][pk]

        if obj != last_obj:
            changes = []
            obj_desc = _('%(model)s #%(id)s') % {'model': obj.__class__._meta.verbose_name, 'id': pk}
            if is_created_pk(pk):
                obj_desc = _('%s (created)') % obj_desc
                obj_still_exists = int(pk[1:]) in changeset.created_objects[obj.__class__]
            else:
                obj_still_exists = pk not in changeset.deleted_existing[obj.__class__]

            edit_url = None
            if obj_still_exists and changeset == request.changeset:
                reverse_kwargs = {'pk': obj.pk}
                if hasattr(obj, 'level'):
                    reverse_kwargs['level'] = obj.level_id
                elif hasattr(obj, 'space'):
                    reverse_kwargs['space'] = obj.space_id
                edit_url = reverse('editor.'+obj.__class__._meta.default_related_name+'.edit', kwargs=reverse_kwargs)

            grouped_changes.append({
                'model': obj.__class__,
                'model_title': obj.__class__._meta.verbose_name,
                'obj': obj_desc,
                'obj_title': obj.title if obj.titles else None,
                'changes': changes,
                'edit_url': edit_url,
            })
            last_obj = obj

        change_data = {
            'pk': change.pk,
            'author': change.author,
            'created': _('created at %(datetime)s') % {'datetime': date_format(change.created, 'DATETIME_FORMAT')},
        }
        changes.append(change_data)
        if change.action == 'create':
            change_data.update({
                'icon': 'plus',
                'class': 'success',
                'title': _('created'),
            })
        elif change.action == 'delete':
            change_data.update({
                'icon': 'minus',
                'class': 'danger',
                'title': _('deleted')
            })
        elif change.action == 'update':
            change_data.update({
                'icon': 'option-vertical',
                'class': 'muted',
            })
            if change.field_name == 'geometry':
                change_data.update({
                    'icon': 'map-marker',
                    'class': 'info',
                    'title': _('edited geometry'),
                })
            else:
                if change.field_name.startswith('title_'):
                    lang = change.field_name[6:]
                    field_title = _('Title (%(lang)s)') % {'lang': dict(settings.LANGUAGES).get(lang, lang)}
                    field_value = str(json.loads(change.field_value))
                    if field_value:
                        obj.titles[lang] = field_value
                    else:
                        obj.titles.pop(lang, None)
                else:
                    field = obj.__class__._meta.get_field(change.field_name)
                    field_title = field.verbose_name
                    field_value = field.to_python(json.loads(change.field_value))
                    model = getattr(field, 'related_model', None)
                    if model is not None:
                        field_value = objects[model][field_value].title
                if not field_value:
                    change_data.update({
                        'title': _('unset %(field_title)s') % {'field_title': field_title},
                    })
                else:
                    change_data.update({
                        'title': field_title,
                        'value': field_value,
                    })
        elif change.action in ('m2m_add', 'm2m_remove'):
            change_data.update({
                'icon': 'chevron-right' if change.action == 'm2m_add' else 'chevron-left',
                'class': 'info',
            })
            if change.field_name == 'redirects':
                change_data.update({
                    'title': _('Redirecting slugs'),
                    'value': change.field_value,
                })
            else:
                field = obj.__class__._meta.get_field(change.field_name)
                change_data.update({
                    'title': field.verbose_name,
                    'value': objects[field.related_model][json.loads(change.field_value)].title,
                })
        else:
            change_data.update({
                'title': '???',
            })

    if changeset.author:
        desc = _('created at %(datetime)s by') % {'datetime': date_format(changeset.created, 'DATETIME_FORMAT')}
    else:
        desc = _('created at %(datetime)s') % {'datetime': date_format(changeset.created, 'DATETIME_FORMAT')}

    ctx = {
        'pk': pk,
        'changeset': changeset,
        'desc': desc,
        'grouped_changes': grouped_changes,
    }

    if request.method == 'POST':
        if request.POST.get('delete') == '1':
            if request.POST.get('delete_confirm') == '1':
                changeset.delete()
                return redirect(reverse('editor.index'))

            ctx.update({
                'model_title': ChangeSet._meta.verbose_name,
                'obj_title': changeset.title,
            })
            return render(request, 'editor/delete.html', ctx)

    return render(request, 'editor/changeset.html', ctx)
