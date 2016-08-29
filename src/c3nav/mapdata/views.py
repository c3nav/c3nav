import mimetypes
import os

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files import File
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from .models import Source


@staff_member_required
def source(request, source):
    source = get_object_or_404(Source, name=source)
    response = HttpResponse(content_type=mimetypes.guess_type(source.name)[0])
    image_path = os.path.join(settings.MAP_ROOT, source.package.directory, 'sources', source.name)
    for chunk in File(open(image_path, 'rb')).chunks():
        response.write(chunk)
    return response
