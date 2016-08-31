import json
import mimetypes
import os

from django.conf import settings
from django.core.files import File
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from ..mapdata.models import Level, Package, Source


def index(request):
    return render(request, 'editor/map.html', {
        'bounds': json.dumps(Source.max_bounds()),
        'sources': [p.sources.all().order_by('name') for p in Package.objects.all()],
        'levels': Level.objects.order_by('altitude'),
    })


def source(request, source):
    source = get_object_or_404(Source, name=source)
    response = HttpResponse(content_type=mimetypes.guess_type(source.name)[0])
    image_path = os.path.join(settings.MAP_ROOT, source.package.directory, 'sources', source.name)
    for chunk in File(open(image_path, 'rb')).chunks():
        response.write(chunk)
    return response
