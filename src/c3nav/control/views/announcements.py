from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render, get_object_or_404

from c3nav.control.forms import AnnouncementForm
from c3nav.control.views import control_panel_view
from c3nav.site.models import Announcement


@login_required(login_url='site.login')
@control_panel_view
def announcement_list(request):
    if not request.user_permissions.manage_announcements:
        raise PermissionDenied

    announcements = Announcement.objects.order_by('-created')

    if request.method == 'POST':
        form = AnnouncementForm(data=request.POST)
        if form.is_valid():
            announcement = form.instance
            announcement.author = request.user
            announcement.save()
            return redirect('control.announcements')
    else:
        form = AnnouncementForm()

    return render(request, 'control/announcements.html', {
        'form': form,
        'announcements': announcements,
    })


@login_required(login_url='site.login')
@control_panel_view
def announcement_detail(request, announcement):
    if not request.user_permissions.manage_announcements:
        raise PermissionDenied

    announcement = get_object_or_404(Announcement, pk=announcement)

    if request.method == 'POST':
        form = AnnouncementForm(instance=announcement, data=request.POST)
        if form.is_valid():
            form.save()
            return redirect('control.announcements')
    else:
        form = AnnouncementForm(instance=announcement)

    return render(request, 'control/announcement.html', {
        'form': form,
        'announcement': announcement,
    })
