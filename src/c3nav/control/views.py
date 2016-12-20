from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from c3nav.editor.hosters import get_hoster_for_package
from c3nav.mapdata.permissions import get_nonpublic_packages


@login_required(login_url='/control/login/')
def dashboard(request):
    return render(request, 'control/dashboard.html')


def prove(request):
    hosters = OrderedDict((package, get_hoster_for_package(package)) for package in get_nonpublic_packages())

    if None in hosters.values():
        return render(request, 'control/prove.html', context={'hosters': None})

    error = False
    success = False
    if request.method == 'POST':
        user_ids = {}
        for package, hoster in hosters.items():
            access_token = request.POST.get(package.name)
            user_id = hoster.get_user_id_with_access_token(access_token)
            if user_id is None:
                error = True
                break
            user_ids[hoster] = user_id

        if not error:
            success = True

    return render(request, 'control/prove.html', context={
        'hosters': hosters,
        'error': error,
        'success': success,
    })
