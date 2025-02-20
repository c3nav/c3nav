import json
from itertools import chain
from typing import Optional
from urllib.parse import urlparse

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, SuspiciousOperation, ValidationError
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest, QueryDict
from django.middleware import csrf
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import etag
from django.views.i18n import LANGUAGE_QUERY_PARAMETER, set_language
from pydantic.type_adapter import TypeAdapter

from c3nav import __version__ as c3nav_version
from c3nav.api.models import Secret
from c3nav.control.forms import AccessPermissionForm, SignedPermissionDataError
from c3nav.mapdata.grid import grid, GridSchema
from c3nav.mapdata.models import Location, Source
from c3nav.mapdata.models.access import AccessPermission, AccessPermissionToken
from c3nav.mapdata.models.locations import LocationGroup, Position, SpecificLocation, get_position_secret
from c3nav.mapdata.models.report import Report, ReportUpdate
from c3nav.mapdata.schemas.locations import SingleLocationItemSchema
from c3nav.mapdata.utils.locations import (levels_by_level_index_for_request, LocationRedirect,
                                           get_location_for_request)
from c3nav.mapdata.utils.user import can_access_editor, get_user_data
from c3nav.mapdata.views import set_tile_access_cookie
from c3nav.routing.models import RouteOptions
from c3nav.site.compliance import add_compliance_checkbox
from c3nav.site.forms import APISecretForm, DeleteAccountForm, PositionForm, PositionSetForm, ReportUpdateForm
from c3nav.site.models import Announcement, SiteUpdate

if settings.METRICS:
    from prometheus_client import Counter


def check_location(location_slug: Optional[str], request) -> Optional[Location]:
    if location_slug is None:
        return None

    location = get_location_for_request(location_slug, request)
    if location is None:
        return None

    if isinstance(location, LocationRedirect):
        return location.target
    if location is None:
        return None

    if not location.can_search:
        location = None

    return location


