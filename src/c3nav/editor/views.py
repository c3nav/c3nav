from contextlib import suppress
from functools import wraps

from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.cache import never_cache

from c3nav.editor.models import ChangeSet
from c3nav.mapdata.models.base import EDITOR_FORM_MODELS


def sidebar_view(func):
    @wraps(func)
    def with_ajax_check(request, *args, **kwargs):
        request.changeset = ChangeSet.get_for_request(request)

        response = func(request, *args, **kwargs)
        if request.is_ajax() or 'ajax' in request.GET:
            if isinstance(response, HttpResponseRedirect):
                return render(request, 'editor/redirect.html', {'target': response['location']})
            response.write('<a data-changeset href="%s">%s</a>' % (request.changeset.get_absolute_url(),
                                                                   escape(request.changeset.count_display)))
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

            if form.redirect_slugs is not None:
                for slug in form.add_redirect_slugs:
                    obj.redirects.create(slug=slug)

                for slug in form.remove_redirect_slugs:
                    obj.redirects.filter(slug=slug).delete()

            if level is not None:
                obj.level = level

            if space is not None:
                obj.space = space

            if on_top_of is not None:
                obj.on_top_of = on_top_of

            obj.save()
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
    changeset = get_object_or_404(ChangeSet.qs_for_request(request), pk=pk)

    ctx = {
        'pk': pk,
        'changeset': changeset,
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
