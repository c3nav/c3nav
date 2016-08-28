import json

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render

from ..mapdata.models import MapLevel, MapPackage, MapSource


@staff_member_required
def dashboard(request):
    return render(request, 'control/dashboard.html')


@staff_member_required
def editor(request, level=None):
    if not level:
        return redirect('control.editor', level=MapLevel.objects.first().name)

    level = get_object_or_404(MapLevel, name=level)
    return render(request, 'control/editor.html', {
        'bounds': json.dumps(MapSource.max_bounds()),
        'packages': MapPackage.objects.all(),
        'levels': MapLevel.objects.all(),
        'current_level': level,
    })
