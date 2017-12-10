from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import ugettext_lazy as _

from c3nav.control.forms import AccessPermissionForm, UserPermissionsForm
from c3nav.control.models import UserPermissions
from c3nav.mapdata.models.access import AccessPermission


def control_panel_view(func):
    @wraps(func)
    def wrapped_func(request, *args, **kwargs):
        if not request.user_permissions.control_panel:
            raise PermissionDenied
        return func(request, *args, **kwargs)
    return login_required(login_url='site.login')(wrapped_func)


@login_required
@control_panel_view
def main_index(request):
    return render(request, 'control/index.html', {})


@login_required
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


@login_required
@control_panel_view
def user_detail(request, user):
    qs = User.objects.select_related(
        'permissions',
    ).prefetch_related(
        Prefetch('accesspermissions', AccessPermission.objects.select_related('access_restriction'))
    )
    user = get_object_or_404(qs, pk=user)

    if request.method == 'POST':
        delete_access_permission = request.POST.get('delete_access_permission')
        if delete_access_permission:
            try:
                permission = AccessPermission.objects.get(pk=delete_access_permission)
            except AccessPermission.DoesNotExist:
                messages.error(request, _('Unknown access permission.'))
            else:
                permission.delete()
                messages.success(request, _('Access Permission successfully deleted.'))
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
