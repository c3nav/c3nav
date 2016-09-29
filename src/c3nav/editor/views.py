from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http.response import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.http import require_POST

from c3nav.editor.forms import FeatureForm
from c3nav.editor.hosters import get_hoster_for_package, hosters
from c3nav.mapdata.models.feature import FEATURE_TYPES, Feature
from c3nav.mapdata.models.package import Package
from c3nav.mapdata.packageio.write import json_encode
from c3nav.mapdata.permissions import can_access_package


def add_feature(request, feature_type):
    feature_type = FEATURE_TYPES.get(feature_type)
    if feature_type is None:
        raise Http404()

    if request.method == 'POST':
        form = FeatureForm(request.POST, feature_type=feature_type, request=request)
        if form.is_valid():
            feature = form.instance
            feature.feature_type = feature_type.name
            feature.titles = {}
            for language, title in form.titles.items():
                if title:
                    feature.titles[language] = title

            if not settings.DIRECT_EDITING:
                return render(request, 'editor/feature_success.html', {
                    'data': signing.dumps((feature.package.name, feature.tofilename(), json_encode(feature.tofile())))
                })

            feature.save()

            return render(request, 'editor/feature_success.html', {})
    else:
        form = FeatureForm(feature_type=feature_type, request=request)

    return render(request, 'editor/feature.html', {
        'form': form,
        'feature_type': feature_type,
        'path': request.path,
        'new': True
    })


def edit_feature(request, name):
    feature = get_object_or_404(Feature, name=name)
    if not can_access_package(request, feature.package):
        raise PermissionDenied
    feature_type = FEATURE_TYPES.get(feature.feature_type)

    if request.method == 'POST':
        if request.POST.get('delete') == '1':
            if request.POST.get('delete_confirm') == '1':
                if not settings.DIRECT_EDITING:
                    return render(request, 'editor/feature_success.html', {
                        'data': signing.dumps((feature.package.name, feature.tofilename(), None))
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
            feature = form.instance
            feature.feature_type = feature_type.name
            feature.titles = {}
            for language, title in form.titles.items():
                if title:
                    feature.titles[language] = title

            if not settings.DIRECT_EDITING:
                return render(request, 'editor/feature_success.html', {
                    'data': signing.dumps((feature.package.name, feature.tofilename(), json_encode(feature.tofile())))
                })

            feature.save()

            return render(request, 'editor/feature_success.html', {})
    else:
        form = FeatureForm(instance=feature, feature_type=feature_type, request=request)

    return render(request, 'editor/feature.html', {
        'form': form,
        'feature_type': feature_type,
        'path': request.path,
        'new': False
    })


@require_POST
def finalize(request):
    if 'data' not in request.POST:
        return render(request, 'editor/error.html', {
            'title': _('Missing data.'),
            'description': _('Edit data is missing.')
        }, status=400)
    data = request.POST['data']

    package_name, file_path, file_contents = signing.loads(data)

    package = Package.objects.filter(name=package_name).first()
    hoster = None
    if package is not None:
        hoster = get_hoster_for_package(package)

    if request.POST.get('check'):
        hoster.check_state(request)

    hoster_state = hoster.get_state(request)
    hoster_error = hoster.get_error(request) if hoster_state == 'logged_out' else None

    return render(request, 'editor/finalize.html', {
        'data': data,
        'package_name': package_name,
        'hoster': hoster,
        'hoster_state': hoster_state,
        'hoster_error': hoster_error,
        'file_path': file_path,
        'file_contents': file_contents
    })


@require_POST
def finalize_oauth_progress(request):
    pass


@require_POST
def finalize_oauth_redirect(request):
    if 'data' not in request.POST:
        return render(request, 'editor/error.html', {
            'title': _('Missing data.'),
            'description': _('Edit data is missing.')
        }, status=400)
    data = request.POST['data']

    package_name, file_path, file_contents = signing.loads(data)
    package = Package.objects.filter(name=package_name).first()
    hoster = None
    if package is not None:
        hoster = get_hoster_for_package(package)

    hoster.set_tmp_data(request, data)
    return redirect(hoster.get_auth_uri(request))


def finalize_oauth_callback(request, hoster):
    hoster = hosters.get(hoster)
    if hoster is None:
        raise Http404

    data = hoster.get_tmp_data(request)
    hoster.handle_callback_request(request)

    return render(request, 'editor/finalize_oauth_callback.html', {'data': data})
