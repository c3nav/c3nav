import json
from contextlib import suppress
from functools import wraps

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.cache import never_cache

from c3nav.editor.models import ChangeSet
from c3nav.editor.wrappers import is_created_pk
from c3nav.mapdata.models.base import EDITOR_FORM_MODELS
from c3nav.mapdata.models.locations import LocationRedirect, LocationSlug


def sidebar_view(func):
    @wraps(func)
    def with_ajax_check(request, *args, **kwargs):
        request.changeset = ChangeSet.get_for_request(request)

        response = func(request, *args, **kwargs)
        if request.is_ajax() or 'ajax' in request.GET:
            if isinstance(response, HttpResponseRedirect):
                return render(request, 'editor/redirect.html', {'target': response['location']})
            response.write(render(request, 'editor/fragment_nav.html', {}).content)
            return response
        if isinstance(response, HttpResponseRedirect):
            return response
        return render(request, 'editor/map.html', {'content': response.content})
    return never_cache(with_ajax_check)


def child_model(model, kwargs=None, parent=None):
    related_name = model._meta.default_related_name
    return {
        'title': model._meta.verbose_name_plural,
        'url': reverse('editor.'+related_name+'.list', kwargs=kwargs),
        'count': None if parent is None else getattr(parent, related_name).count(),
    }


@sidebar_view
def main_index(request):
    Level = request.changeset.wrap('Level')
    return render(request, 'editor/index.html', {
        'levels': Level.objects.filter(on_top_of__isnull=True),
        'child_models': [
            child_model(request.changeset.wrap('LocationGroup')),
            child_model(request.changeset.wrap('Source')),
        ],
    })


@sidebar_view
def level_detail(request, pk):
    Level = request.changeset.wrap('Level')
    level = get_object_or_404(Level.objects.select_related('on_top_of').prefetch_related('levels_on_top'), pk=pk)

    return render(request, 'editor/level.html', {
        'levels': Level.objects.filter(on_top_of__isnull=True),
        'level': level,
        'level_url': 'editor.levels.detail',
        'level_as_pk': True,

        'child_models': [child_model(request.changeset.wrap(model_name), kwargs={'level': pk}, parent=level)
                         for model_name in ('Building', 'Space', 'Door')],
        'levels_on_top': level.levels_on_top.all(),
        'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
    })


@sidebar_view
def space_detail(request, level, pk):
    Space = request.changeset.wrap('Space')
    space = get_object_or_404(Space.objects.select_related('level'), level__pk=level, pk=pk)

    return render(request, 'editor/space.html', {
        'level': space.level,
        'space': space,

        'child_models': [child_model(request.changeset.wrap(model_name), kwargs={'space': pk}, parent=space)
                         for model_name in ('Hole', 'Area', 'Stair', 'Obstacle', 'LineObstacle', 'Column', 'Point')],
        'geometry_url': '/api/editor/geometries/?space='+pk,
    })


