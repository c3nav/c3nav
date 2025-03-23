from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils.timezone import make_aware
from django.utils.translation import gettext_lazy as _

from c3nav.control.forms import MapUpdateFilterForm, MapUpdateForm
from c3nav.control.views.base import control_panel_view
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.update import MapUpdateJob
from c3nav.mapdata.tasks import schedule_available_mapupdate_jobs


@login_required(login_url='site.login')
@control_panel_view
def map_updates(request):  # todo: make class based view
    if not request.user_permissions.manage_map_updates:
        raise PermissionDenied

    page = request.GET.get('page', 1)

    if request.method == 'POST':
        if 'create_map_update' in request.POST:
            map_update_form = MapUpdateForm(data=request.POST)
            if map_update_form.is_valid():
                map_update = map_update_form.instance
                map_update.type = 'control_panel'
                map_update.user = request.user
                map_update.save()
                messages.success(request, _('Map update successfully created.'))
                return redirect(request.path_info)
        elif 'process_updates' in request.POST:
            if settings.HAS_CELERY:
                schedule_available_mapupdate_jobs.delay()
                messages.success(request, _('Map update processing successfully queued.'))
            else:
                messages.error(request, _('Map update processing was not be queued because celery is not configured.'))
            return redirect(request.path_info)

    filter_form = MapUpdateFilterForm(request.GET)
    map_update_form = MapUpdateForm()

    queryset = MapUpdate.objects.order_by('-datetime').select_related('user', 'changeset__author')
    if request.GET.get('type', None):
        queryset = queryset.filter(type=request.GET['type'])
    if request.GET.get('geometries_changed', None):
        if request.GET['geometries_changed'] in ('1', '0'):
            queryset = queryset.filter(geometries_changed=request.GET['geometries_changed'] == '1')
    if request.GET.get('processed', None):
        queryset = queryset.filter(pk__lte=MapUpdateJob.last_successful_update(request.GET['processed'])[0])
    if request.GET.get('user_id', None):
        if request.GET['user_id'].isdigit():
            queryset = queryset.filter(user_id=request.GET['user_id'])

    paginator = Paginator(queryset, 20)
    updates = paginator.page(page)

    last_processed, last_processed_success = cache.get('mapdata:last_process_updates_run', (None, None))
    if last_processed:
        last_processed = make_aware(datetime.fromtimestamp(last_processed))

    last_processed_start = cache.get('mapdata:last_process_updates_start', None)
    if last_processed_start:
        last_processed_start = make_aware(datetime.fromtimestamp(last_processed_start))

    return render(request, 'control/map_updates.html', {
        'last_processed': last_processed,
        'last_processed_start': last_processed_start,
        'last_processed_success': last_processed_success,
        'auto_process_updates': settings.AUTO_PROCESS_UPDATES,
        'map_update_form': map_update_form,
        'filter_form': filter_form,
        'updates': updates,
    })