def map_index(request, mode=None, slug=None, slug2=None, details=None, options=None, nearby=None, pos=None, embed=None):
    # check for access token
    access_token = request.GET.get('access')
    if access_token:
        with transaction.atomic():
            try:
                if ':' in access_token:
                    token = AccessPermissionForm.load_signed_data(access_token)
                else:
                    token = AccessPermissionToken.objects.select_for_update().get(token=access_token, redeemed=False,
                                                                                  valid_until__gte=timezone.now())
            except (AccessPermissionToken.DoesNotExist, ValueError, ValidationError, SignedPermissionDataError):
                messages.error(request, _('This token does not exist or was already redeemed.'))
            else:
                num_restrictions = len(token.restrictions)
                with transaction.atomic():
                    if token.pk:
                        token.save()
                    token.redeem(request=request)
                    if token.pk:
                        token.save()

                if request.user.is_authenticated:
                    messages.success(request, ngettext_lazy('Area successfully unlocked.',
                                                            'Areas successfully unlocked.', num_restrictions))
                else:
                    messages.success(
                        request,
                        ngettext_lazy(
                            'Area successfully unlocked. '
                            'If you sign in, it will also be saved to your account.',
                            'Areas successfully unlocked. '
                            'If you sign in, they will also be saved to your account.',
                            num_restrictions
                        )
                    )

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
        'origin': (TypeAdapter(SingleLocationItemSchema).validate_python(origin).model_dump()
                   if origin else None),
        'destination': (TypeAdapter(SingleLocationItemSchema).validate_python(destination).model_dump()
                        if destination else None),
        'sidebar': routing or destination is not None,
        'details': True if details else False,
        'options': True if options else False,
        'nearby': True if nearby else False,
    }

    levels = levels_by_level_index_for_request(request)

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

    if origin is not None and destination is not None:
        metadata = {
            'title': _('Route from %s to %s') % (origin.title, destination.title),
            'preview_img_url': request.build_absolute_uri(reverse('mapdata.preview.route', kwargs={
                'slug': origin.effective_slug,
                'slug2': destination.effective_slug,
                'ext': 'webp',
            })),
            'canonical_url': request.build_absolute_uri(reverse('site.index', kwargs={
                'mode': 'r',
                'slug': origin.effective_slug,
                'slug2': destination.effective_slug,
                'details': False,
                'options': False,
            })),
        }
    elif destination is not None or origin is not None:
        if destination is not None:
            loc_slug = destination.effective_slug
            title = destination.title
            subtitle = destination.subtitle if hasattr(destination, 'subtitle') else None
        else:
            loc_slug = origin.effective_slug
            title = origin.title
            subtitle = origin.subtitle if hasattr(origin, 'subtitle') else None
        metadata = {
            'title': title,
            'description': subtitle,
            'preview_img_url': request.build_absolute_uri(reverse('mapdata.preview.location',
                                                                  kwargs={'slug': loc_slug, 'ext': 'webp'})),
            'canonical_url': request.build_absolute_uri(reverse('site.index', kwargs={
                'mode': 'l',
                'slug': loc_slug,
                'nearby': False,
                'details': False,
            })),
        }
    elif mode is None:
        metadata = {
            'title': settings.BRANDING,
            # 'description': '',
            'preview_img_url': request.build_absolute_uri(reverse('mapdata.preview.location',
                                                                  kwargs={'slug': settings.MAIN_PREVIEW_SLUG,
                                                                          'ext': 'webp'})),
            'canonical_url': request.build_absolute_uri('/'),
        }
    else:
        metadata = None

    from c3nav.mapdata.models.theme import Theme
    ctx = {
        'bounds': json.dumps(Source.max_bounds(), separators=(',', ':')),
        'levels': json.dumps(tuple((level.pk, level.level_index, level.short_label) for level in levels.values()), separators=(',', ':')),
        'state': json.dumps(state, separators=(',', ':'), cls=DjangoJSONEncoder),
        'tile_cache_server': settings.TILE_CACHE_SERVER,
        'initial_level': settings.INITIAL_LEVEL,
        'initial_bounds': json.dumps(initial_bounds, separators=(',', ':')) if initial_bounds else None,
        'last_site_update': json.dumps(SiteUpdate.last_update()),
        'ssids': json.dumps(settings.WIFI_SSIDS, separators=(',', ':')) if settings.WIFI_SSIDS else None,
        'random_location_groups': (
            ','.join(str(i) for i in settings.RANDOM_LOCATION_GROUPS) if settings.RANDOM_LOCATION_GROUPS else None
        ),
        'editor': can_access_editor(request),
        'embed': bool(embed),
        'imprint': settings.IMPRINT_LINK,
        'meta': metadata,
        'available_themes': {
            theme.pk: [theme.title, theme.public]
            for theme in Theme.objects.all()
        }
    }

    if grid.enabled:
        ctx['grid'] = json.dumps(GridSchema.model_validate(grid).model_dump(), separators=(',', ':'), cls=DjangoJSONEncoder)

    csrf.get_token(request)

    if not embed:
        announcement = Announcement.get_current()
        if announcement:
            messages.info(request, announcement.text)

    response = render(request, 'site/map.html', ctx)
    set_tile_access_cookie(request, response)

    if embed:
        xframe_options_exempt(lambda: response)()
        cross_origin = request.META.get('HTTP_ORIGIN')
        if cross_origin is not None:
            try:
                if request.META['HTTP_HOST'] == urlparse(cross_origin).hostname:
                    cross_origin = None
            except ValueError:
                pass
        if cross_origin is not None:
            response['Access-Control-Allow-Origin'] = cross_origin

    return response


def qr_code_etag(request, path):
    return '1'


@etag(qr_code_etag)
@cache_control(max_age=3600)
def qr_code(request, path):
    data = (request.build_absolute_uri('/' + path.removeprefix('/')) +
            ('?' + request.META['QUERY_STRING'] if request.META['QUERY_STRING'] else ''))
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
        return HttpResponse(json.dumps(dict(request.user_data), cls=DjangoJSONEncoder).encode(),
                            content_type='text/plain')
    redirect_path = request.GET['next'] if request.GET.get('next', '').startswith('/') else reverse('site.index')
    return redirect(redirect_path)


