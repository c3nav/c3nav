from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from c3nav.access.apply import get_nonpublic_packages
from c3nav.access.forms import AccessTokenForm
from c3nav.access.models import AccessToken, AccessUser
from c3nav.editor.hosters import get_hoster_for_package


@login_required(login_url='/access/login/')
def dashboard(request):
    return redirect('access.users')


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

        token = user.new_token(permissions=':full', description='automatically created')
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


@login_required(login_url='/access/login/')
def user_list(request, page=1):
    queryset = AccessUser.objects.all()
    paginator = Paginator(queryset, 25)

    try:
        users = paginator.page(page)
    except PageNotAnInteger:
        return redirect('access.users')
    except EmptyPage:
        return redirect('access.users')

    return render(request, 'access/users.html', {
        'users': users,
    })


@login_required(login_url='/access/login/')
def user_detail(request, pk):
    user = get_object_or_404(AccessUser, id=pk)

    tokens = user.tokens.order_by('-creation_date')

    if request.method == 'POST':
        if 'expire' in request.POST:
            token = get_object_or_404(AccessToken, user=user, id=request.POST['expire'])
            token.expired = True
            token.save()
            return redirect('access.user', pk=user.id)

        new_token_form = AccessTokenForm(data=request.POST, request=request)
        if new_token_form.is_valid():
            token = new_token_form.instance
            token.user = user
            token.secret = AccessToken.create_secret()

            author = None
            try:
                author = request.user.operator
            except:
                pass

            token.author = author
            token.save()

            return redirect('access.user.token', user=user.id, token=token.id)
    else:
        new_token_form = AccessTokenForm(request=request)

    return render(request, 'access/user.html', {
        'user': user,
        'new_token_form': new_token_form,
        'tokens': tokens,
    })


@login_required(login_url='/access/login/')
def show_user_token(request, user, token):
    user = get_object_or_404(AccessUser, id=user)
    token = get_object_or_404(AccessToken, user=user, id=token, activated=False)

    return render(request, 'access/user_token.html', {
        'user': user,
        'tokens': token,
    })
