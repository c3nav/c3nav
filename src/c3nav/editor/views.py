from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http.response import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from c3nav.editor.forms import CommitForm, FeatureForm
from c3nav.editor.hosters import get_hoster_for_package, hosters
from c3nav.mapdata.models.feature import FEATURE_TYPES, Feature
from c3nav.mapdata.models.package import Package
from c3nav.mapdata.packageio.write import json_encode
from c3nav.mapdata.permissions import can_access_package


def edit_feature(request, feature_type=None, name=None):
    if name is not None:
        # Edit existing feature
        feature = get_object_or_404(Feature, name=name)
        if not can_access_package(request, feature.package):
            raise PermissionDenied
        feature_type = FEATURE_TYPES.get(feature.feature_type)
    else:
        # Create new feature
        feature = None
        feature_type = FEATURE_TYPES.get(feature_type)
        if feature_type is None:
            raise Http404()

    if request.method == 'POST':
        if feature is not None and request.POST.get('delete') == '1':
            # Delete this feature!
            if request.POST.get('delete_confirm') == '1':
                if not settings.DIRECT_EDITING:
                    title_en = feature.titles.get('en', next(iter(feature.titles.values())))
                    commit_msg = 'Deleted %s: %s' % (feature_type.title_en.lower(), title_en)
                    return render(request, 'editor/feature_success.html', {
                        'data': signing.dumps({
                            'type': 'editor.edit',
                            'action': 'delete',
                            'package_name': feature.package.name,
                            'commit_id': feature.package.commit_id,
                            'commit_msg': commit_msg,
                            'file_path': feature.tofilename(),
                        })
                    })

                feature.delete()
                return render(request, 'editor/feature_success.html', {})

            return render(request, 'editor/feature_delete.html', {
                'name': feature.name,
                'feature_type': feature_type,
                'path': request.path
            })

        form = FeatureForm(instance=feature, data=request.POST, feature_type=feature_type, request=request)
        if form.is_valid():
            # Update/create feature
            commit_type = 'Created' if feature is None else 'Updated'
            action = 'create' if feature is None else 'edit'
            feature = form.instance
            feature.feature_type = feature_type.name
            feature.titles = {}
            for language, title in form.titles.items():
                if title:
                    feature.titles[language] = title

            if not settings.DIRECT_EDITING:
                content = json_encode(feature.tofile())
                title_en = feature.titles.get('en', next(iter(feature.titles.values())))
                commit_msg = '%s %s: %s' % (commit_type, feature_type.title_en.lower(), title_en)
                return render(request, 'editor/feature_success.html', {
                    'data': signing.dumps({
                        'type': 'editor.edit',
                        'action': action,
                        'package_name': feature.package.name,
                        'commit_id': feature.package.commit_id,
                        'commit_msg': commit_msg,
                        'file_path': feature.tofilename(),
                        'content': content,
                    })
                })

            feature.save()

            return render(request, 'editor/feature_success.html', {})
    else:
        form = FeatureForm(instance=feature, feature_type=feature_type, request=request)

    return render(request, 'editor/feature.html', {
        'form': form,
        'feature_type': feature_type,
        'path': request.path,
        'new': feature is None
    })


@require_POST
def finalize(request):
    if 'data' not in request.POST:
        raise SuspiciousOperation('Missing data.')
    raw_data = request.POST['data']
    data = signing.loads(raw_data)

    if data['type'] != 'editor.edit':
        raise SuspiciousOperation('Wrong data type.')

    package = Package.objects.filter(name=data['package_name']).first()
    hoster = None
    if package is not None:
        hoster = get_hoster_for_package(package)

    action = request.POST.get('action')
    if action == 'check':
        hoster.check_state(request)
    elif action == 'oauth':
        hoster.set_tmp_data(request, raw_data)
        return redirect(hoster.get_auth_uri(request))

    hoster_state = hoster.get_state(request)
    hoster_error = hoster.get_error(request) if hoster_state == 'logged_out' else None

    if request.method == 'POST' and 'commit_msg' in request.POST:
        form = CommitForm(request.POST)
        if form.is_valid() and hoster_state == 'logged_in':
            pass
    else:
        form = CommitForm({'commit_msg': data['commit_msg']})

    return render(request, 'editor/finalize.html', {
        'data': raw_data,
        'action': data['action'],
        'commit_id': data['commit_id'],
        'commit_form': form,
        'package_name': data['package_name'],
        'hoster': hoster,
        'hoster_state': hoster_state,
        'hoster_error': hoster_error,
        'file_path': data['file_path'],
        'file_contents': data.get('content')
    })


def oauth_callback(request, hoster):
    hoster = hosters.get(hoster)
    if hoster is None:
        raise Http404

    data = hoster.get_tmp_data(request)
    hoster.handle_callback_request(request)

    return render(request, 'editor/oauth_callback.html', {'data': data})
