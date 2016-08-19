from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.shortcuts import redirect, render

from ..mapdata import mapmanager


@staff_member_required
def dashboard(request):
    return render(request, 'control/dashboard.html')


@staff_member_required
def editor(request, level=None):
    if not level:
        return redirect('control.editor', level=mapmanager.levels[0])
    if level not in mapmanager.levels:
        raise Http404('Level does not exist')
    return render(request, 'control/editor.html', {
        'map': mapmanager
    })
