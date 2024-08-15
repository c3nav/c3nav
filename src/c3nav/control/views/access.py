from contextlib import suppress
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from c3nav.control.forms import AccessPermissionForm
from c3nav.control.views.base import control_panel_view
from c3nav.mapdata.models.access import AccessPermissionToken


@login_required(login_url='site.login')
@control_panel_view
def grant_access(request):  # todo: make class based view
    if request.method == 'POST' and request.POST.get('submit_access_permissions'):
        form = AccessPermissionForm(request=request, data=request.POST)
        if form.is_valid():
            token = form.get_token()
            token.save()
            if settings.DEBUG:
                with suppress(ValueError):
                    signed_data = form.get_signed_data()
                    print('/?'+urlencode({'access': signed_data}))
            return redirect(reverse('control.access.qr', kwargs={'token': token.token}))
    else:
        form = AccessPermissionForm(request=request)

    ctx = {
        'access_permission_form': form,
        'tokens': AccessPermissionToken.objects.filter(author=request.user, unlimited=True),
    }

    return render(request, 'control/access.html', ctx)


@login_required(login_url='site.login')
@control_panel_view
def grant_access_qr(request, token):  # todo: make class based view
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
        'token': token,
        'url': url,
        'url_qr': reverse('site.qr', kwargs={'path': url.removeprefix('/')}),
        'url_absolute': request.build_absolute_uri(url),
    })
