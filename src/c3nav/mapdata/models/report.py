import string

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils.crypto import get_random_string
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.utils.locations import get_location_by_id_for_request


def get_report_secret():
    return get_random_string(32, string.ascii_letters)


class LocationById():
    def __init__(self):
        super().__init__()
        self.name = None
        self.cached_id = None
        self.cached_value = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner=None):
        value_id = getattr(instance, self.name+'_id')
        if value_id is None:
            self.cached_pk = None
            self.cached_value = None
            return None

        if value_id == self.cached_id:
            return self.cached_value

        value = get_location_by_id_for_request(value_id, getattr(instance, 'request', None))
        if value is None:
            raise ObjectDoesNotExist
        self.cached_id = value_id
        self.cached_value = value
        return value

    def __set__(self, instance, value):
        self.cached_id = value.pk
        self.cached_value = value
        setattr(instance, self.name+'_id', value.pk)


class Report(models.Model):
    CATEGORIES = (
        ('location-issue', _('location issue')),
        ('missing-location', _('missing location')),
        ('route-issue', _('route issue')),
    )
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    category = models.CharField(max_length=20, db_index=True, choices=CATEGORIES, verbose_name=_('category'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('author'))
    open = models.BooleanField(default=True, verbose_name=_('open'))
    last_update = models.DateTimeField(auto_now=True, verbose_name=_('last_update'))
    title = models.CharField(max_length=100, default='', verbose_name=_('title'),
                             help_text=_('a short title for your report'))
    description = models.TextField(max_length=1000, default='', verbose_name=_('description'),
                                   help_text=_('tell us precisely what\'s wrong'))
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT,
                                    related_name='assigned_reports', verbose_name=_('assigned to'))
    location = models.ForeignKey('mapdata.LocationSlug', null=True, on_delete=models.SET_NULL,
                                 related_name='reports', verbose_name=_('location'))
    coordinates_id = models.CharField(_('coordinates'), null=True, max_length=48)
    origin_id = models.CharField(_('origin'), null=True, max_length=48)
    destination_id = models.CharField(_('destination'), null=True, max_length=48)
    route_options = models.CharField(_('route options'), null=True, max_length=128)

    created_title = I18nField(_('new location title'), plural_name='titles', blank=False, fallback_any=True,
                              help_text=_('you have to supply a title in at least one language'))
    created_groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('location groups'), blank=True,
                                            limit_choices_to={'can_report_missing': True},
                                            help_text=_('select all groups that apply, if any'))
    secret = models.CharField(_('secret'), max_length=32, default=get_report_secret)

    coordinates = LocationById()
    origin = LocationById()
    destination = LocationById()

    class Meta:
        verbose_name = _('Report')
        verbose_name_plural = _('Reports')
        default_related_name = 'report'

    @property
    def form_cls(self):
        from c3nav.site.forms import ReportMissingLocationForm, ReportIssueForm
        return ReportMissingLocationForm if self.category == 'missing-location' else ReportIssueForm

    @classmethod
    def qs_for_request(cls, request):
        if request.user.is_superuser:
            # todo: permissions!
            return cls.objects.all()
        elif request.user.is_authenticated:
            return cls.objects.filter(author=request.user)
        else:
            return cls.objects.none()


class ReportUpdate(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE)
    datetime = models.DateTimeField(auto_now_add=True, verbose_name=_('datetime'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('author'))
    open = models.NullBooleanField(verbose_name=_('open'))
    comment = models.TextField(verbose_name=_('comment'))
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT,
                                    related_name='report_update_assigns', verbose_name=_('assigned to'))
    public = models.BooleanField(verbose_name=_('public'))

    class Meta:
        verbose_name = _('Report update')
        verbose_name_plural = _('Report updates')
        default_related_name = 'reportupdate'
