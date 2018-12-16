import string
from datetime import datetime
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.timezone import make_aware
from django.utils.translation import ugettext_lazy as _

from c3nav.control.forms import (AccessPermissionForm, AnnouncementForm, MapUpdateFilterForm, MapUpdateForm,
                                 UserPermissionsForm, UserSpaceAccessForm)
from c3nav.control.models import UserPermissions, UserSpaceAccess
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.access import AccessPermission, AccessPermissionToken, AccessRestriction
from c3nav.mapdata.tasks import process_map_updates
from c3nav.site.models import Announcement


def control_panel_view(func):
    @wraps(func)
    def wrapped_func(request, *args, **kwargs):
        if not request.user_permissions.control_panel:
            raise PermissionDenied
        return func(request, *args, **kwargs)
    return login_required(login_url='site.login')(wrapped_func)


@login_required(login_url='site.login')
@control_panel_view
def main_index(request):
    return render(request, 'control/index.html', {})


@login_required(login_url='site.login')
@control_panel_view
def user_list(request):
    search = request.GET.get('s')
    page = request.GET.get('page', 1)

    queryset = User.objects.order_by('id')
    if search:
        queryset = queryset.filter(username__icontains=search.strip())

    paginator = Paginator(queryset, 20)
    users = paginator.page(page)

    return render(request, 'control/users.html', {
        'users': users,
    })


@login_required(login_url='site.login')
@control_panel_view
def user_detail(request, user):
    qs = User.objects.select_related(
        'permissions',
    ).prefetch_related(
        Prefetch('spaceaccesses', UserSpaceAccess.objects.select_related('space')),
        Prefetch('accesspermissions', AccessPermission.objects.select_related('access_restriction', 'author'))
    )
    user = get_object_or_404(qs, pk=user)

    if request.method == 'POST':
        delete_access_permission = request.POST.get('delete_access_permission')
        if delete_access_permission:
            with transaction.atomic():
                try:
                    permission = AccessPermission.objects.select_for_update().get(pk=delete_access_permission)
                except AccessPermission.DoesNotExist:
                    messages.error(request, _('Unknown access permission.'))
                else:
                    if request.user_permissions.grant_all_access or permission.author_id == request.user.pk:
                        permission.delete()
                        messages.success(request, _('Access Permission successfully deleted.'))
                    else:
                        messages.error(request, _('You cannot delete this Access Permission.'))
                return redirect(request.path_info+'?restriction='+str(permission.pk)+'#access')

        api_secret_action = request.POST.get('api_secret')
        if (api_secret_action and (request.user_permissions.grant_permissions or
                                   (request.user == user and user.permissions.api_secret))):

            permissions = user.permissions

            if api_secret_action == 'generate' and permissions.api_secret:
                messages.error(request, _('This user already has an API secret.'))
                return redirect(request.path_info)

            if api_secret_action in ('delete', 'regenerate') and not permissions.api_secret:
                messages.error(request, _('This user does not have an API secret.'))
                return redirect(request.path_info)

            with transaction.atomic():
                if api_secret_action in ('generate', 'regenerate'):
                    api_secret = get_random_string(64, string.ascii_letters+string.digits)
                    permissions.api_secret = api_secret
                    permissions.save()

                    messages.success(request, _('The new API secret is: %s – '
                                                'be sure to note it down now, it won\'t be shown again.') % api_secret)

                elif api_secret_action == 'delete':
                    permissions.api_secret = None
                    permissions.save()

                    messages.success(request, _('API secret successfully deleted!'))

                return redirect(request.path_info)

    ctx = {
        'user': user,
    }

    # user permissions
    try:
        permissions = user.permissions
    except AttributeError:
        permissions = UserPermissions(user=user, initial=True)
    ctx.update({
        'user_permissions': tuple(
            field.verbose_name for field in UserPermissions._meta.get_fields()
            if not field.one_to_one and getattr(permissions, field.attname)
        )
    })
    if request.user_permissions.grant_permissions:
        if request.method == 'POST' and request.POST.get('submit_user_permissions'):
            form = UserPermissionsForm(instance=permissions, data=request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, _('General permissions successfully updated.'))
                return redirect(request.path_info)
        else:
            form = UserPermissionsForm(instance=permissions)
        ctx.update({
            'user_permissions_form': form
        })

    # access permissions
    now = timezone.now()
    restriction = request.GET.get('restriction')
    if restriction and restriction.isdigit():
        restriction = get_object_or_404(AccessRestriction, pk=restriction)
        permissions = user.accesspermissions.filter(access_restriction=restriction).order_by('expire_date')
        for permission in permissions:
            permission.expired = permission.expire_date and permission.expire_date >= now
        ctx.update({
            'access_restriction': restriction,
            'access_permissions': user.accesspermissions.filter(
                access_restriction=restriction
            ).order_by('expire_date')
        })
    else:
        if request.method == 'POST' and request.POST.get('submit_access_permissions'):
            form = AccessPermissionForm(request=request, data=request.POST)
            if form.is_valid():
                form.get_token().redeem(user)
                messages.success(request, _('Access permissions successfully granted.'))
                return redirect(request.path_info)
        else:
            form = AccessPermissionForm(request=request)

        access_permissions = {}
        for permission in user.accesspermissions.all():
            access_permissions.setdefault(permission.access_restriction_id, []).append(permission)
        access_permissions = tuple(
            {
                'pk': pk,
                'title': permissions[0].access_restriction.title,
                'can_grant': any(item.can_grant for item in permissions),
                'expire_date': set(item.expire_date for item in permissions),
            } for pk, permissions in access_permissions.items()
        )
        for permission in access_permissions:
            permission['expire_date'] = None if None in permission['expire_date'] else max(permission['expire_date'])
            permission['expired'] = permission['expire_date'] and permission['expire_date'] >= now
        access_permissions = tuple(sorted(
            access_permissions,
            key=lambda permission: (1, 0) if permission['expire_date'] is None else (0, permission['expire_date']),
            reverse=True
        ))
        ctx.update({
            'access_permissions': access_permissions,
            'access_permission_form': form
        })

        # space access
        form = None
        if request.user_permissions.grant_space_access:
            if request.method == 'POST' and request.POST.get('submit_space_access'):
                form = UserSpaceAccessForm(request=request, data=request.POST)
                if form.is_valid():
                    instance = form.instance
                    instance.user = user
                    try:
                        instance.save()
                    except IntegrityError:
                        messages.error(request, _('User space access could not be granted because it already exists.'))
                    else:
                        messages.success(request, _('User space access successfully granted.'))
                    return redirect(request.path_info)
            else:
                form = UserSpaceAccessForm(request=request)

        delete_space_access = request.POST.get('delete_space_access')
        if delete_space_access:
            with transaction.atomic():
                try:
                    access = user.spaceaccesses.filter(pk=delete_space_access)
                except AccessPermission.DoesNotExist:
                    messages.error(request, _('Unknown space access.'))
                else:
                    if request.user_permissions.grant_space_access or user.pk == request.user.pk:
                        access.delete()
                        messages.success(request, _('Space access successfully deleted.'))
                    else:
                        messages.error(request, _('You cannot delete this space access.'))
                return redirect(request.path_info)

        space_accesses = None
        if request.user_permissions.grant_space_access or user.pk == request.user.pk:
            space_accesses = user.spaceaccesses.all()

        ctx.update({
            'space_accesses': space_accesses,
            'space_accesses_form': form
        })

    return render(request, 'control/user.html', ctx)


