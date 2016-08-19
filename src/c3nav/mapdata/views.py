import mimetypes

from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, HttpResponse
from django.shortcuts import render

from ..mapdata import mapmanager


@staff_member_required
def source(request, filename):
    source = mapmanager.sources_by_filename.get(filename)
    if source is None:
        raise Http404('Source does not exist')

    response = HttpResponse(content_type=mimetypes.guess_type(source.src)[0])
    with open(source.src, 'rb') as f:
        response.write(f.read())
    return response
