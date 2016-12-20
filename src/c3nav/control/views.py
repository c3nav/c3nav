from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from c3nav.control.models import AccessUser
from c3nav.editor.hosters import get_hoster_for_package
from c3nav.mapdata.permissions import get_nonpublic_packages


@login_required(login_url='/control/login/')
def dashboard(request):
    return render(request, 'control/dashboard.html')


def prove(request):
    hosters = OrderedDict((package, get_hoster_for_package(package)) for package in get_nonpublic_packages())

    if not hosters or None in hosters.values():
        return render(request, 'control/prove.html', context={'hosters': None})

    error = None
    if request.method == 'POST':
        user_id = None
        for package, hoster in hosters.items():
            access_token = request.POST.get(package.name)
            hoster_user_id = hoster.get_user_id_with_access_token(access_token)
            if hoster_user_id is None:
                return render(request, 'control/prove.html', context={
                    'hosters': hosters,
                    'error': 'invalid',
                })

            if user_id is None:
                user_id = hoster_user_id

        user = AccessUser.objects.filter(user_url=user_id).first()
        if user is not None:
            if user.tokens.count():
                return render(request, 'control/prove.html', context={
                    'hosters': hosters,
                    'error': 'duplicate',
                })
        else:
            user = AccessUser.objects.create(user_url=user_id)
        token = user.tokens.create(permissions=':all', description='automatically created')
        token_instance = token.new_instance()

        return render(request, 'control/prove.html', context={
            'hosters': hosters,
            'success': True,
            'token': token_instance,
        })

    return render(request, 'control/prove.html', context={
        'hosters': hosters,
        'error': error,
    })
