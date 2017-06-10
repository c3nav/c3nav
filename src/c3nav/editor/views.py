from contextlib import suppress
from functools import wraps

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.cache import never_cache

from c3nav.mapdata.models import Section, Space
from c3nav.mapdata.models.base import EDITOR_FORM_MODELS


def sidebar_view(func):
    @wraps(func)
    def with_ajax_check(request, *args, **kwargs):
        response = func(request, *args, **kwargs)
        if request.is_ajax() or 'ajax' in request.GET:
            if isinstance(response, HttpResponseRedirect):
                return render(request, 'editor/redirect.html', {'target': response['location']})
            return response
        return render(request, 'editor/map.html', {'content': response.content})
    return never_cache(with_ajax_check)


def child_model(model_name, kwargs=None, parent=None):
    model = apps.get_model('mapdata', model_name)
    related_name = model._meta.default_related_name
    return {
        'title': model._meta.verbose_name_plural,
        'url': reverse('editor.'+related_name+'.list', kwargs=kwargs),
        'count': None if parent is None else getattr(parent, related_name).count(),
    }


@sidebar_view
def main_index(request):
    return render(request, 'editor/index.html', {
        'sections': Section.objects.filter(on_top_of__isnull=True),
        'child_models': [
            child_model('LocationGroup'),
            child_model('Source'),
        ],
    })


@sidebar_view
def section_detail(request, pk):
    section = get_object_or_404(Section.objects.select_related('on_top_of'), pk=pk)

    return render(request, 'editor/section.html', {
        'sections': Section.objects.filter(on_top_of__isnull=True),
        'section': section,
        'section_url': 'editor.sections.detail',
        'section_as_pk': True,

        'child_models': [child_model(model_name, kwargs={'section': pk}, parent=section)
                         for model_name in ('Building', 'Space', 'Door')],
        'sections_on_top': section.sections_on_top.all(),
        'geometry_url': '/api/editor/geometries/?section='+str(section.primary_section_pk),
    })


@sidebar_view
def space_detail(request, section, pk):
    space = get_object_or_404(Space, section__id=section, pk=pk)

    return render(request, 'editor/space.html', {
        'section': space.section,
        'space': space,

        'child_models': [child_model(model_name, kwargs={'space': pk}, parent=space)
                         for model_name in ('Hole', 'Area', 'Stair', 'Obstacle', 'LineObstacle', 'Column', 'Point')],
        'geometry_url': '/api/editor/geometries/?space='+pk,
    })


@sidebar_view
def edit(request, pk=None, model=None, section=None, space=None, explicit_edit=False):
    model = EDITOR_FORM_MODELS[model]
    related_name = model._meta.default_related_name

    obj = None
    if pk is not None:
        # Edit existing map item
        kwargs = {'pk': pk}
        if section is not None:
            kwargs.update({'section__id': section})
        elif space is not None:
            kwargs.update({'space__id': space})
        obj = get_object_or_404(model, **kwargs)
        if False:  # todo can access
            raise PermissionDenied
    elif section is not None:
        section = get_object_or_404(Section, pk=section)
    elif space is not None:
        space = get_object_or_404(Space, pk=space)

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

    if model == Section:
        ctx.update({
            'section': obj,
            'back_url': reverse('editor.index') if new else reverse('editor.sections.detail', kwargs={'pk': pk}),
        })
        if not new:
            ctx.update({
                'geometry_url': '/api/editor/geometries/?section='+str(obj.primary_section_pk),
            })
    elif model == Space and not new:
        ctx.update({
            'section': obj.section,
            'back_url': reverse('editor.spaces.detail', kwargs={'section': obj.section.pk, 'pk': pk}),
            'geometry_url': '/api/editor/geometries/?space='+pk,
        })
    elif model == Space and new:
        ctx.update({
            'section': section,
            'back_url': reverse('editor.spaces.list', kwargs={'section': section.pk}),
            'geometry_url': '/api/editor/geometries/?section='+str(section.primary_section_pk),
        })
    elif hasattr(model, 'section'):
        if obj:
            section = obj.section
        ctx.update({
            'section': section,
            'back_url': reverse('editor.'+related_name+'.list', kwargs={'section': section.pk}),
            'geometry_url': '/api/editor/geometries/?section='+str(section.primary_section_pk),
        })
    elif hasattr(model, 'space'):
        if obj:
            space = obj.space
        ctx.update({
            'section': space.section,
            'back_url': reverse('editor.'+related_name+'.list', kwargs={'space': space.pk}),
            'geometry_url': '/api/editor/geometries/?space='+str(space.pk),
        })
    else:
        kwargs = {}
        if section is not None:
            kwargs.update({'section': section})
        elif space is not None:
            kwargs.update({'space': space})

        ctx.update({
            'back_url': reverse('.'.join(request.resolver_match.url_name.split('.')[:-1]+['list']), kwargs=kwargs),
        })

    if request.method == 'POST':
        if obj is not None and request.POST.get('delete') == '1':
            # Delete this mapitem!
            if request.POST.get('delete_confirm') == '1':
                if not settings.DIRECT_EDITING:
                    # todo: suggest changes
                    raise NotImplementedError
                obj.delete()
                if model == Section:
                    return redirect(reverse('editor.index'))
                elif model == Space:
                    return redirect(reverse('editor.spaces.list', kwargs={'section': obj.section.pk}))
                return redirect(ctx['back_url'])
            return render(request, 'editor/delete.html', ctx)

        form = model.EditorForm(instance=obj, data=request.POST, request=request)
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

            if not settings.DIRECT_EDITING:
                # todo: suggest changes
                raise NotImplementedError

            if section is not None:
                obj.section = section

            if space is not None:
                obj.space = space

            obj.save()
            form.save_m2m()

            return redirect(ctx['back_url'])
    else:
        form = model.EditorForm(instance=obj, request=request)

    ctx.update({
        'form': form,
    })

    return render(request, 'editor/edit.html', ctx)


@sidebar_view
def list_objects(request, model=None, section=None, space=None, explicit_edit=False):
    model = EDITOR_FORM_MODELS[model]
    if not request.resolver_match.url_name.endswith('.list'):
        raise ValueError('url_name does not end with .list')

    # noinspection PyProtectedMember
    ctx = {
        'path': request.path,
        'model_name': model.__name__.lower(),
        'model_title': model._meta.verbose_name,
        'model_title_plural': model._meta.verbose_name_plural,
        'explicit_edit': explicit_edit,
    }

    queryset = model.objects.all().order_by('id')
    reverse_kwargs = {}

    if section is not None:
        reverse_kwargs['section'] = section
        section = get_object_or_404(Section, pk=section)
        queryset = queryset.filter(section=section)
        ctx.update({
            'back_url': reverse('editor.sections.detail', kwargs={'pk': section.pk}),
            'back_title': _('back to section'),
            'sections': Section.objects.filter(on_top_of__isnull=True),
            'section': section,
            'section_url': request.resolver_match.url_name,
            'geometry_url': '/api/editor/geometries/?section='+str(section.primary_section_pk),
        })
    elif space is not None:
        reverse_kwargs['space'] = space
        space = get_object_or_404(Space, pk=space)
        queryset = queryset.filter(space=space)
        ctx.update({
            'section': space.section,
            'back_url': reverse('editor.spaces.detail', kwargs={'section': space.section.pk, 'pk': space.pk}),
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
