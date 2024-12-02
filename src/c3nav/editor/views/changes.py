from operator import itemgetter

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.db.models.fields.related import ManyToManyField
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.utils.text import format_lazy
from django.utils.translation import get_language_info, get_language
from django.utils.translation import gettext_lazy as _

from c3nav.editor.forms import ChangeSetForm, RejectForm, get_editor_form
from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import sidebar_view
from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models import LocationSlug
from c3nav.mapdata.models.locations import LocationRedirect


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
        restore_model, restore_id = (request.POST.get('restore', '')+'-').split('-')[:2]
        if restore_model and restore_id and restore_id.isdigit():
            if request.changeset.can_edit(request):
                changed_object = changeset.changes.objects.get(restore_model, {}).get(restore_id)
                if changed_object is None:
                    messages.error(request, _("Can't find this changed object"))
                elif not changed_object.deleted:
                    messages.error(request, _("Can't restore this object because it wasn't deleted"))
                else:
                    changed_object.deleted = False
                    messages.success(request, _('Object has been successfully restored.'))
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
                return redirect(reverse('editor.login') + '?r=' + request.path)

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

    changed_objects_data = []

    problems = changeset.problems
    any_problems = problems.any

    # todo: unable to resolve errors like "removed what is already gone"

    added_redirects = {}
    removed_redirects = {}
    for changed_object in changeset.changes:
        if changed_object.obj.model == "locationredirect":
            if changed_object.created and not changed_object.deleted:
                added_redirects.setdefault(changed_object.fields["target"], set()).add(changed_object.fields["slug"])
            elif changed_object.deleted:
                orig_values = changeset.changes.prev.get(changed_object.obj).values
                removed_redirects.setdefault(orig_values["target"], set()).add(orig_values["slug"])
            else:
                raise ValueError  # dafuq? not possibile through the editor

    current_lang = get_language()

    for changed_object in changeset.changes:
        model = apps.get_model("mapdata", changed_object.obj.model)
        if model == LocationRedirect:
            continue
        changes = []

        obj_problems = problems.get_object(changed_object.obj)

        title = None
        if changed_object.titles:
            if current_lang in changed_object.titles:
                title = changed_object.titles[current_lang]
            else:
                title = next(iter(changed_object.titles.values()))

        prev_values = changeset.changes.prev.get(changed_object.obj).values

        edit_url = None
        if not changed_object.deleted:
            # todo: only if it's active
            reverse_kwargs = {'pk': changed_object.obj.id}
            if "space" in prev_values:
                reverse_kwargs["space"] = changed_object.fields.get("space", prev_values["space"])
            elif "level" in prev_values:
                reverse_kwargs["level"] = changed_object.fields.get("level", prev_values["level"])
            try:
                edit_url = reverse('editor.' + model._meta.default_related_name + '.edit', kwargs=reverse_kwargs)
            except NoReverseMatch:
                pass

        changed_object_data = {
            'model': model,
            'model_name': model._meta.model_name,
            'model_title': model._meta.verbose_name,
            'pk': changed_object.obj.id,
            'desc': format_lazy(_('{model} #{id}'), model=model._meta.verbose_name, id=changed_object.obj.id),
            'title': title,
            'changes': changes,
            'edit_url': edit_url,
            'deleted': changed_object.deleted,
        }

        form_fields = get_editor_form(model)._meta.fields

        if changed_object.created:
            changes.append({
                'icon': 'plus',
                'class': 'success',
                'empty': True,
                'title': _('created'),
                'problem': _("can't create this object") if obj_problems.cant_create else None,
            })
        else:
            if obj_problems.obj_does_not_exist:
                changes.append({
                    'icon': 'warning-sign',
                    'class': 'danger',
                    'empty': True,
                    'title': _('no longer exists'),
                    'problem': _("can't update this object because it no longer exists"),
                })
            # todo: make it possible for the user to get rid of this

        update_changes = []
        for name, value in changed_object.fields.items():
            change_data = {
                'icon': 'option-vertical',
                'class': 'muted',
            }
            if name in obj_problems.field_does_not_exist:
                change_data.update({
                    'title': name,
                    'value': value,
                    'order': (10,),
                    'problem': _("this field no longer exists"),
                })
            elif name == 'geometry':
                change_data.update({
                    'icon': 'map-marker',
                    'class': 'info',
                    'empty': True,
                    'title': _('created geometry') if changed_object.created else _('edited geometry'),
                    'order': (8,),
                })
                update_changes.append(change_data)
            elif name == 'data':
                change_data.update({
                    'icon': 'signal',
                    'class': 'info',
                    'empty': True,
                    'title': _('created scan data') if changed_object.created else _('edited scan data'),
                    'order': (9,),
                })
                update_changes.append(change_data)
            else:
                field = model._meta.get_field(name)
                field_title = field.verbose_name
                if isinstance(field, I18nField):
                    for lang, subvalue in value.items():
                        sub_change_data = change_data.copy()
                        lang_info = get_language_info(lang)
                        field_title = format_lazy(_('{field_name} ({lang})'),
                                                  field_name=field.verbose_name,
                                                  lang=lang_info['name_translated'])
                        if subvalue == '' or subvalue is None:
                            sub_change_data.update({
                                'empty': True,
                                'title': format_lazy(_('remove {field_title}'), field_title=field_title),
                            })
                        else:
                            sub_change_data.update({
                                'title': field_title,
                                'value': subvalue,
                            })
                        sub_change_data.update({
                            'order': (4, tuple(code for code, title in settings.LANGUAGES).index(lang)),
                        })
                        update_changes.append(sub_change_data)
                elif isinstance(field, ManyToManyField):
                    continue
                else:
                    if value == '' or value is None:
                        if changed_object.created:
                            continue
                        change_data.update({
                            'empty': True,
                            'title': format_lazy(_('remove {field_title}'), field_title=field_title),
                        })
                    else:
                        # todo: if this is a reference, we wanna not show the id but something betterẞ
                        # todo: display if dummy value was used or other problem exists with this field
                        change_data.update({
                            'title': field_title,
                            'value': value,
                        })
                    order = 5
                    if name == 'slug':
                        order = 1
                    if name not in form_fields:
                        order = 0
                    change_data.update({
                        'order': (order, form_fields.index(name) if order else 1),
                    })
                    update_changes.append(change_data)
        changes.extend(sorted(update_changes, key=itemgetter('order')))

        for name, m2m_changes in changed_object.m2m_changes.items():
            field = model._meta.get_field(name)
            # todo: display problems with m2m values
            for item in m2m_changes.added:
                changes.append({
                    'icon': 'chevron-right',
                    'class': 'info',
                    'title': field.verbose_name,
                    'value': item,
                })
            for item in m2m_changes.removed:
                changes.append({
                    'icon': 'chevron-left',
                    'class': 'info',
                    'title': field.verbose_name,
                    'value': item,
                })

        if issubclass(model, LocationSlug):
            # todo: display problems with redirect slugs
            for slug in added_redirects.get(changed_object.obj.id, ()):
                changes.append({
                    'icon': 'chevron-right',
                    'class': 'info',
                    'title': _('Redirect slugs'),
                    'value': slug,
                })
            for slug in removed_redirects.get(changed_object.obj.id, ()):
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
                'problem': (
                    _("can't delete this object because of protected references")
                    if obj_problems.protected_references else None
                ),
            })

        changed_objects_data.append(changed_object_data)

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
