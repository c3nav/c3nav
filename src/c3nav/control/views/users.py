from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView

from c3nav.control.forms import AccessPermissionForm, UserPermissionsForm, UserSpaceAccessForm
from c3nav.control.models import UserPermissions, UserSpaceAccess
from c3nav.control.views.base import ControlPanelMixin, control_panel_view
from c3nav.mapdata.models import AccessRestriction
from c3nav.mapdata.models.access import AccessPermission, AccessRestrictionGroup


class UserListView(ControlPanelMixin, ListView):
    model = User
    paginate_by = 20
    template_name = "control/users.html"
    ordering = "id"
    context_object_name = "users"
    user_permission = "view_users"

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.GET.get('s')
        if search:
            qs = qs.filter(username__icontains=search.strip())
        return qs


@login_required(login_url='site.login')
@control_panel_view
def user_detail(request, user):  # todo: make class based view
    if not (request.user_permissions.view_users or user == request.user.pk):
        raise PermissionDenied

    qs = User.objects.select_related(
        'permissions',
    ).prefetch_related(
        Prefetch('spaceaccesses', UserSpaceAccess.objects.select_related('space')),
        Prefetch('accesspermissions', AccessPermission.objects.select_related(
            'access_restriction', 'access_restriction_group', 'author'
        ))
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
    elif restriction and restriction.startswith("g") and restriction[1:].isdigit():
        restriction_group = get_object_or_404(AccessRestrictionGroup, pk=int(restriction[1:]))
        permissions = user.accesspermissions.filter(access_restriction_group=restriction_group).order_by('expire_date')
        for permission in permissions:
            permission.expired = permission.expire_date and permission.expire_date >= now
        ctx.update({
            'access_restriction': restriction_group,
            'access_permissions': user.accesspermissions.filter(
                access_restriction_group=restriction_group
            ).order_by('expire_date')
        })
    else:
        if request.method == 'POST' and request.POST.get('submit_access_permissions'):
            form = AccessPermissionForm(request=request, data=request.POST)
            if form.is_valid():
                token = form.get_token()
                token.save()
                token.redeem(user=user)
                messages.success(request, _('Access permissions successfully granted.'))
                return redirect(request.path_info)
        else:
            form = AccessPermissionForm(request=request)

        access_permissions = {}
        for permission in user.accesspermissions.all():
            access_permissions.setdefault(
                permission.access_restriction_id or ("g%d" % permission.access_restriction_group_id), []
            ).append(permission)
        access_permissions = tuple(
            {
                'pk': pk,
                'title': (
                    permissions[0].access_restriction.title
                    if permissions[0].access_restriction_id
                    else permissions[0].access_restriction_group.title
                ),
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
