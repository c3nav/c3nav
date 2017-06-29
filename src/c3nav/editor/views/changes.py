from itertools import chain
from operator import itemgetter

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import ugettext_lazy as _

from c3nav.editor.forms import ChangeSetForm
from c3nav.editor.models import ChangeSet
from c3nav.editor.utils import is_created_pk
from c3nav.editor.views.base import sidebar_view
from c3nav.mapdata.models.locations import LocationRedirect, LocationSlug


@sidebar_view
def changeset_detail(request, pk):
    changeset = request.changeset
    if str(pk) != str(request.changeset.pk):
        changeset = get_object_or_404(ChangeSet.qs_for_request(request), pk=pk)
    can_edit = changeset.can_edit(request)

    if request.method == 'POST' and can_edit:
        restore = request.POST.get('restore')
        if restore and restore.isdigit():
            try:
                changed_object = changeset.changed_objects_set.get(pk=restore)
            except:
                pass
            else:
                if changed_object.deleted:
                    changed_object.deleted = False
                    changed_object.save(standalone=True)
                messages.success(request, _('Object has been successfully restored!'))

            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

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

    added_redirects = {}
    removed_redirects = {}
    for changed_object in changeset.changed_objects.get(LocationRedirect, {}).values():
        if changed_object.is_created == changed_object.deleted:
            continue
        values = changed_object.updated_fields
        redirect_list = (removed_redirects if changed_object.deleted else added_redirects)
        redirect_list.setdefault(values['target'], []).append(values['slug'])

    redirect_changed_objects = []

    for pk in set(added_redirects.keys()) | set(removed_redirects.keys()):
        obj = objects[LocationSlug][pk]
        model = obj.__class__
        try:
            changeset.changed_objects[model][pk]
        except KeyError:
            redirect_changed_objects.append((model, {pk: changeset.get_changed_object(obj)}))

    for model, changed_objects in chain(changeset.changed_objects.items(), redirect_changed_objects):
        if model == LocationRedirect:
            continue

        for pk, changed_object in changed_objects.items():
            obj = objects[model][pk]

            obj_desc = _('%(model)s #%(id)s') % {'model': obj.__class__._meta.verbose_name, 'id': pk}
            if is_created_pk(pk):
                obj_still_exists = pk in changeset.created_objects.get(obj.__class__, ())
            else:
                obj_still_exists = pk not in changeset.deleted_existing.get(obj.__class__, ())

            edit_url = None
            if obj_still_exists and can_edit and not isinstance(obj, LocationRedirect):
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
                'pk': changed_object.pk,
                'desc': obj_desc,
                'title': obj.title if getattr(obj, 'titles', None) else None,
                'changes': changes,
                'edit_url': edit_url,
                'deleted': changed_object.deleted,
                'order': (changed_object.deleted and changed_object.is_created, not changed_object.is_created),
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

            if isinstance(obj, LocationSlug):
                for slug in added_redirects.get(obj.pk, ()):
                    changes.append({
                        'icon': 'chevron-right',
                        'class': 'info',
                        'title': _('Redirect slugs'),
                        'value': slug,
                    })
                for slug in removed_redirects.get(obj.pk, ()):
                    changes.append({
                        'icon': 'chevron-left',
                        'class': 'info',
                        'title': _('Redirect slugs'),
                        'value': slug,
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
        created = _('created at %(datetime)s by') % {'datetime': date_format(changeset.created, 'DATETIME_FORMAT')}
    else:
        created = _('created at %(datetime)s') % {'datetime': date_format(changeset.created, 'DATETIME_FORMAT')}

    ctx = {
        'changeset': changeset,
        'created': created,
        'can_edit': can_edit,
        'changed_objects': changed_objects_data,
    }

    return render(request, 'editor/changeset.html', ctx)


@sidebar_view
def changeset_edit(request, pk):
    changeset = request.changeset
    if str(pk) != str(request.changeset.pk):
        changeset = get_object_or_404(ChangeSet.qs_for_request(request), pk=pk)

    if not changeset.can_edit(request):
        raise PermissionDenied

    if request.method == 'POST':
        form = ChangeSetForm(instance=changeset, data=request.POST)
        if form.is_valid():
            form.save()
            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))
    else:
        form = ChangeSetForm(instance=changeset)

    return render(request, 'editor/changeset_edit.html', {
        'changeset': changeset,
        'form': form,
    })