def migrate_access_permissions_after_login(request):
    if not request.user.is_authenticated:
        raise ValueError
    with transaction.atomic():
        session_token = request.session.pop("accesspermission_session_token", None)
        if session_token:
            AccessPermission.objects.filter(session_token=session_token).update(session_token=None, user=request.user)
            transaction.on_commit(lambda: cache.delete(AccessPermission.request_access_permission_key(request)))


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return close_response(request)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.user_cache, 'django.contrib.auth.backends.ModelBackend')
            migrate_access_permissions_after_login(request)
            return close_response(request)
    else:
        form = AuthenticationForm(request)

    add_compliance_checkbox(form)

    redirect_path = request.GET.get(REDIRECT_FIELD_NAME, '/account/')
    if referer := request.headers.get('Referer', None):
        referer = urlparse(referer)
        if referer.netloc == request.META['HTTP_HOST']:
            redirect_path = f'{referer.path}?{referer.query}' if referer.query else referer.path
    redirect_query = QueryDict(mutable=True)
    redirect_query[REDIRECT_FIELD_NAME] = redirect_path

    ctx = {
        'title': _('Log in'),
        'form': form,
        'redirect_path': redirect_path,
        'redirect_query': redirect_query.urlencode(safe="/")
    }

    if settings.USER_REGISTRATION:
        ctx.update({
            'bottom_link_url': reverse('site.register'),
            'bottom_link_text': _('Create new account')
        })

    if settings.SSO_ENABLED:
        from c3nav.control.sso import get_sso_services
        ctx['sso_services'] = get_sso_services()

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
            login(request, user, 'django.contrib.auth.backends.ModelBackend')
            migrate_access_permissions_after_login(request)
            return close_response(request)
    else:
        form = UserCreationForm()

    add_compliance_checkbox(form)

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
            login(request, request.user, 'django.contrib.auth.backends.ModelBackend')
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
def delete_account_view(request):
    if request.method == 'POST':
        form = DeleteAccountForm(data=request.POST)
        if form.is_valid():
            request.user.delete()
            messages.success(request, _('Account successfully deleted.'))
            return redirect('site.account')
    else:
        form = DeleteAccountForm()

    return render(request, 'site/account_form.html', {
        'title': _('Delete account'),
        'form_description': _("Click the button below to instantly delete your account and all associated data. "
                              "This process can't be reversed."),
        'back_url': reverse('site.account'),
        'form': form,
    })


@never_cache
@login_required(login_url='site.login')
def account_view(request):
    ctx = {
        'user_has_reports': Report.user_has_reports(request.user),
    }
    if settings.SSO_ENABLED:
        from social_core.backends.utils import user_backends_data
        from social_django.utils import Storage
        from c3nav.control.sso import get_sso_services
        sso_services = get_sso_services()
        ctx['sso_services'] = sso_services
        backends = user_backends_data(
            request.user, settings.AUTHENTICATION_BACKENDS, Storage
        )
        ctx['sso_backends'] = {
            'associated': {backend.provider: sso_services[backend.provider] for backend in backends["associated"] },
            'not_associated': {backend: sso_services[backend] for backend in backends["not_associated"] },
        }
    return render(request, 'site/account.html', ctx)


@never_cache
@login_required(login_url='site.login')
def account_manage(request):
    return render(request, 'site/account_manage.html', {})


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
            token.redeem(request=request)
            token.save()

            if request.user.is_authenticated:
                messages.success(request, ngettext_lazy('Area successfully unlocked.',
                                                        'Areas successfully unlocked.', num_restrictions))
            else:
                messages.success(
                    request,
                    ngettext_lazy(
                        'Area successfully unlocked. If you sign in, it will also be saved to your account.',
                        'Areas successfully unlocked. If you sign in, they will also be saved to your account.',
                        num_restrictions
                    ))
            return redirect('site.index')

    return render(request, 'site/confirm.html', {
        'title': ngettext_lazy('Unlock area', 'Unlock areas', num_restrictions),
        'texts': (ngettext_lazy('You have been invited to unlock the following area:',
                                'You have been invited to unlock the following areas:',
                                num_restrictions),
                  ', '.join(str(restriction.title) for restriction in token.restrictions)),
    })


