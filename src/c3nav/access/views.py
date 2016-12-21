from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, render

from c3nav.access.models import AccessToken, AccessUser
from c3nav.editor.hosters import get_hoster_for_package
from c3nav.mapdata.permissions import get_nonpublic_packages


@login_required(login_url='/access/login/')
def dashboard(request):
    return render(request, 'access/dashboard.html')


def prove(request):
    hosters = OrderedDict((package, get_hoster_for_package(package)) for package in get_nonpublic_packages())

    if not hosters or None in hosters.values():
        return render(request, 'access/prove.html', context={'hosters': None})

    error = None
    if request.method == 'POST':
        user_id = None
        for package, hoster in hosters.items():
            access_token = request.POST.get(package.name)
            hoster_user_id = hoster.get_user_id_with_access_token(access_token)
            if hoster_user_id is None:
                return render(request, 'access/prove.html', context={
                    'hosters': hosters,
                    'error': 'invalid',
                })

            if user_id is None:
                user_id = hoster_user_id

        replaced = False
        with transaction.atomic():
            user = AccessUser.objects.filter(user_url=user_id).first()
            if user is not None:
                valid_tokens = user.valid_tokens
                if valid_tokens.count():
                    if request.POST.get('replace') != '1':
                        return render(request, 'access/prove.html', context={
                            'hosters': hosters,
                            'error': 'duplicate',
                        })

                    for token in valid_tokens:
                        token.expired = True
                        token.save()
                    replaced = True
            else:
                user = AccessUser.objects.create(user_url=user_id)

        token = user.new_token(permissions=':all', description='automatically created')
        return render(request, 'access/prove.html', context={
            'hosters': hosters,
            'success': True,
            'replaced': replaced,
            'token': token,
        })

    return render(request, 'access/prove.html', context={
        'hosters': hosters,
        'error': error,
    })


def activate_token(request, pk, secret):
    token = get_object_or_404(AccessToken, expired=False, activated=False, id=pk, secret=secret)
    request.c3nav_access = token
    request.c3nav_new_access = True
    return render(request, 'access/activate.html', context={
        'success': True,
    })
