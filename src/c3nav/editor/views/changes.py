from itertools import chain
from operator import itemgetter

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.text import format_lazy
from django.utils.translation import get_language_info
from django.utils.translation import gettext_lazy as _

from c3nav.editor.forms import ChangeSetForm, RejectForm, get_editor_form
from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import sidebar_view
from c3nav.editor.wrappers import is_created_pk
from c3nav.mapdata.models.locations import LocationRedirect, LocationSlug


@sidebar_view(select_related=('last_update', 'last_state_update', 'last_change', 'author'))
def changeset_detail(request, pk):
    changeset = request.changeset
    active = True
    if str(pk) != str(request.changeset.pk):
        active = False
        qs = ChangeSet.qs_for_request(request).select_related('last_update', 'last_state_update',
                                                              'last_change', 'author')
        changeset = get_object_or_404(qs, pk=pk)

    if not changeset.can_see(request):
        raise Http404

    can_edit = changeset.can_edit(request)
    can_delete = changeset.can_delete(request)

    if request.method == 'POST':
        restore = request.POST.get('restore')
        if restore and restore.isdigit():
            with changeset.lock_to_edit(request) as changeset:
                if changeset.can_edit(request):
                    try:
                        changed_object = changeset.changed_objects_set.get(pk=restore)
                    except Exception:
                        pass
                    else:
                        try:
                            changed_object.restore()
                            messages.success(request, _('Object has been successfully restored.'))
                        except PermissionError:
                            messages.error(request, _('You cannot restore this object, because it depends on '
                                                      'a deleted object or it would violate a unique contraint.'))

                else:
                    messages.error(request, _('You can not edit changes on this change set.'))

            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

        elif request.POST.get('activate') == '1':
            with changeset.lock_to_edit(request) as changeset:
                if changeset.can_activate(request):
                    changeset.activate(request)
                    messages.success(request, _('You activated this change set.'))
                else:
                    messages.error(request, _('You can not activate this change set.'))

            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

        elif request.POST.get('propose') == '1':
            if not request.user.is_authenticated:
                messages.info(request, _('You need to log in to propose changes.'))
                return redirect(reverse('editor.login')+'?r='+request.path)

            with changeset.lock_to_edit(request) as changeset:
                if not changeset.title or not changeset.description:
                    messages.warning(request, _('You need to add a title an a description to propose this change set.'))
                    return redirect(reverse('editor.changesets.edit', kwargs={'pk': changeset.pk}))

                if changeset.can_propose(request):
                    changeset.propose(request.user)
                    messages.success(request, _('You proposed your changes.'))
                else:
                    messages.error(request, _('You cannot propose this change set.'))

            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

        elif request.POST.get('unpropose') == '1':
            with changeset.lock_to_edit(request) as changeset:
                if changeset.can_unpropose(request):
                    changeset.unpropose(request.user)
                    messages.success(request, _('You unproposed your changes.'))
                else:
                    messages.error(request, _('You cannot unpropose this change set.'))

            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

        elif request.POST.get('review') == '1':
            with changeset.lock_to_edit(request) as changeset:
                if changeset.can_start_review(request):
                    changeset.start_review(request.user)
                    messages.success(request, _('You are now reviewing these changes.'))
                else:
                    messages.error(request, _('You cannot review these changes.'))

            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

        elif request.POST.get('reject') == '1':
            with changeset.lock_to_edit(request) as changeset:
                if not changeset.can_end_review(request):
                    messages.error(request, _('You cannot reject these changes.'))
                    return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

                if request.POST.get('reject_confirm') == '1':
                    form = RejectForm(data=request.POST)
                    if form.is_valid():
                        changeset.reject(request.user, form.cleaned_data['comment'], form.cleaned_data['final'])
                        messages.success(request, _('You rejected these changes.'))
                        return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))
                else:
                    form = RejectForm()

                return render(request, 'editor/changeset_reject.html', {
                    'changeset': changeset,
                    'form': form,
                })

        elif request.POST.get('unreject') == '1':
            with changeset.lock_to_edit(request) as changeset:
                if not changeset.can_unreject(request):
                    messages.error(request, _('You cannot unreject these changes.'))
                    return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

                changeset.unreject(request.user)
                messages.success(request, _('You unrejected these changes.'))

            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

        elif request.POST.get('apply') == '1':
            with changeset.lock_to_edit(request) as changeset:
                if not changeset.can_end_review(request):
                    messages.error(request, _('You cannot accept and apply these changes.'))
                    return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

                if request.POST.get('apply_confirm') == '1':
                    changeset.apply(request.user)
                    messages.success(request, _('You accepted and applied these changes.'))
                    return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

                return render(request, 'editor/changeset_apply.html', {})

        elif request.POST.get('delete') == '1':
            with changeset.lock_to_edit(request) as changeset:
                if not changeset.can_delete(request):
                    messages.error(request, _('You cannot delete this change set.'))

                if request.POST.get('delete_confirm') == '1':
                    changeset.delete()
                    messages.success(request, _('You deleted this change set.'))
                    if request.user.is_authenticated:
                        return redirect(reverse('editor.users.detail', kwargs={'pk': request.user.pk}))
                    else:
                        return redirect(reverse('editor.index'))

                return render(request, 'editor/delete.html', {
                    'model_title': ChangeSet._meta.verbose_name,
                    'obj_title': changeset.title,
                })

    changeset.fill_changes_cache()

    ctx = {
        'changeset': changeset,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'can_propose': changeset.can_propose(request),
        'can_unpropose': changeset.can_unpropose(request),
        'can_start_review': changeset.can_start_review(request),
        'can_end_review': changeset.can_end_review(request),
        'can_unreject': changeset.can_unreject(request),
        'active': active,
    }

    cache_key = '%s:%s:%s:view_data' % (changeset.cache_key_by_changes,
                                        changeset.last_update_id,
                                        int(can_edit))
    changed_objects_data = cache.get(cache_key)
    if changed_objects_data:
        ctx['changed_objects'] = changed_objects_data
        return render(request, 'editor/changeset.html', ctx)

    objects = changeset.get_objects()

    changed_objects_data = []

    added_redirects = {}
    removed_redirects = {}
    for changed_object in changeset.changed_objects.get(LocationRedirect, {}).values():
        if changed_object.is_created == changed_object.deleted:
            continue
        obj = objects[LocationRedirect][changed_object.obj_pk]
        redirect_list = (removed_redirects if changed_object.deleted else added_redirects)
        redirect_list.setdefault(obj.target_id, []).append(obj.slug)

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
            if pk in objects[model]:
                obj = objects[model][pk]
                obj_desc = format_lazy(_('{model} #{id}'), model=obj.__class__._meta.verbose_name, id=pk)
                if is_created_pk(pk):
                    obj_still_exists = pk in changeset.created_objects.get(obj.__class__, ())
                else:
                    obj_still_exists = pk not in changeset.deleted_existing.get(obj.__class__, ())
            else:
                obj = changed_object.obj._obj
                obj_still_exists = False
                if changed_object.deleted:
                    obj_desc = format_lazy(_('{model} #{id}'), model=obj.__class__._meta.verbose_name, id=pk)

                else:
                    obj_desc = format_lazy(_('{model} #{id} (deleted outside this changeset)'),
                                           model=obj.__class__._meta.verbose_name, id=pk)

            edit_url = None
            if obj_still_exists and can_edit and not isinstance(obj, LocationRedirect):
                reverse_kwargs = {'pk': obj.pk}
                if hasattr(obj, 'space_id'):
                    reverse_kwargs['space'] = obj.space_id
                elif hasattr(obj, 'level_id'):
                    reverse_kwargs['level'] = obj.level_id
                try:
                    edit_url = reverse('editor.' + obj.__class__._meta.default_related_name + '.edit',
                                       kwargs=reverse_kwargs)
                except NoReverseMatch:
                    pass

            changes = []
            missing_dependencies = changed_object.get_missing_dependencies()
            unique_collisions = changed_object.get_unique_collisions()
            changed_object_data = {
                'model': obj.__class__,
                'model_title': obj.__class__._meta.verbose_name,
                'pk': changed_object.pk,
                'desc': obj_desc,
                'title': obj.title if getattr(obj, 'titles', None) else None,
                'changes': changes,
                'edit_url': edit_url,
                'deleted': changed_object.deleted,
                'missing_dependencies': missing_dependencies,
                'unique_collisions': unique_collisions,
                'order': (changed_object.deleted and changed_object.is_created, not changed_object.is_created),
            }
            changed_objects_data.append(changed_object_data)

            form_fields = get_editor_form(model)._meta.fields

            if changed_object.is_created:
                changes.append({
                    'icon': 'plus',
                    'class': 'success',
                    'empty': True,
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
                        'empty': True,
                        'title': _('created geometry') if changed_object.is_created else _('edited geometry'),
                        'order': (8,),
                    })
                elif name == 'data':
                    change_data.update({
                        'icon': 'signal',
                        'class': 'info',
                        'empty': True,
                        'title': _('created scan data') if changed_object.is_created else _('edited scan data'),
                        'order': (9,),
                    })
                else:
                    if '__i18n__' in name:
                        orig_name, i18n, lang = name.split('__')
                        lang_info = get_language_info(lang)
                        field = model._meta.get_field(orig_name)
                        field_title = format_lazy(_('{field_name} ({lang})'),
                                                  field_name=field.verbose_name,
                                                  lang=lang_info['name_translated'])
                        field_value = str(value)
                        if field_value:
                            getattr(obj, field.attname)[lang] = field_value
                        else:
                            getattr(obj, field.attname).pop(lang, None)
                        change_data.update({
                            'order': (4, tuple(code for code, title in settings.LANGUAGES).index(lang)),
                        })
                    else:
                        field = model._meta.get_field(name)
                        field_title = field.verbose_name
                        if field.related_model is not None:
                            if value is None:
                                field_value = None
                            else:
                                if issubclass(field.related_model, User):
                                    field_value = objects[field.related_model][value].username
                                else:
                                    field_value = objects[field.related_model][value].title
                                change_data.update({
                                    'missing_dependency': field.name in missing_dependencies,
                                })
                        else:
                            field_value = field.to_python(value)
                        if name in unique_collisions:
                            change_data.update({
                                'unique_collision': field.name in unique_collisions,
                            })
                        order = 5
                        if name == 'slug':
                            order = 1
                        if name not in form_fields:
                            order = 0
                        change_data.update({
                            'order': (order, form_fields.index(name) if order else 1),
                        })
                    if field_value == '' or field_value is None:
                        change_data.update({
                            'empty': True,
                            'title': format_lazy(_('remove {field_title}'), field_title=field_title),
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
                    'empty': True,
                    'title': _('deleted'),
                    'order': (9,),
                })

    changed_objects_data = sorted(changed_objects_data, key=itemgetter('order'))

    cache.set(cache_key, changed_objects_data, 300)
    ctx['changed_objects'] = changed_objects_data

    return render(request, 'editor/changeset.html', ctx)


@sidebar_view
def changeset_edit(request, pk):
    changeset = request.changeset
    if str(pk) != str(request.changeset.pk):
        changeset = get_object_or_404(ChangeSet.qs_for_request(request), pk=pk)

    with changeset.lock_to_edit(request) as changeset:
        if not changeset.can_edit(request):
            messages.error(request, _('You cannot edit this change set.'))
            return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))

        if request.method == 'POST':
            form = ChangeSetForm(instance=changeset, data=request.POST)
            if form.is_valid():
                changeset = form.instance
                update = changeset.updates.create(user=request.user,
                                                  title=changeset.title, description=changeset.description)
                changeset.last_update = update
                changeset.save()
                return redirect(reverse('editor.changesets.detail', kwargs={'pk': changeset.pk}))
        else:
            form = ChangeSetForm(instance=changeset)

    return render(request, 'editor/changeset_edit.html', {
        'changeset': changeset,
        'form': form,
    })


@sidebar_view
def changeset_redirect(request):
    changeset = request.changeset
    changeset_url = changeset.get_absolute_url()
    if not changeset_url:
        raise Http404
    return redirect(changeset_url)