language_change_counter = None
if settings.METRICS:
    language_change_counter = Counter('language_change', 'Language changes', ['language'])
    for lang_code, lang_name in settings.LANGUAGES:
        language_change_counter.labels(lang_code)


def choose_language(request):
    next_url = request.GET.get("next", request.META.get("HTTP_REFERER"))
    if not url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
    ):
        next_url = reverse('site.index')
    if request.method == 'POST':
        lang_code = request.POST.get(LANGUAGE_QUERY_PARAMETER)
        if language_change_counter:
            language_change_counter.labels(lang_code).inc()
        return set_language(request)
    return render(request, 'site/language.html', {'next_url': next_url})


@never_cache
def about_view(request):
    return render(request, 'site/about.html', {
        'ajax': request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'ajax' in request.GET,
        'imprint': settings.IMPRINT_LINK,
        'patrons': settings.IMPRINT_PATRONS,
        'team': settings.IMPRINT_TEAM,
        'hosting': settings.IMPRINT_HOSTING,
        'about_extra': settings.ABOUT_EXTRA,
        'version': c3nav_version,
    })


def get_report_location_for_request(pk, request):
    location = get_location_for_request(pk, request)
    if location is None:
        raise Http404
    return location


@never_cache
def report_start_coordinates(request, coordinates):
    return render(request, 'site/report_question.html', {
        'question': _('What\'s wrong here?'),
        'answers': [
            {
                'url': reverse('site.report_missing_check', kwargs={'coordinates': coordinates}),
                'text': _('A location is missing'),
            },
            {
                'url': reverse('site.report_select_location', kwargs={'coordinates': coordinates}),
                'text': _('A location is there, but wrong'),
            },
        ]
    })


@never_cache
def report_missing_check(request, coordinates):
    nearby = get_location_for_request(coordinates, request).nearby
    if not nearby:
        return redirect(reverse('site.report_missing_choose', kwargs={"coordinates": coordinates}))
    return render(request, 'site/report_question.html', {
        'question': _('Are you sure it\'s not one of these?'),
        'locations': [
            {
                'location': get_location_for_request(location.id, request),  # todo: correct subtitle w/o this
            }
            for location in nearby
        ],
        'answers': [
            {
                'url': reverse('site.report_missing_choose', kwargs={"coordinates": coordinates}),
                'text': _('Yeah, it\'s not in there'),
            },
        ]
    })


@never_cache
def report_select_location(request, coordinates):
    location = get_location_for_request(coordinates, request)
    nearby = list(location.nearby)
    if location.space:
        nearby.append(location.space)
    if not nearby:
        messages.error(request, _('There are no locations nearby.'))
        return render(request, 'site/report_question.html', {})
    return render(request, 'site/report_question.html', {
        'question': _('Which one is it?'),
        'locations': [
            {
                'url': reverse('site.report_create', kwargs={"location": location.id}),
                'location': get_location_for_request(location.id, request),  # todo: correct subtitle w/o this
            }
            for location in nearby
        ],
    })


