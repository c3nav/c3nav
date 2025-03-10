import binascii
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from itertools import chain
from typing import Sequence

from django.contrib.auth.models import User
from django.db.models import Prefetch
from django.forms import ChoiceField, Form, IntegerField, ModelForm, Select, MultipleChoiceField
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from c3nav.api.models import Secret
from c3nav.control.models import UserPermissions, UserSpaceAccess
from c3nav.mapdata.forms import I18nModelFormMixin
from c3nav.mapdata.models import MapUpdate, Space
from c3nav.mapdata.models.access import (AccessPermission, AccessPermissionToken, AccessPermissionTokenItem,
                                         AccessRestriction, AccessRestrictionGroup)
from c3nav.mapdata.quests.base import quest_types
from c3nav.site.models import Announcement


class UserPermissionsForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['review_group_reports'].label_from_instance = lambda obj: obj.title
        self.fields['allowed_quests'] = MultipleChoiceField(
            label=_('Available quests'),
            choices=[(key, quest.quest_type_label) for key, quest in quest_types.items()],
            initial=self.instance.quests,
            required=False,
        )

    def save(self, *args, **kwargs):
        self.instance.quests = self.cleaned_data['allowed_quests']
        super().save()

    class Meta:
        model = UserPermissions
        exclude = ('user', 'max_changeset_changes', 'api_secret', 'quests')


