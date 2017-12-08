from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render


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
