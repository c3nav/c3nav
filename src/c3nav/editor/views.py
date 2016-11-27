from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.core.signing import BadSignature
from django.http.response import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import translation

from c3nav.editor.hosters import get_hoster_for_package, hosters
from c3nav.mapdata.models import GEOMETRY_MAPITEM_TYPES
from c3nav.mapdata.models.package import Package
from c3nav.mapdata.packageio.write import json_encode
from c3nav.mapdata.permissions import can_access_package


def edit_feature(request, feature_type, name=None):
    model = GEOMETRY_MAPITEM_TYPES.get(feature_type)
    if model is None:
        raise Http404()

    feature = None
    if name is not None:
        # Edit existing feature
        feature = get_object_or_404(model, name=name)
        if not can_access_package(request, feature.package):
            raise PermissionDenied

    if request.method == 'POST':
        if feature is not None and request.POST.get('delete') == '1':
            # Delete this feature!
            if request.POST.get('delete_confirm') == '1':
                if not settings.DIRECT_EDITING:
                    with translation.override('en'):
                        commit_msg = 'Deleted %s: %s' % (model._meta.verbose_name, feature.title)
                    return render(request, 'editor/feature_success.html', {
                        'data': signing.dumps({
                            'type': 'editor.edit',
                            'action': 'delete',
                            'package_name': feature.package.name,
                            'commit_id': feature.package.commit_id,
                            'commit_msg': commit_msg,
                            'file_path': feature.get_filename(),
                        })
                    })

                feature.delete()
                return render(request, 'editor/feature_success.html', {})

            return render(request, 'editor/feature_delete.html', {
                'name': feature.name,
                'feature_type': feature_type,
                'path': request.path
            })

        form = model.EditorForm(instance=feature, data=request.POST, request=request)
        if form.is_valid():
            # Update/create feature
            commit_type = 'Created' if feature is None else 'Updated'
            action = 'create' if feature is None else 'edit'
            feature = form.instance

            if form.titles is not None:
                feature.titles = {}
                for language, title in form.titles.items():
                    if title:
                        feature.titles[language] = title

            if not settings.DIRECT_EDITING:
                content = json_encode(feature.tofile())
                with translation.override('en'):
                    commit_msg = '%s %s: %s' % (commit_type, model._meta.verbose_name, feature.title)
                return render(request, 'editor/feature_success.html', {
                    'data': signing.dumps({
                        'type': 'editor.edit',
                        'action': action,
                        'package_name': feature.package.name,
                        'commit_id': feature.package.commit_id,
                        'commit_msg': commit_msg,
                        'file_path': feature.get_filename(),
                        'content': content,
                    })
                })

            feature.save()

            return render(request, 'editor/feature_success.html', {})
    else:
        form = model.EditorForm(instance=feature, request=request)

    return render(request, 'editor/feature.html', {
        'form': form,
        'feature_type': feature_type,
        'path': request.path,
        'new': feature is None
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