@never_cache
def report_missing_choose(request, coordinates):
    groups = LocationGroup.qs_for_request(request).filter(can_report_missing__in=(
        LocationGroup.CanReportMissing.SINGLE,
        LocationGroup.CanReportMissing.SINGLE_IMAGE,
        LocationGroup.CanReportMissing.REJECT,
    ))
    if not groups.exists():
        return redirect(reverse('site.report_create', kwargs={"coordinates": coordinates}))
    return render(request, 'site/report_question.html', {
        'question': _('Does one of these describe your missing location?'),
        'locations': [
            {
                "url": reverse('site.report_create',
                               kwargs={"coordinates": coordinates, "group": group.effective_slug}),
                "location": group,
                "replace_subtitle": group.description
            }
            for group in groups
        ],
        'before_answers': _('Please carefully check if one of the options above applies to the missing location!'),
        'answers': [
            {
                'url': reverse('site.report_create', kwargs={"coordinates": coordinates}),
                'text': _('None of these fit'),
            },
        ],
    })


@never_cache
def report_start_location(request, location):
    return redirect(reverse('site.report_create',
                            kwargs={"location": location}))


@never_cache
def report_start_route(request, origin, destination, options):
    return redirect(reverse('site.report_create',
                            kwargs={"origin": origin, "destination": destination, "options": options}))


@never_cache
@login_required(login_url='site.login')
def report_create(request, coordinates=None, location=None, origin=None, destination=None, options=None, group=None):
    report = Report()
    report.request = request

    form_kwargs = {}
    help_text = None

    if coordinates:
        report.category = 'missing-location'
        report.coordinates_id = coordinates
        form_kwargs["request"] = request
        if group:
            group = get_location_for_request(group, request)
            if not isinstance(group, LocationGroup):
                raise Http404
            if group.can_report_missing == LocationGroup.CanReportMissing.REJECT:
                messages.error(request, format_html(
                    '{}<br><br>{}',
                    _('We do not accept reports for this type of location.'),
                    group.report_help_text,
                ))
                return render(request, 'site/report_question.html', {})
            if group.can_report_missing not in (LocationGroup.CanReportMissing.SINGLE,
                                                LocationGroup.CanReportMissing.SINGLE_IMAGE):
                raise Http404
            help_text = group.report_help_text
            form_kwargs["group"] = group
        try:
            report.coordinates
        except ObjectDoesNotExist:
            raise Http404
    elif location:
        report.category = 'location-issue'
        report.location = get_report_location_for_request(location, request)
        for group in report.location.groups.all():
            if group.can_report_mistake == LocationGroup.CanReportMistake.REJECT:
                messages.error(request, format_html(
                    '{}<br><br>{}',
                    _('We do not accept reports for this location.'),
                    group.report_help_text,
                ))
                return render(request, 'site/report_question.html', {})
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
        form = report.form_cls(instance=report, data=request.POST, files=request.FILES, **form_kwargs)
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
        form = report.form_cls(instance=report, **form_kwargs)

    return render(request, 'site/report_create.html', {
        'report': report,
        'options': options,
        'form': form,
        "help_text": help_text,
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
    coordinates = get_location_for_request(coordinates, request)
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


@login_required(login_url='site.login')
def api_secret_list(request):
    print(Secret.objects.values_list("api_secret", flat=True))
    if request.method == 'POST' and request.POST.get('delete', 'nope').isdigit():
        Secret.objects.filter(user=request.user, pk=int(request.POST['delete'])).delete()
        messages.success(request, _('API secret deleted.'))
        return redirect(reverse('site.api_secret_list'))
    return render(request, 'site/api_secret_list.html', {
        'api_secrets': Secret.objects.filter(user=request.user).order_by('-created'),
    })


@login_required(login_url='site.login')
def api_secret_create(request):
    if Secret.objects.filter(user=request.user).count() >= 20:
        messages.error(request, _('You can\'t create more than 20 API secrets.'))

    if request.method == 'POST':
        form = APISecretForm(data=request.POST, request=request)
        if form.is_valid():
            secret = form.save()
            messages.success(request, format_html(
                '{}<br><code>{}</code>',
                _('API secret created. Save it now, cause it will not be shown again!'),
                f'secret:{secret.api_secret}',
            ))
            return redirect(reverse('site.api_secret_list'))
    else:
        form = APISecretForm(request=request)

    return render(request, 'site/api_secret_create.html', {
        'form': form,
    })
