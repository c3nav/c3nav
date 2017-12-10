from datetime import timedelta
from itertools import chain

from django.db.models import Q
from django.forms import ChoiceField, Form, ModelForm
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.control.models import UserPermissions
from c3nav.mapdata.models.access import AccessPermissionToken, AccessRestriction


class UserPermissionsForm(ModelForm):
    class Meta:
        model = UserPermissions
        exclude = ('user', )


class AccessPermissionForm(Form):
    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.author = request.user

        if not request.user_permissions.access_all:
            self.author_access_permissions = {
                pk: expire_date for pk, expire_date in self.author.accesspermissions.filter(
                    Q(can_grant=True) & (Q(expire_date__isnull=True) | Q(expire_date__lt=timezone.now()))
                ).values_list('access_restriction_id', 'expire_date')
            }
            access_restrictions = AccessRestriction.objects.filter(
                pk__in=self.author_access_permissions.keys()
            )
        else:
            self.author_access_permissions = {}
            access_restrictions = AccessRestriction.objects.all()

        self.access_restrictions = {
            access_restriction.pk: access_restriction
            for access_restriction in access_restrictions
        }

        self.access_restriction_choices = {
            'all': self.access_restrictions.values(),
            **{str(pk): (access_restriction, ) for pk, access_restriction in self.access_restrictions.items()}
        }

        choices = [('', _('choose permissions…')),
                   ('all', ungettext_lazy('everything possible (%d permission)',
                                          'everything possible (%d permissions)',
                                          len(access_restrictions)) % len(access_restrictions))]

        choices.append((_('Access Permissions'), tuple(
            (str(pk), access_restriction.title)
            for pk, access_restriction in self.access_restrictions.items()
        )))

        self.fields['access_restrictions'] = ChoiceField(choices=choices, required=True)

        expire_choices = [
            ('', _('never')),
        ]
        for minutes in range(15, 60, 15):
            expire_choices.append(
                (str(minutes), ungettext_lazy('in %d minute', 'in %d minutes', minutes) % minutes))

        for hours in chain(range(1, 6), range(6, 24, 6)):
            expire_choices.append(
                (str(hours*60), ungettext_lazy('in %d hour', 'in %d hours', hours) % hours)
            )
        expire_choices.insert(
            5, (str(90), _('in 1½ hour'))
        )
        for days in range(1, 14):
            expire_choices.append(
                (str(days*24*60), ungettext_lazy('in %d day', 'in %d days', days) % days)
            )

        self.fields['expires'] = ChoiceField(required=False, initial='60', choices=expire_choices)

        if request.user_permissions.access_all:
            choices = [('0', '---')]*6 + [('1', _('can pass on'))] + [('0', '---')]*3
            self.fields['can_grant'] = ChoiceField(required=False, initial='60', choices=choices)

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

    def get_token(self):
        restrictions = []
        for restriction in self.cleaned_data['access_restrictions']:
            expires = self.cleaned_data['expires']
            author_expires = self.author_access_permissions.get(restriction.pk)
            if author_expires is not None:
                expires = author_expires if expires is None else min(expires, author_expires)
            restrictions.append((restriction.pk, expires))
        return AccessPermissionToken(author=self.author,
                                     can_grant=self.cleaned_data.get('can_grant', '0') == '1',
                                     restrictions=tuple(restrictions))
