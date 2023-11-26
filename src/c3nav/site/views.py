import json
from itertools import chain
from typing import Optional

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist, SuspiciousOperation
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.middleware import csrf
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import etag

from c3nav.control.forms import AccessPermissionForm, SignedPermissionDataError
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models import Location, Source
from c3nav.mapdata.models.access import AccessPermissionToken
from c3nav.mapdata.models.locations import LocationRedirect, Position, SpecificLocation, get_position_secret
from c3nav.mapdata.models.report import Report, ReportUpdate
from c3nav.mapdata.utils.locations import (get_location_by_id_for_request, get_location_by_slug_for_request,
                                           levels_by_short_label_for_request)
from c3nav.mapdata.utils.user import can_access_editor, get_user_data
from c3nav.mapdata.views import set_tile_access_cookie
from c3nav.routing.models import RouteOptions
from c3nav.site.forms import PositionForm, PositionSetForm, ReportUpdateForm
from c3nav.site.models import Announcement, SiteUpdate


def check_location(location: Optional[str], request) -> Optional[SpecificLocation]:
    if location is None:
        return None

    location = get_location_by_slug_for_request(location, request)
    if location is None:
        return None

    if isinstance(location, LocationRedirect):
        location: Location = location.target
    if location is None:
        return None

    if not location.can_search:
        location = None

    return location


def map_index(request, mode=None, slug=None, slug2=None, details=None, options=None, nearby=None, pos=None, embed=None):

    # check for access token
    access_signed_data = request.GET.get('access')
    if access_signed_data:
        try:
            token = AccessPermissionForm.load_signed_data(access_signed_data)
        except SignedPermissionDataError as e:
            return HttpResponse(str(e).encode(), content_type='text/plain', status=400)

        num_restrictions = len(token.restrictions)
        with transaction.atomic():
            token.save()

            if not request.user.is_authenticated:
                messages.info(request, _('You need to log in to unlock areas.'))
                request.session['redeem_token_on_login'] = str(token.token)
                token.redeem()
                return redirect_to_login(request.path_info, 'site.login')

            token.redeem(request.user)
            token.save()

        messages.success(request, ngettext_lazy('Area successfully unlocked.',
                                                'Areas successfully unlocked.', num_restrictions))
        return redirect('site.index')

    origin = None
    destination = None
    routing = False
    if slug2 is not None:
        routing = True
        origin = check_location(slug, request)
        destination = check_location(slug2, request)
    else:
        routing = (mode and mode != 'l')
        if mode == 'o':
            origin = check_location(slug, request)
        else:
            destination = check_location(slug, request)

    state = {
        'routing': routing,
        'origin': (origin.serialize(detailed=False, simple_geometry=True, geometry=False)
                   if origin else None),
        'destination': (destination.serialize(detailed=False, simple_geometry=True, geometry=False)
                        if destination else None),
        'sidebar': routing or destination is not None,
        'details': True if details else False,
        'options': True if options else False,
        'nearby': True if nearby else False,
    }

    levels = levels_by_short_label_for_request(request)

    level = levels.get(pos.level, None) if pos else None
    if level is not None:
        state.update({
            'level': level.pk,
            'center': (pos.x, pos.y),
            'zoom': pos.zoom,
        })

    initial_bounds = settings.INITIAL_BOUNDS
    if not initial_bounds:
        initial_bounds = tuple(chain(*Source.max_bounds()))

    ctx = {
        'bounds': json.dumps(Source.max_bounds(), separators=(',', ':')),
        'levels': json.dumps(tuple((level.pk, level.short_label) for level in levels.values()), separators=(',', ':')),
        'state': json.dumps(state, separators=(',', ':'), cls=DjangoJSONEncoder),
        'tile_cache_server': settings.TILE_CACHE_SERVER,
        'initial_level': settings.INITIAL_LEVEL,
        'primary_color': settings.PRIMARY_COLOR,
        'initial_bounds': json.dumps(initial_bounds, separators=(',', ':')) if initial_bounds else None,
        'last_site_update': json.dumps(SiteUpdate.last_update()),
        'ssids': json.dumps(settings.WIFI_SSIDS, separators=(',', ':')) if settings.WIFI_SSIDS else None,
        'random_location_groups': (
            ','.join(str(i) for i in settings.RANDOM_LOCATION_GROUPS) if settings.RANDOM_LOCATION_GROUPS else None
        ),
        'editor': can_access_editor(request),
        'embed': bool(embed),
    }

    if grid.enabled:
        ctx['grid'] = json.dumps({
            'rows': grid.rows,
            'cols': grid.cols,
            'invert_x': grid.invert_x,
            'invert_y': grid.invert_y,
        }, separators=(',', ':'), cls=DjangoJSONEncoder)

    csrf.get_token(request)

    if not embed:
        announcement = Announcement.get_current()
        if announcement:
            messages.info(request, announcement.text)

    response = render(request, 'site/map.html', ctx)
    set_tile_access_cookie(request, response)
    if embed:
        xframe_options_exempt(lambda: response)()
    return response


def qr_code_etag(request, path):
    return '1'


