from django.conf import settings
from django.db import transaction
from django.http.response import Http404
from django.shortcuts import render

from c3nav.editor.forms import FeatureForm
from c3nav.mapdata.models.feature import FEATURE_TYPES


def add_feature(request, feature_type):
    feature_type = FEATURE_TYPES.get(feature_type)
    if feature_type is None:
        raise Http404()

    if request.method == 'POST':
        form = FeatureForm(request.POST, feature_type=feature_type)
        if form.is_valid():
            if not settings.DIRECT_EDITING:
                return render(request, 'editor/feature_success.html', {})

            with transaction.atomic():
                feature = form.instance
                feature.feature_type = feature_type.name
                feature.titles = {}
                for language, title in form.titles.items():
                    if title:
                        feature.titles[language] = title
                feature.save()

            return render(request, 'editor/feature_success.html', {})
    else:
        form = FeatureForm(feature_type=feature_type)

    return render(request, 'editor/feature.html', {
        'form': form,
        'feature_type': feature_type,
        'path': request.path,
        'new': True
    })