@sidebar_view
def edit(request, pk=None, model=None, level=None, space=None, on_top_of=None, explicit_edit=False):
    model = request.changeset.wrap(EDITOR_FORM_MODELS[model])
    related_name = model._meta.default_related_name

    Level = request.changeset.wrap('Level')
    Space = request.changeset.wrap('Space')

    obj = None
    if pk is not None:
        # Edit existing map item
        kwargs = {'pk': pk}
        qs = model.objects.all()
        if level is not None:
            kwargs.update({'level__pk': level})
            qs = qs.select_related('level')
        elif space is not None:
            kwargs.update({'space__pk': space})
            qs = qs.select_related('space')
        obj = get_object_or_404(qs, **kwargs)
        if False:  # todo can access
            raise PermissionDenied
    elif level is not None:
        level = get_object_or_404(Level, pk=level)
    elif space is not None:
        space = get_object_or_404(Space, pk=space)
    elif on_top_of is not None:
        on_top_of = get_object_or_404(Level.objects.filter(on_top_of__isnull=True), pk=on_top_of)

    new = obj is None
    # noinspection PyProtectedMember
    ctx = {
        'path': request.path,
        'pk': pk,
        'model_name': model.__name__.lower(),
        'model_title': model._meta.verbose_name,
        'new': new,
        'title': obj.title if obj else None,
    }

    with suppress(FieldDoesNotExist):
        ctx.update({
            'geomtype': model._meta.get_field('geometry').geomtype,
        })

    if model == Level:
        ctx.update({
            'level': obj,
            'back_url': reverse('editor.index') if new else reverse('editor.levels.detail', kwargs={'pk': pk}),
            'nozoom': True,
        })
        if not new:
            ctx.update({
                'geometry_url': '/api/editor/geometries/?level='+str(obj.primary_level_pk),
                'on_top_of': obj.on_top_of,
            })
        elif on_top_of:
            ctx.update({
                'geometry_url': '/api/editor/geometries/?level=' + str(on_top_of.pk),
                'on_top_of': on_top_of,
                'back_url': reverse('editor.levels.detail', kwargs={'pk': on_top_of.pk}),
            })
    elif model == Space and not new:
        level = obj.level
        ctx.update({
            'level': obj.level,
            'back_url': reverse('editor.spaces.detail', kwargs={'level': obj.level.pk, 'pk': pk}),
            'geometry_url': '/api/editor/geometries/?space='+pk,
            'nozoom': True,
        })
    elif model == Space and new:
        ctx.update({
            'level': level,
            'back_url': reverse('editor.spaces.list', kwargs={'level': level.pk}),
            'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
            'nozoom': True,
        })
    elif hasattr(model, 'level'):
        if not new:
            level = obj.level
        ctx.update({
            'level': level,
            'back_url': reverse('editor.'+related_name+'.list', kwargs={'level': level.pk}),
            'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
        })
    elif hasattr(model, 'space'):
        if not new:
            space = obj.space
        ctx.update({
            'level': space.level,
            'back_url': reverse('editor.'+related_name+'.list', kwargs={'space': space.pk}),
            'geometry_url': '/api/editor/geometries/?space='+str(space.pk),
        })
    else:
        kwargs = {}
        if level is not None:
            kwargs.update({'level': level})
        elif space is not None:
            kwargs.update({'space': space})

        ctx.update({
            'back_url': reverse('.'.join(request.resolver_match.url_name.split('.')[:-1]+['list']), kwargs=kwargs),
        })

    if request.method == 'POST':
        if not new and request.POST.get('delete') == '1':
            # Delete this mapitem!
            if request.POST.get('delete_confirm') == '1':
                obj.delete()
                if model == Level:
                    if obj.on_top_of_id is not None:
                        return redirect(reverse('editor.levels.detail', kwargs={'pk': obj.on_top_of_id}))
                    return redirect(reverse('editor.index'))
                elif model == Space:
                    return redirect(reverse('editor.spaces.list', kwargs={'level': obj.level.pk}))
                return redirect(ctx['back_url'])
            ctx['obj_title'] = obj.title
            return render(request, 'editor/delete.html', ctx)

        form = model.EditorForm(instance=model() if new else obj, data=request.POST, request=request)
        if form.is_valid():
            # Update/create objects
            obj = form.save(commit=False)

            if form.titles is not None:
                obj.titles = {}
                for language, title in form.titles.items():
                    if title:
                        obj.titles[language] = title

            if level is not None:
                obj.level = level

            if space is not None:
                obj.space = space

            if on_top_of is not None:
                obj.on_top_of = on_top_of

            obj.save()

            if form.redirect_slugs is not None:
                for slug in form.add_redirect_slugs:
                    obj.redirects.create(slug=slug)

                for slug in form.remove_redirect_slugs:
                    obj.redirects.filter(slug=slug).delete()

            form.save_m2m()
            # request.changeset.changes.all().delete()

            return redirect(ctx['back_url'])
    else:
        form = model.EditorForm(instance=obj, request=request)

    ctx.update({
        'form': form,
    })

    return render(request, 'editor/edit.html', ctx)


