from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.core.signing import BadSignature
from django.http.response import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation

from c3nav.editor.hosters import get_hoster_for_package, hosters
from c3nav.mapdata.models.base import MAPITEM_TYPES
from c3nav.mapdata.models.package import Package
from c3nav.mapdata.packageio.write import json_encode
from c3nav.mapdata.permissions import can_access_package, filter_queryset_by_package_access


def list_mapitemtypes(request, level):
    def get_item_count(mapitemtype):
        if not hasattr(mapitemtype, 'level'):
            return 0
        return filter_queryset_by_package_access(request, mapitemtype.objects.filter(level__name=level)).count()

    return render(request, 'editor/mapitemtypes.html', {
        'level': level,
        'mapitemtypes': [
            {
                'name': name,
                'title': mapitemtype._meta.verbose_name_plural,
                'has_level': hasattr(mapitemtype, 'level'),
                'count': get_item_count(mapitemtype),
            } for name, mapitemtype in MAPITEM_TYPES.items()
        ],
    })


def list_mapitems(request, mapitem_type, level=None):
    mapitemtype = MAPITEM_TYPES.get(mapitem_type)
    if mapitemtype is None:
        raise Http404('Unknown mapitemtype.')

    if hasattr(mapitemtype, 'level') and level is None:
        raise Http404('Missing level.')
    elif not hasattr(mapitemtype, 'level') and level is not None:
        return redirect('editor.mapitems', mapitem_type=mapitem_type)

    queryset = mapitemtype.objects.all()
    if level is not None:
        queryset = queryset.filter(level__name=level)

    return render(request, 'editor/mapitems.html', {
        'mapitem_type': mapitem_type,
        'title': mapitemtype._meta.verbose_name_plural,
        'has_level': level is not None,
        'has_elevator': hasattr(mapitemtype, 'elevator'),
        'level': level,
        'items': filter_queryset_by_package_access(request, queryset),
    })


def edit_mapitem(request, mapitem_type, name=None):
    mapitemtype = MAPITEM_TYPES.get(mapitem_type)
    if mapitemtype is None:
        raise Http404()

    mapitem = None
    if name is not None:
        # Edit existing map item
        mapitem = get_object_or_404(mapitemtype, name=name)
        if not can_access_package(request, mapitem.package):
            raise PermissionDenied

    new = mapitem is None
    orig_name = mapitem.name if mapitem is not None else None

    if request.method == 'POST':
        if mapitem is not None and request.POST.get('delete') == '1':
            # Delete this mapitem!
            if request.POST.get('delete_confirm') == '1':
                if not settings.DIRECT_EDITING:
                    with translation.override('en'):
                        commit_msg = 'Deleted %s: %s' % (mapitemtype._meta.verbose_name, mapitem.title)
                    return render(request, 'editor/mapitem_success.html', {
                        'data': signing.dumps({
                            'type': 'editor.edit',
                            'action': 'delete',
                            'package_name': mapitem.package.name,
                            'commit_id': mapitem.package.commit_id,
                            'commit_msg': commit_msg,
                            'file_path': mapitem.get_filename(),
                        })
                    })

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
            commit_type = 'Created' if mapitem is None else 'Updated'
            action = 'create' if mapitem is None else 'edit'
            mapitem = form.instance

            if form.titles is not None:
                mapitem.titles = {}
                for language, title in form.titles.items():
                    if title:
                        mapitem.titles[language] = title

            if not settings.DIRECT_EDITING:
                content = json_encode(mapitem.tofile())
                with translation.override('en'):
                    commit_msg = '%s %s: %s' % (commit_type, mapitemtype._meta.verbose_name, mapitem.title)
                return render(request, 'editor/mapitem_success.html', {
                    'data': signing.dumps({
                        'type': 'editor.edit',
                        'action': action,
                        'package_name': mapitem.package.name,
                        'commit_id': mapitem.package.commit_id,
                        'commit_msg': commit_msg,
                        'file_path': mapitem.get_filename(),
                        'content': content,
                    })
                })

            mapitem.save()

            return render(request, 'editor/mapitem_success.html', {
                'mapitem_type': mapitem_type
            })
    else:
        form = mapitemtype.EditorForm(instance=mapitem, request=request)

    return render(request, 'editor/mapitem.html', {
        'form': form,
        'mapitem_type': mapitem_type,
        'has_geometry': hasattr(mapitemtype, 'geometry'),
        'name': orig_name,
        'geomtype': getattr(mapitemtype, 'geomtype', None),
        'path': request.path,
        'new': new
    })


def finalize(request):
    if request.method != 'POST':
        return render(request, 'editor/finalize_redirect.html', {})

    if 'data' not in request.POST:
        raise SuspiciousOperation('Missing data.')
    raw_data = request.POST['data']

    try:
        data = signing.loads(raw_data)
    except BadSignature:
        raise SuspiciousOperation('Bad Signature.')

    if data['type'] != 'editor.edit':
        raise SuspiciousOperation('Wrong data type.')

    package = Package.objects.filter(name=data['package_name']).first()
    hoster = None
    if package is not None:
        hoster = get_hoster_for_package(package)

    hoster.check_state(request)

    return render(request, 'editor/finalize.html', {
        'hoster': hoster,
        'data': raw_data,
        'action': data['action'],
        'commit_id': data['commit_id'],
        'commit_msg': data['commit_msg'],
        'package_name': data['package_name'],
        'file_path': data['file_path'],
        'file_contents': data.get('content')
    })


def oauth_callback(request, hoster):
    hoster = hosters.get(hoster)
    if hoster is None:
        raise Http404

    hoster.handle_callback_request(request)

    return render(request, 'editor/finalize_redirect.html', {})
