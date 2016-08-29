import mimetypes

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from .models import Source


@staff_member_required
def source(request, source):
    source = get_object_or_404(Source, name=source)
    response = HttpResponse(content_type=mimetypes.guess_type(source.image.name)[0])
    for chunk in source.image.chunks():
        response.write(chunk)
    return response
