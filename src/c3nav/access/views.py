import qrcode
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from c3nav.access.forms import AccessTokenForm, AccessUserForm
from c3nav.access.models import AccessToken, AccessUser


@login_required(login_url='/access/login/')
def dashboard(request):
    return redirect('access.users')


def activate_token(request, pk, secret):
    token = get_object_or_404(AccessToken, expired=False, activated=False, id=pk, secret=secret)
    if request.method == 'POST':
        request.c3nav_access = token
        request.c3nav_new_access = True
        return render(request, 'access/activate.html', context={
            'success': True,
        })

    return render(request, 'access/activate.html', context={
        'token': token,
    })


def token_qr(request, pk, secret):
    get_object_or_404(AccessToken, expired=False, activated=False, id=pk, secret=secret)

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(request.build_absolute_uri(reverse('access.activate', kwargs={'pk': pk, 'secret': secret})))
    qr.make(fit=True)

    response = HttpResponse(content_type='image/png')
    qr.make_image().save(response, 'PNG')
    return response


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

    if request.method == 'POST':
        new_user_form = AccessUserForm(data=request.POST)
        if new_user_form.is_valid():
            user = new_user_form.instance
            user.author = request.user
            user.save()

            return redirect('access.user', pk=user.id)
    else:
        new_user_form = AccessUserForm()

    return render(request, 'access/users.html', {
        'users': users,
        'new_user_form': new_user_form,
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

            token.author = request.user
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
    token = get_object_or_404(AccessToken, user=user, id=token)

    return render(request, 'access/user_token.html', {
        'user': user,
        'token': token,
    })