@etag(qr_code_etag)
@cache_control(max_age=3600)
def qr_code(request, path):
    data = (request.build_absolute_uri('/'+path) +
            ('?'+request.META['QUERY_STRING'] if request.META['QUERY_STRING'] else ''))
    if len(data) > 256:
        return HttpResponseBadRequest()

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    response = HttpResponse(content_type='image/png')
    qr.make_image().save(response, 'PNG')
    return response


def close_response(request):
    # todo: use a better way to recognize this
    ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'ajax' in request.GET
    if ajax:
        return HttpResponse(json.dumps(get_user_data(request), cls=DjangoJSONEncoder).encode(),
                            content_type='text/plain')
    redirect_path = request.GET['next'] if request.GET.get('next', '').startswith('/') else reverse('site.index')
    return redirect(redirect_path)


def redeem_token_after_login(request):
    token = request.session.pop('redeem_token_on_login', None)
    if not token:
        return

    try:
        token = AccessPermissionToken.objects.get(token=token)
    except AccessPermissionToken.DoesNotExist:
        return

    try:
        token.redeem(request.user)
    except AccessPermissionToken.RedeemError:
        messages.error(request, _('Areas could not be unlocked because the token has expired.'))
        return

    messages.success(request, token.redeem_success_message)


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return close_response(request)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.user_cache)
            redeem_token_after_login(request)
            return close_response(request)
    else:
        form = AuthenticationForm(request)

    ctx = {
        'title': _('Log in'),
        'form': form,
    }

    if settings.USER_REGISTRATION:
        ctx.update({
            'bottom_link_url': reverse('site.register'),
            'bottom_link_text': _('Create new account')
        })

    return render(request, 'site/account_form.html', ctx)


@never_cache
def logout_view(request):
    logout(request)
    return close_response(request)


