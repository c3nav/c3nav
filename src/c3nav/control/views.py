import string
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.translation import ugettext_lazy as _

from c3nav.control.forms import AccessPermissionForm, AnnouncementForm, UserPermissionsForm
from c3nav.control.models import UserPermissions
from c3nav.mapdata.models.access import AccessPermission, AccessPermissionToken
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
                return redirect(request.path_info)

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
        permissions = UserPermissions(user=user)
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
    if request.method == 'POST' and request.POST.get('submit_access_permissions'):
        form = AccessPermissionForm(request=request, data=request.POST)
        if form.is_valid():
            form.get_token().redeem(user)
            messages.success(request, _('Access permissions successfully granted.'))
            return redirect(request.path_info)
    else:
        form = AccessPermissionForm(request=request)

    ctx.update({
        'access_permission_form': form
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
            announcement = request.user
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
