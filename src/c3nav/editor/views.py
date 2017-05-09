from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http.response import Http404
from django.shortcuts import get_object_or_404, redirect, render

from c3nav.access.apply import can_access, filter_queryset_by_access
from c3nav.mapdata.models import AreaLocation, Section
from c3nav.mapdata.models.base import EDITOR_FORM_MODELS


def list_mapitemtypes(request, section):
    section = get_object_or_404(Section, pk=section)

    def get_item_count(mapitemtype):
        if hasattr(mapitemtype, 'section'):
            return filter_queryset_by_access(request, mapitemtype.objects.filter(section=section)).count()

        return 0

    return render(request, 'editor/mapitemtypes.html', {
        'section': section,
        'mapitemtypes': [
            {
                'name': name,
                'title': mapitemtype._meta.verbose_name_plural,
                'has_section': hasattr(mapitemtype, 'section'),
                'count': get_item_count(mapitemtype),
            } for name, mapitemtype in EDITOR_FORM_MODELS.items()
        ],
    })


def list_mapitems(request, mapitem_type, section=None):
    mapitemtype = EDITOR_FORM_MODELS.get(mapitem_type)
    if mapitemtype is None:
        raise Http404('Unknown mapitemtype.')

    has_section = hasattr(mapitemtype, 'section')
    if has_section and section is None:
        raise Http404('Missing section.')
    elif not has_section and section is not None:
        return redirect('editor.mapitems', mapitem_type=mapitem_type)

    queryset = mapitemtype.objects.all().order_by('name')

    if section is not None:
        section = get_object_or_404(Section, section)
        if hasattr(mapitemtype, 'section'):
            queryset = queryset.filter(section=section)

    queryset = filter_queryset_by_access(request, queryset)

    if issubclass(mapitemtype, AreaLocation):
        queryset = sorted(queryset, key=AreaLocation.get_sort_key)

    return render(request, 'editor/mapitems.html', {
        'mapitem_type': mapitem_type,
        'title': mapitemtype._meta.verbose_name_plural,
        'has_section': section is not None,
        'has_altitude': hasattr(mapitemtype, 'altitude'),
        'section': section.id,
        'items': queryset,
    })


def edit_mapitem(request, mapitem_type, name=None):
    mapitemtype = EDITOR_FORM_MODELS.get(mapitem_type)
    if mapitemtype is None:
        raise Http404()

    mapitem = None
    if name is not None:
        # Edit existing map item
        mapitem = get_object_or_404(mapitemtype, name=name)
        if not can_access(request, mapitem):
            raise PermissionDenied

    new = mapitem is None
    orig_name = mapitem.name if mapitem is not None else None

    if request.method == 'POST':
        if mapitem is not None and request.POST.get('delete') == '1':
            # Delete this mapitem!
            if request.POST.get('delete_confirm') == '1':
                if not settings.DIRECT_EDITING:
                    # todo: suggest changes
                    raise NotImplementedError

                mapitem.delete()
                return render(request, 'editor/mapitem_success.html', {
                    'mapitem_type': mapitem_type
                })

            return render(request, 'editor/mapitem_delete.html', {
                'name': mapitem.name,
                'mapitem_type': mapitem_type,
                'path': request.path
            })

        form = mapitemtype.EditorForm(instance=mapitem, data=request.POST, request=request)
        if form.is_valid():
            # Update/create mapitem
            mapitem = form.save(commit=False)

            if form.titles is not None:
                mapitem.titles = {}
                for language, title in form.titles.items():
                    if title:
                        mapitem.titles[language] = title

            if not settings.DIRECT_EDITING:
                # todo: suggest changes
                raise NotImplementedError

            mapitem.save()
            form.save_m2m()

            return render(request, 'editor/mapitem_success.html', {
                'mapitem_type': mapitem_type
            })
    else:
        form = mapitemtype.EditorForm(instance=mapitem, request=request)

    return render(request, 'editor/mapitem.html', {
        'form': form,
        'mapitem_type': mapitem_type,
        'title': mapitemtype._meta.verbose_name,
        'has_geometry': hasattr(mapitemtype, 'geometry'),
        'name': orig_name,
        'geomtype': getattr(mapitemtype, 'geomtype', None),
        'path': request.path,
        'new': new
    })
