from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.cache import never_cache

from c3nav.mapdata.models import Section
from c3nav.mapdata.models.base import EDITOR_FORM_MODELS


def sidebar_view(func):
    @wraps(func)
    def with_ajax_check(request, *args, **kwargs):
        response = func(request, *args, **kwargs)
        if request.is_ajax():
            if isinstance(response, HttpResponseRedirect):
                return render(request, 'editor/redirect.html', {'target': response['location']})
            return response
        return render(request, 'editor/map.html', {'content': response.content})
    return never_cache(with_ajax_check)


@sidebar_view
def main_index(request):
    return render(request, 'editor/index.html', {
        'sections': Section.objects.all(),
    })


@sidebar_view
def section_detail(request, pk):
    pk = get_object_or_404(Section, pk=pk)

    return render(request, 'editor/section.html', {
        'sections': Section.objects.all(),
        'section': pk,
        'section_url': 'editor.section',
    })


@sidebar_view
def edit(request, pk=None, model=None):
    model = EDITOR_FORM_MODELS[model]

    obj = None
    if pk is not None:
        # Edit existing map item
        obj = get_object_or_404(model, pk=pk)
        if False:  # todo can access
            raise PermissionDenied

    new = obj is None
    # noinspection PyProtectedMember
    ctx = {
        'path': request.path,
        'pk': pk,
        'model_title': model._meta.verbose_name,
        'new': new,
        'title': obj.title if obj else None,
    }

    if model == Section:
        ctx.update({
            'section': obj,
            'back_url': reverse('editor.index') if new else reverse('editor.section', kwargs={'pk': pk}),
        })
    elif hasattr(obj, 'section'):
        ctx.update({
            'section': obj.section,
            'back_url': reverse('editor.space', kwargs={'pk': pk}),
        })
    elif hasattr(obj, 'space'):
        ctx.update({
            'section': obj.space.section,
            'back_url': reverse('editor.space', kwargs={'pk': obj.space.pk}),
        })
    else:
        if not request.resolver_match.url_name.endswith('.edit'):
            raise ValueError('url_name does not end with .edit')
        ctx.update({
            'back_url': reverse(request.resolver_match.url_name[:-4]+'list'),
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
                    ctx.update({'target': reverse('editor.index')})
                return redirect(reverse('editor.index') if model == Section else ctx['back_url'])
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

            if not settings.DIRECT_EDITING:
                # todo: suggest changes
                raise NotImplementedError

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
def list_objects(request, model=None, section=None, space=None):
    model = EDITOR_FORM_MODELS[model]
    if not request.resolver_match.url_name.endswith('.list'):
        raise ValueError('url_name does not end with .list')

    # noinspection PyProtectedMember
    ctx = {
        'create_url': request.resolver_match.url_name[:-4]+'create',
        'edit_url': request.resolver_match.url_name[:-4]+'edit',
        'path': request.path,
        'model_name': model.__name__.lower(),
        'model_title': model._meta.verbose_name,
        'model_title_plural': model._meta.verbose_name_plural,
        'objects': model.objects.all().order_by('id'),
    }

    if space is not None:
        ctx.update({
            'back_url': reverse('editor.space', kwargs={'pk': space}),
            'back_title': _('back to space'),
        })
    elif section is not None:
        ctx.update({
            'back_url': reverse('editor.space', kwargs={'pk': space}),
            'back_title': _('back to space'),
        })
    else:
        ctx.update({
            'back_url': reverse('editor.index'),
            'back_title': _('back to overview'),
        })

    return render(request, 'editor/list.html', ctx)