class AccessPermissionForm(Form):
    def __init__(self, request=None, author=None, expire_date=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # remember author if this form is saved
        self.author = author or request.user
        author_permissions = request.user_permissions if request else UserPermissions.get_for_user(author)

        self.expire_date = expire_date

        # determine which access permissions the author can grant
        if request:
            self.author_access_permissions = AccessPermission.get_for_request_with_expire_date(request, can_grant=True)
        else:
            self.author_access_permissions = AccessPermission.get_for_user_with_expire_date(author, can_grant=True)

        access_restrictions = AccessRestriction.objects.filter(
            pk__in=self.author_access_permissions.keys()
        )

        self.access_restrictions: dict[int: AccessRestriction] = {
            access_restriction.pk: access_restriction
            for access_restriction in access_restrictions
        }
        access_restrictions_ids = set(self.access_restrictions.keys())

        self.access_restriction_choices: dict[str, Sequence[int, str]] = {
            **{str(pk): (pk, ) for pk, access_restriction in self.access_restrictions.items()}
        }

        # get access permission groups
        if request:
            groups = AccessRestrictionGroup.qs_for_request(request, can_grant=True)
        else:
            groups = AccessRestrictionGroup.qs_for_user(author, can_grant=True)
        groups = groups.prefetch_related(
            Prefetch('members', AccessRestriction.objects.only('pk'))
        )
        self.group_contents: dict[int, set[int]] = {
            group.pk: set(r.pk for r in group.members.all())
            for group in groups
        }
        self.group_contents = {
            pk: restrictions for pk, restrictions in self.group_contents.items()
            if not (restrictions - access_restrictions_ids)
        }

        self.titles = {
            **{r.pk: r.title for r in access_restrictions},
            **{('g%d' % g.pk): g.title for g in groups},
        }

        self.access_restriction_choices.update({
            ('g%d' % pk): (('g%d' % pk),)
            for pk, restrictions in self.group_contents.items()
        })

        restrictions_not_in_group: set[int] = access_restrictions_ids
        for restrictions in self.group_contents.values():
            restrictions_not_in_group -= restrictions

        self.access_restriction_choices.update({
            "all": tuple(('g%d' % pk) for pk in self.group_contents.keys()) + tuple(restrictions_not_in_group),
        })

        # construct choice field for access permissions
        choices = [('', _('choose permissions…')),  # noqa
                   ('all', ngettext_lazy('everything possible (%d permission)',
                                         'everything possible (%d permissions)',
                                         len(access_restrictions)) % len(access_restrictions))]

        choices.append((_('Access Permission Groups'), tuple(
            ('g%d' % group.pk, group.title)
            for group in groups
        )))
        choices.append((_('Access Permissions'), tuple(
            (str(pk), access_restriction.title)
            for pk, access_restriction in self.access_restrictions.items()
        )))

        self.fields['access_restrictions'] = ChoiceField(choices=choices, required=True)

        # construct choices for the expire field
        expire_choices = [
            ('', _('never')),
        ]
        for minutes in range(15, 60, 15):
            expire_choices.append(
                (str(minutes), ngettext_lazy('in %d minute', 'in %d minutes', minutes) % minutes))

        for hours in chain(range(1, 6), range(6, 24, 6)):
            expire_choices.append(
                (str(hours*60), ngettext_lazy('in %d hour', 'in %d hours', hours) % hours)
            )
        expire_choices.insert(
            5, (str(90), _('in 1½ hour'))
        )
        for days in range(1, 14):
            expire_choices.append(
                (str(days*24*60), ngettext_lazy('in %d day', 'in %d days', days) % days)
            )

        self.fields['expires'] = ChoiceField(required=False, initial='60', choices=expire_choices)

        # if applicable, add field to grant pass on permissions
        if author_permissions.grant_all_access:
            choices = [('0', '---')]*6 + [('1', _('can pass on'))] + [('0', '---')]*3
            self.fields['can_grant'] = ChoiceField(required=False, initial='0', choices=choices)

        # if applicable, add field to grant pass on permissions
        if author_permissions.grant_unlimited_access:
            choices = [('0', '---')] * 6 + [('1', _('UNLIMITED'))] + [('0', '---')] * 3
            self.fields['unlimited'] = ChoiceField(required=False, initial='0', choices=choices)

    def clean_access_restrictions(self):
        data = self.cleaned_data['access_restrictions']
        return self.access_restriction_choices[data]

    def clean_expires(self):
        data = self.cleaned_data['expires']
        if data == '':
            return None
        return timezone.now()+timedelta(minutes=int(data))

    def save(self, user):
        self._save_code(self._create_code(), user)

    def get_token(self, unique_key=None):
        # create an AccessPermissionToken from this form and return it
        restrictions = []
        default_expire_date = self.expire_date or self.cleaned_data['expires']
        for restriction in self.cleaned_data['access_restrictions']:
            expire_date = default_expire_date

            if isinstance(restriction, int):
                author_expire_date = self.author_access_permissions.get(restriction)
            else:
                author_expire_date = min(
                    (d for d in (self.author_access_permissions.get(i)
                                 for i in self.group_contents[int(restriction.removeprefix('g'))])
                     if d is not None),
                    default=None,
                )

            # make sure that each permission is not granted for a longer time than the author has it
            if author_expire_date is not None:
                expire_date = author_expire_date if expire_date is None else min(expire_date, author_expire_date)
            restrictions.append(AccessPermissionTokenItem(pk=restriction, expire_date=expire_date,
                                                          title=self.titles[restriction]))
        unlimited_stuff = {}
        if self.cleaned_data.get("unlimited", "0") == "1":
            unlimited_stuff = {
                "valid_until": default_expire_date,
                "unlimited": True,
            }
        return AccessPermissionToken(author=self.author,
                                     can_grant=self.cleaned_data.get('can_grant', '0') == '1',
                                     restrictions=tuple(restrictions),
                                     unique_key=unique_key,
                                     **unlimited_stuff)

    def get_signed_data(self, key=None):
        try:
            api_secret = self.author.api_secrets.filter(scope_grant_permissions=True).valid_only().get().api_secret
        except Secret.DoesNotExist:
            raise ValueError('Author has no feasible api secret.')
        data = {
            'id': self.data['access_restrictions'],
            'time': int(time.time()),
            'valid_until': int(self.cleaned_data['expires'].strftime('%s')) if self.cleaned_data['expires'] else None,
            'author': self.author.pk,
        }
        if key is not None:
            data['key'] = key
        data = json.dumps(data, separators=(',', ':'))
        signature = hmac.new(api_secret.encode(), msg=data.encode(), digestmod=hashlib.sha256).digest()
        return '%s:%s' % (data, binascii.b2a_base64(signature).strip().decode())

    @classmethod
    def load_signed_data(cls, signed_data: str):
        if ':' not in signed_data:
            raise SignedPermissionDataError('Invalid data.')

        raw_data, signature = signed_data.rsplit(':', 1)

        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            raise SignedPermissionDataError('Invalid JSON.')

        try:
            restrictions = data.pop('id')
            author_id = data.pop('author')
            issue_time = data.pop('time')
            valid_until = data.pop('valid_until')
            unique_key = data.pop('key', None)
        except KeyError as e:
            raise SignedPermissionDataError('Missing %s.' % str(e))

        for unknown_key in data:
            raise SignedPermissionDataError('Unknown value: %s' % unknown_key)

        try:
            issue_time = int(issue_time)
        except ValueError:
            raise SignedPermissionDataError('Invalid time.')

        try:
            valid_until = int(valid_until) if valid_until is not None else None
        except ValueError:
            raise SignedPermissionDataError('Invalid valid_until.')
        else:
            valid_until = valid_until and datetime.utcfromtimestamp(valid_until).replace(tzinfo=dt_timezone.utc)

        try:
            author_id = int(author_id)
        except ValueError:
            raise SignedPermissionDataError('Invalid author.')

        if unique_key is not None and not isinstance(unique_key, str):
            raise SignedPermissionDataError('key has to be null or a string.')

        if issue_time > time.time()+5:
            raise SignedPermissionDataError('time cannot be in the future.')
        if issue_time < time.time()-60:
            raise SignedPermissionDataError('token has expired.')
        if unique_key is not None and not (1 <= len(unique_key) <= 32):
            raise SignedPermissionDataError('key has to be 1-32 characters')

        try:
            author = User.objects.select_related('permissions').get(pk=author_id)
        except User.DoesNotExist:
            raise SignedPermissionDataError('Author does not exist.')

        api_secrets = author.api_secrets.filter(
            scope_grant_permissions=True
        ).valid_only().values_list('api_secret', flat=True)
        if not api_secrets:
            raise SignedPermissionDataError('Author has no API secret.')

        for api_secret in api_secrets:
            verify_signature = binascii.b2a_base64(hmac.new(api_secret.encode(),
                                                            msg=raw_data.encode(), digestmod=hashlib.sha256).digest())
            if signature == verify_signature.strip().decode():
                break
        else:
            raise SignedPermissionDataError('Invalid signature.')  # todo: test this!!

        form = cls(author=author, expire_date=valid_until, data={
            'access_restrictions': str(restrictions),
        })
        if not form.is_valid():
            raise SignedPermissionDataError(' '.join(form.errors))
        return form.get_token(unique_key=unique_key)


class UserSpaceAccessForm(ModelForm):
    class Meta:
        model = UserSpaceAccess
        fields = ('space', 'can_edit')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['space'].label_from_instance = lambda obj: obj.title
        self.fields['space'].queryset = Space.objects.order_by('slug')
        choices = [('0', _('no'))] * 6 + [('1', _('yes'))] + [('0', _('no'))] * 3
        self.fields['can_edit'].widget = Select(choices=choices)


class SignedPermissionDataError(Exception):
    pass


class AnnouncementForm(I18nModelFormMixin, ModelForm):
    class Meta:
        model = Announcement
        fields = ('text', 'active', 'active_until')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['active_until'].initial = timezone.now()


class MapUpdateFilterForm(Form):
    type = ChoiceField(
        choices=(('', _('any type')), ) + MapUpdate.TYPES,
        required=False
    )
    geometries_changed = ChoiceField(
        choices=(('', _('any')), ('1', _('geometries changed')), ('0', _('no geometries changed'))),
        required=False
    )
    processed = ChoiceField(
        choices=(('', _('any')), ('1', _('processed')), ('0', _('not processed'))),
        required=False
    )
    user_id = IntegerField(min_value=1, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user_id'].widget.attrs['placeholder'] = _('user id')


class MapUpdateForm(ModelForm):
    class Meta:
        model = MapUpdate
        fields = ('geometries_changed', )
