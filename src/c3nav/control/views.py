import json

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render

from ..mapdata.models import Level, Package, Source


@staff_member_required
def dashboard(request):
    return render(request, 'control/dashboard.html')


@staff_member_required
def editor(request, level=None):
    if not level:
        return redirect('control.editor', level=Level.objects.first().name)

    level = get_object_or_404(Level, name=level)
    return render(request, 'control/editor.html', {
        'bounds': json.dumps(Source.max_bounds()),
        'sources': [p.sources.all().order_by('name') for p in Package.objects.all()],
        'levels': Level.objects.all(),
        'current_level': level,
    })
