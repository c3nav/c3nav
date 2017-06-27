from operator import itemgetter

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import ugettext_lazy as _

from c3nav.editor.models import ChangeSet
from c3nav.editor.utils import is_created_pk
from c3nav.editor.views.base import sidebar_view


@sidebar_view
def changeset_detail(request, pk):
    can_edit = True
    changeset = request.changeset
    if str(pk) != str(request.changeset.pk):
        can_edit = False
        changeset = get_object_or_404(ChangeSet.qs_for_request(request), pk=pk)

    if request.method == 'POST':
        restore = request.POST.get('restore')
        if restore and restore.isdigit():
            change = changeset.changes.filter(pk=restore).first()
            if change is not None and change.can_restore:
                if request.POST.get('restore_confirm') != '1':
                    return render(request, 'editor/changeset_restore_confirm.html', {'pk': change.pk})
                change.restore(request.user if request.user.is_authenticated else None)
                messages.success(request, _('Original state has been restored!'))

        elif request.POST.get('delete') == '1':
            if request.POST.get('delete_confirm') == '1':
                changeset.delete()
                return redirect(reverse('editor.index'))

            return render(request, 'editor/delete.html', {
                'model_title': ChangeSet._meta.verbose_name,
                'obj_title': changeset.title,
            })

    changeset.fill_changes_cache(include_deleted_created=True)

    objects = changeset.get_objects()

    changed_objects_data = []

    for model, changed_objects in changeset.changed_objects.items():
        for pk, changed_object in changed_objects.items():
            obj = objects[model][pk]

            obj_desc = _('%(model)s #%(id)s') % {'model': obj.__class__._meta.verbose_name, 'id': pk}
            if is_created_pk(pk):
                obj_still_exists = pk in changeset.created_objects[obj.__class__]
            else:
                obj_still_exists = pk not in changeset.deleted_existing.get(obj.__class__, ())

            edit_url = None
            if obj_still_exists and can_edit:
                reverse_kwargs = {'pk': obj.pk}
                if hasattr(obj, 'level_id'):
                    reverse_kwargs['level'] = obj.level_id
                elif hasattr(obj, 'space_id'):
                    reverse_kwargs['space'] = obj.space_id
                edit_url = reverse('editor.' + obj.__class__._meta.default_related_name + '.edit',
                                   kwargs=reverse_kwargs)

            changes = []
            changed_object_data = {
                'model': obj.__class__,
                'model_title': obj.__class__._meta.verbose_name,
                'desc': obj_desc,
                'title': obj.title if obj.titles else None,
                'changes': changes,
                'edit_url': edit_url,
                'order': changed_object.created,
            }
            changed_objects_data.append(changed_object_data)

            form_fields = changeset.wrap_model(type(obj)).EditorForm._meta.fields

            if changed_object.is_created:
                changes.append({
                    'icon': 'plus',
                    'class': 'success',
                    'title': _('created'),
                })

            update_changes = []

            for name, value in changed_object.updated_fields.items():
                change_data = {
                    'icon': 'option-vertical',
                    'class': 'muted',
                }
                if name == 'geometry':
                    change_data.update({
                        'icon': 'map-marker',
                        'class': 'info',
                        'title': _('edited geometry'),
                        'order': (8,),
                    })
                else:
                    if name.startswith('title_'):
                        lang = name[6:]
                        field_title = _('Title (%(lang)s)') % {'lang': dict(settings.LANGUAGES).get(lang, lang)}
                        field_value = str(value)
                        if field_value:
                            obj.titles[lang] = field_value
                        else:
                            obj.titles.pop(lang, None)
                        change_data.update({
                            'order': (4, tuple(code for code, title in settings.LANGUAGES).index(lang)),
                        })
                    else:
                        field = model._meta.get_field(name)
                        field_title = field.verbose_name
                        field_value = field.to_python(value)
                        if field.related_model is not None:
                            field_value = objects[field.related_model][field_value].title
                        order = 5
                        if name == 'slug':
                            order = 1
                        if name not in form_fields:
                            order = 0
                        change_data.update({
                            'order': (order, form_fields.index(name) if order else 1),
                        })
                    if not field_value:
                        change_data.update({
                            'title': _('remove %(field_title)s') % {'field_title': field_title},
                        })
                    else:
                        change_data.update({
                            'title': field_title,
                            'value': field_value,
                        })
                update_changes.append(change_data)

            changes.extend(sorted(update_changes, key=itemgetter('order')))

            for m2m_mode in ('m2m_added', 'm2m_removed'):
                m2m_list = getattr(changed_object, m2m_mode).items()
                for name, values in sorted(m2m_list, key=lambda nv: form_fields.index(nv[0])):
                    field = model._meta.get_field(name)
                    for value in values:
                        changes.append({
                            'icon': 'chevron-right' if m2m_mode == 'm2m_added' else 'chevron-left',
                            'class': 'info',
                            'title': field.verbose_name,
                            'value': objects[field.related_model][value].title,
                        })

            if changed_object.deleted:
                changes.append({
                    'icon': 'minus',
                    'class': 'danger',
                    'title': _('deleted'),
                    'order': (9,),
                })

    changed_objects_data = sorted(changed_objects_data, key=itemgetter('order'))

    if changeset.author:
        desc = _('created at %(datetime)s by') % {'datetime': date_format(changeset.created, 'DATETIME_FORMAT')}
    else:
        desc = _('created at %(datetime)s') % {'datetime': date_format(changeset.created, 'DATETIME_FORMAT')}

    ctx = {
        'pk': changeset.pk,
        'changeset': changeset,
        'desc': desc,
        'changed_objects': changed_objects_data,
    }

    return render(request, 'editor/changeset.html', ctx)