@sidebar_view
def list_objects(request, model=None, level=None, space=None, explicit_edit=False):
    if not request.resolver_match.url_name.endswith('.list'):
        raise ValueError('url_name does not end with .list')

    model = request.changeset.wrap(EDITOR_FORM_MODELS[model])

    Level = request.changeset.wrap('Level')
    Space = request.changeset.wrap('Space')

    ctx = {
        'path': request.path,
        'model_name': model.__name__.lower(),
        'model_title': model._meta.verbose_name,
        'model_title_plural': model._meta.verbose_name_plural,
        'explicit_edit': explicit_edit,
    }

    queryset = model.objects.all().order_by('id')
    reverse_kwargs = {}

    if level is not None:
        reverse_kwargs['level'] = level
        level = get_object_or_404(Level, pk=level)
        queryset = queryset.filter(level=level)
        ctx.update({
            'back_url': reverse('editor.levels.detail', kwargs={'pk': level.pk}),
            'back_title': _('back to level'),
            'levels': Level.objects.filter(on_top_of__isnull=True),
            'level': level,
            'level_url': request.resolver_match.url_name,
            'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
        })
    elif space is not None:
        reverse_kwargs['space'] = space
        space = get_object_or_404(Space.objects.select_related('level'), pk=space)
        queryset = queryset.filter(space=space)
        ctx.update({
            'level': space.level,
            'back_url': reverse('editor.spaces.detail', kwargs={'level': space.level.pk, 'pk': space.pk}),
            'back_title': _('back to space'),
            'geometry_url': '/api/editor/geometries/?space='+str(space.pk),
        })
    else:
        ctx.update({
            'back_url': reverse('editor.index'),
            'back_title': _('back to overview'),
        })

    edit_url_name = request.resolver_match.url_name[:-4]+('detail' if explicit_edit else 'edit')
    for obj in queryset:
        reverse_kwargs['pk'] = obj.pk
        obj.edit_url = reverse(edit_url_name, kwargs=reverse_kwargs)
    reverse_kwargs.pop('pk', None)

    ctx.update({
        'create_url': reverse(request.resolver_match.url_name[:-4] + 'create', kwargs=reverse_kwargs),
        'objects': queryset,
    })

    return render(request, 'editor/list.html', ctx)


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

    created_obj_ids = {}

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
            if is_created_pk(pk):
                if pk not in created_obj_ids:
                    created_obj_ids[pk] = len(created_obj_ids)+1
                obj_desc = _('Created %(model)s #%(id)s') % {'model': obj.__class__._meta.verbose_name,
                                                             'id': created_obj_ids[pk]}
            else:
                obj_desc = _('%(model)s #%(id)s') % {'model': obj.__class__._meta.verbose_name, 'id': pk}

            grouped_changes.append({
                'model': obj.__class__,
                'obj': obj_desc,
                'obj_title': obj.title if obj.titles else None,
                'changes': changes,
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


@sidebar_view
def login_view(request):
    redirect_path = request.GET['r'] if request.GET.get('r', '').startswith('/editor/') else reverse('editor.index')
    if request.user.is_authenticated:
        return redirect(redirect_path)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.user_cache)

            if request.changeset.pk is not None:
                if request.session.session_key is None:
                    request.session.save()
                request.changeset.author = form.user_cache
                request.changeset.session_key = request.session.session_key
                request.changeset.save()
            return redirect(redirect_path)
    else:
        form = AuthenticationForm(request)

    return render(request, 'editor/login.html', {'form': form})


@sidebar_view
def logout_view(request):
    redirect_path = request.GET['r'] if request.GET.get('r', '').startswith('/editor/') else reverse('editor.login')
    logout(request)
    return redirect(redirect_path)