@login_required(login_url='site.login')
@control_panel_view
def grant_access(request):
    if request.method == 'POST' and request.POST.get('submit_access_permissions'):
        form = AccessPermissionForm(request=request, data=request.POST)
        if form.is_valid():
            token = form.get_token()
            token.save()
            if settings.DEBUG and request.user_permissions.api_secret:
                signed_data = form.get_signed_data()
                print('/?'+urlencode({'access': signed_data}))
            return redirect(reverse('control.access.qr', kwargs={'token': token.token}))
    else:
        form = AccessPermissionForm(request=request)

    ctx = {
        'access_permission_form': form
    }

    return render(request, 'control/access.html', ctx)


@login_required(login_url='site.login')
@control_panel_view
def grant_access_qr(request, token):
    with transaction.atomic():
        token = AccessPermissionToken.objects.select_for_update().get(token=token, author=request.user)
        if token.redeemed:
            messages.success(request, _('Access successfully granted.'))
            token = None
        elif request.method == 'POST' and request.POST.get('revoke'):
            token.delete()
            messages.success(request, _('Token successfully revoked.'))
            return redirect('control.access')
        elif not token.unlimited:
            try:
                latest = AccessPermissionToken.objects.filter(author=request.user).latest('valid_until')
            except AccessPermissionToken.DoesNotExist:
                token = None
            else:
                if latest.id != token.id:
                    token = None
            if token is None:
                messages.error(request, _('You can only display your most recently created token.'))

        if token is None:
            return redirect('control.access')

        token.bump()
        token.save()

    url = reverse('site.access.redeem', kwargs={'token': str(token.token)})
    return render(request, 'control/access_qr.html', {
        'url': url,
        'url_qr': reverse('site.qr', kwargs={'path': url}),
        'url_absolute': request.build_absolute_uri(url),
    })


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


@login_required(login_url='site.login')
@control_panel_view
def map_updates(request):
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
                process_map_updates.delay()
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
        if request.GET['processed'] in ('1', '0'):
            queryset = queryset.filter(processed=request.GET['processed'] == '1')
    if request.GET.get('user_id', None):
        if request.GET['user_id'].isdigit():
            queryset = queryset.filter(user_id=request.GET['user_id'])

    paginator = Paginator(queryset, 20)
    users = paginator.page(page)

    last_processed, last_processed_success = cache.get('mapdata:last_process_updates_run', (None, None))
    if last_processed:
        make_aware(datetime.fromtimestamp(last_processed))

    return render(request, 'control/map_updates.html', {
        'last_processed': last_processed,
        'last_processed_success': last_processed_success,
        'auto_process_updates': settings.AUTO_PROCESS_UPDATES,
        'map_update_form': map_update_form,
        'filter_form': filter_form,
        'updates': users,
    })