@never_cache
def register_view(request):
    if not settings.USER_REGISTRATION:
        return HttpResponse(_('account creation is currently disabled.'), content_type='text/plain', status=403)

    if request.user.is_authenticated:
        return close_response(request)

    if request.method == 'POST':
        form = UserCreationForm(data=request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            redeem_token_after_login(request)
            return close_response(request)
    else:
        form = UserCreationForm()

    form.fields['username'].max_length = 20
    for field in form.fields.values():
        field.help_text = None

    return render(request, 'site/account_form.html', {
        'title': _('Create new account'),
        'back_url': reverse('site.login'),
        'form': form
    })


@never_cache
@login_required(login_url='site.login')
def change_password_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            login(request, request.user)
            messages.success(request, _('Password successfully changed.'))
            return redirect('site.account')
    else:
        form = PasswordChangeForm(user=request.user)

    for field in form.fields.values():
        field.help_text = None

    return render(request, 'site/account_form.html', {
        'title': _('Change password'),
        'back_url': reverse('site.account'),
        'form': form
    })


@never_cache
@login_required(login_url='site.login')
def account_view(request):
    return render(request, 'site/account.html', {
        'user_has_reports': Report.user_has_reports(request.user),
    })


@never_cache
def access_redeem_view(request, token):
    with transaction.atomic():
        try:
            token = AccessPermissionToken.objects.select_for_update().get(token=token, redeemed=False,
                                                                          valid_until__gte=timezone.now())
        except AccessPermissionToken.DoesNotExist:
            messages.error(request, _('This token does not exist or was already redeemed.'))
            return redirect('site.index')

        num_restrictions = len(token.restrictions)

        if request.method == 'POST':
            if not request.user.is_authenticated:
                messages.info(request, _('You need to log in to unlock areas.'))
                request.session['redeem_token_on_login'] = str(token.token)
                token.redeem()
                return redirect('site.login')

            token.redeem(request.user)
            token.save()

            messages.success(request, ngettext_lazy('Area successfully unlocked.',
                                                    'Areas successfully unlocked.', num_restrictions))
            return redirect('site.index')

    return render(request, 'site/confirm.html', {
        'title': ngettext_lazy('Unlock area', 'Unlock areas', num_restrictions),
        'texts': (ngettext_lazy('You have been invited to unlock the following area:',
                                'You have been invited to unlock the following areas:',
                                num_restrictions),
                  ', '.join(str(restriction.title) for restriction in token.restrictions)),
    })


def choose_language(request):
    return render(request, 'site/language.html', {})


@never_cache
def about_view(request):
    return render(request, 'site/about.html', {
        'ajax': request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'ajax' in request.GET,
        'address': settings.IMPRINT_ADDRESS,
        'patrons': settings.IMPRINT_PATRONS,
        'team': settings.IMPRINT_TEAM,
        'hosting': settings.IMPRINT_HOSTING,
    })


def get_report_location_for_request(pk, request):
    location = get_location_by_id_for_request(pk, request)
    if location is None:
        raise Http404
    return location


@never_cache
@login_required(login_url='site.login')
def report_create(request, coordinates=None, location=None, origin=None, destination=None, options=None):
    report = Report()
    report.request = request

    if coordinates:
        report.category = 'missing-location'
        report.coordinates_id = coordinates
        try:
            report.coordinates
        except ObjectDoesNotExist:
            raise Http404
    elif location:
        report.category = 'location-issue'
        report.location = get_report_location_for_request(location, request)
        if report.location is None:
            raise Http404
        if not isinstance(report.location, SpecificLocation):
            raise Http404
    elif origin:
        report.category = 'route-issue'
        report.origin_id = origin
        report.destination_id = destination
        try:
            # noinspection PyStatementEffect
            report.origin
            # noinspection PyStatementEffect
            report.destination
        except ObjectDoesNotExist:
            raise Http404
        try:
            options = RouteOptions.unserialize_string(options)
        except Exception:
            raise SuspiciousOperation
        report.options = options.serialize_string()

    if request.method == 'POST':
        form = report.form_cls(instance=report, data=request.POST)
        if form.is_valid():
            report = form.instance
            if request.user.is_authenticated:
                report.author = request.user
            form.save()

            success_messages = [_('Your report was submitted.')]
            success_kwargs = {'pk': report.pk}
            if request.user.is_authenticated:
                success_messages.append(_('You can keep track of it from your user dashboard.'))
            else:
                success_messages.append(_('You can keep track of it by revisiting the public URL mentioned below.'))
                success_kwargs = {'secret': report.secret}
            messages.success(request, ' '.join(str(s) for s in success_messages))
            return redirect(reverse('site.report_detail', kwargs=success_kwargs))
    else:
        form = report.form_cls(instance=report)

    return render(request, 'site/report_create.html', {
        'report': report,
        'options': options,
        'form': form,
    })


@login_required(login_url='site.login')
def report_list(request, filter):
    page = request.GET.get('page', 1)

    queryset = Report.qs_for_request(request).order_by('-created').select_related('author')
    if filter == 'open':
        queryset = queryset.filter(open=True)

    paginator = Paginator(queryset, 20)
    reports = paginator.page(page)

    return render(request, 'site/report_list.html', {
        'filter': filter,
        'reports': reports,
    })


def report_detail(request, pk, secret=None):
    if secret:
        qs = Report.objects.filter(secret=secret)
    else:
        qs = Report.qs_for_request(request)
    report = get_object_or_404(qs, pk=pk)
    report.request = request

    form = report.form_cls(instance=report)

    can_review = report.request_can_review(request)
    if can_review:
        new_update = ReportUpdate(
            report=report,
            author=request.user,
        )
        if request.method == 'POST':
            update_form = ReportUpdateForm(request, instance=new_update, data=request.POST)
            if update_form.is_valid():
                update_form.save()
                messages.success(request, _('Report updated.'))
                return redirect(request.path_info)
        else:
            update_form = ReportUpdateForm(request, instance=new_update)
    else:
        update_form = None

    return render(request, 'site/report_detail.html', {
        'report': report,
        'form': form,
        'update_form': update_form,
    })


@login_required(login_url='site.login')
def position_list(request):
    return render(request, 'site/position_list.html', {
        'positions': Position.objects.filter(owner=request.user),
        'user_data_json': json.dumps(get_user_data(request), cls=DjangoJSONEncoder),
    })


@login_required(login_url='site.login')
def position_create(request):
    if Position.objects.filter(owner=request.user).count() >= 20:
        messages.error(request, _('You can\'t create more than 20 positions.'))

    position = Position()
    position.owner = request.user

    if request.method == 'POST':
        form = PositionForm(instance=position, data=request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Position created.'))
            return redirect(reverse('site.position_detail', kwargs={'pk': position.pk}))
    else:
        form = PositionForm(instance=position)

    return render(request, 'site/position_create.html', {
        'form': form,
    })


@login_required(login_url='site.login')
def position_detail(request, pk):
    position = get_object_or_404(Position.objects.filter(owner=request.user), pk=pk)
    position.request = request

    if request.method == 'POST':
        with transaction.atomic():
            if request.POST.get('delete', None):
                position.delete()
                messages.success(request, _('Position deleted.'))
                return redirect(reverse('site.position_list'))

            if request.POST.get('set_null', None):
                position.last_coordinates_update = timezone.now()
                position.coordinates = None

            if request.POST.get('reset_secret', None):
                position.secret = get_position_secret()

            form = PositionForm(instance=position, data=request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, _('Position updated.'))
                return redirect(reverse('site.position_detail', kwargs={'pk': position.pk}))
    else:
        form = PositionForm(instance=position)

    return render(request, 'site/position_detail.html', {
        'position': position,
        'form': form,
    })


@login_required(login_url='site.login')
def position_set(request, coordinates):
    coordinates = get_location_by_id_for_request(coordinates, request)
    if coordinates is None:
        raise Http404

    if request.method == 'POST':
        form = PositionSetForm(request, data=request.POST)
        if form.is_valid():
            position = form.cleaned_data['position']
            position.last_coordinates_update = timezone.now()
            position.coordinates = coordinates
            position.save()
            messages.success(request, _('Position set.'))
            return redirect(reverse('site.position_detail', kwargs={'pk': position.pk}))
    else:
        form = PositionSetForm(request)

    return render(request, 'site/position_set.html', {
        'coordinates': coordinates,
        'form': form,
    })
