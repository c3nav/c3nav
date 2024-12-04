from collections import OrderedDict
from contextlib import contextmanager

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction
from django.urls import reverse
from django.utils.http import int_to_base36
from django.utils.timezone import make_naive
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from django_pydantic_field import SchemaField

from c3nav.editor.changes import ChangedObjectCollection, ChangeProblems
from c3nav.editor.operations import DatabaseOperationCollection
from c3nav.editor.tasks import send_changeset_proposed_notification
from c3nav.mapdata.models import LocationSlug, MapUpdate
from c3nav.mapdata.models.locations import LocationRedirect


def _changed_object_collection_default() -> ChangedObjectCollection:
    return ChangedObjectCollection()

class ChangeSet(models.Model):
    STATES = (
        ('unproposed', _('unproposed')),
        ('proposed', _('proposed')),
        ('review', _('in review')),
        ('rejected', _('rejected')),
        ('reproposed', _('proposed again')),
        ('finallyrejected', _('finally rejected')),
        ('applied', _('accepted and applied')),
    )
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    last_change = models.ForeignKey('editor.ChangeSetUpdate', null=True, related_name='+',
                                    verbose_name=_('last object change'), on_delete=models.CASCADE)
    last_update = models.ForeignKey('editor.ChangeSetUpdate', null=True, related_name='+',
                                    verbose_name=_('last update'), on_delete=models.CASCADE)
    last_state_update = models.ForeignKey('editor.ChangeSetUpdate', null=True, related_name='+',
                                          verbose_name=_('last state update'), on_delete=models.CASCADE)
    state = models.CharField(max_length=20, db_index=True, choices=STATES, default='unproposed')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('Author'))
    title = models.CharField(max_length=100, default='', verbose_name=_('Title'))
    description = models.TextField(max_length=1000, default='', verbose_name=_('Description'), blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT,
                                    related_name='assigned_changesets', verbose_name=_('assigned to'))
    map_update = models.OneToOneField(MapUpdate, null=True, related_name='changeset',
                                      verbose_name=_('map update'), on_delete=models.PROTECT)
    changes: ChangedObjectCollection = SchemaField(schema=ChangedObjectCollection,
                                                   default=_changed_object_collection_default)

    class Meta:
        verbose_name = _('Change Set')
        verbose_name_plural = _('Change Sets')
        default_related_name = 'changesets'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.created_objects = {}
        self.updated_existing = {}
        self.deleted_existing = {}
        self.m2m_added = {}
        self.m2m_removed = {}

        self._object_changed = False
        self._request = None
        self._original_state = self.state

        self.direct_editing = False

    """
    Get Changesets for Request/Session/User
    """
    @classmethod
    def qs_for_request(cls, request):
        """
        Returns a base QuerySet to get only changesets the current user is allowed to see
        """
        if request.user_permissions.review_changesets:
            return ChangeSet.objects.all()
        elif request.user.is_authenticated:
            return ChangeSet.objects.filter(author=request.user)
        elif 'changeset' in request.session:
            return ChangeSet.objects.filter(pk=request.session['changeset'])
        return ChangeSet.objects.none()

    @classmethod
    def get_for_request(cls, request, select_related=None, as_logged_out=False):
        """
        Get the changeset for the current request.
        If a changeset is associated with the session id, it will be returned.
        Otherwise, if the user is authenticated, the last created queryset
        for this user will be returned and the session id will be added to it.
        If both fails, an empty unsaved changeset will be returned which will
        be automatically saved when a change is added to it.
        In any case, the default autor for changes added to the queryset during
        this request will be set to the current user.
        """
        if select_related is None:
            select_related = ('last_change', )
        changeset_pk = request.session.get('changeset')
        if changeset_pk is not None:
            qs = ChangeSet.objects.select_related(*select_related).exclude(state__in=('applied', 'finallyrejected'))
            if request.user.is_authenticated and not as_logged_out:
                if not request.user_permissions.review_changesets:
                    qs = qs.filter(author=request.user)
            else:
                qs = qs.filter(author__isnull=True)
            try:
                return qs.get(pk=changeset_pk)
            except ChangeSet.DoesNotExist:
                pass

        changeset = ChangeSet()
        changeset._request = request
        if request.session.get('direct_editing', False) and ChangeSet.can_direct_edit(request):
            changeset.direct_editing = True

        if request.user.is_authenticated:
            changeset.author = request.user

        return changeset

    """
    Permissions
    """
    @property
    def changes_editable(self):
        return self.state in ('unproposed', 'rejected', 'review')

    @property
    def proposed(self):
        return self.state not in ('unproposed', 'rejected')

    @property
    def closed(self):
        return self.state in ('finallyrejected', 'applied')

    def is_author(self, request):
        return (self.pk is None or self.author == request.user or
                (self.author is None and not request.user.is_authenticated and
                 request.session.get('changeset', None) == self.pk))

    def can_see(self, request):
        return self.is_author(request) or self.can_review(request)

    @contextmanager
    def lock_to_edit(self, request=None):
        with transaction.atomic():
            if self.pk is not None:
                changeset = ChangeSet.objects.select_for_update().get(pk=self.pk)
                yield changeset
            else:
                yield self

    def can_edit(self, request):
        if not self.proposed:
            return self.is_author(request)
        elif self.state == 'review':
            return self.assigned_to == request.user
        return False

    def can_activate(self, request):
        return not self.closed and self.can_edit(request)

    def can_delete(self, request):
        return self.can_edit(request) and self.state == 'unproposed'

    def can_propose(self, request):
        return self.can_edit(request) and not self.proposed and self.changes and not self.problems.any

    def can_unpropose(self, request):
        return self.author_id == request.user.pk and self.state in ('proposed', 'reproposed')

    def can_commit(self, request):
        return (self.can_edit(request) and self.can_review(request)
                and not self.proposed and self.changes and not self.problems.any)

    def has_space_access_on_all_objects(self, request, force=False):
        # todo: reimplement this
        if not request.user.is_authenticated:
            return False

        try:
            request._has_space_access_on_all_objects_cache
        except AttributeError:
            request._has_space_access_on_all_objects_cache = {}

        can_edit_spaces = {space_id for space_id, can_edit in request.user_space_accesses.items() if can_edit}

        if not can_edit_spaces:
            return False

        if not force:
            try:
                return request._has_space_access_on_all_objects_cache[self.pk]
            except KeyError:
                pass

        for model in self.changed_objects.keys():
            if issubclass(model, LocationRedirect):
                continue
            try:
                model._meta.get_field('space')
            except FieldDoesNotExist:
                return False

        result = True
        for model, objects in self.get_objects(many=False).items():
            if issubclass(model, (LocationRedirect, LocationSlug)):
                continue

            try:
                model._meta.get_field('space')
            except FieldDoesNotExist:
                result = False
                break

            for obj in objects:
                if obj.space_id not in can_edit_spaces:
                    result = False
                    break
            if not result:
                break

            try:
                model._meta.get_field('origin_space')
            except FieldDoesNotExist:
                pass
            else:
                for obj in objects:
                    if obj.origin_space_id not in can_edit_spaces:
                        result = False
                        break
                if not result:
                    break

            try:
                model._meta.get_field('target_space')
            except FieldDoesNotExist:
                pass
            else:
                for obj in objects:
                    if obj.target_space_id not in can_edit_spaces:
                        result = False
                        break
                if not result:
                    break

        request._has_space_access_on_all_objects_cache[self.pk] = result
        return result

    def can_review(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user_permissions.review_changesets:
            return True
        return self.has_space_access_on_all_objects(request)

    @classmethod
    def can_direct_edit(cls, request):
        return request.user_permissions.direct_edit

    def can_start_review(self, request):
        return self.can_review(request) and self.state in ('proposed', 'reproposed')

    def can_end_review(self, request):
        return self.can_review(request) and self.state == 'review' and self.assigned_to == request.user

    def can_apply(self, request):
        return self.can_end_review(request) and not self.problems.any

    def can_unreject(self, request):
        return (self.can_review(request) and self.state in ('rejected', 'finallyrejected') and
                self.assigned_to == request.user)

    """
    Update methods
    """
    def propose(self, user):
        new_state = {'unproposed': 'proposed', 'rejected': 'reproposed'}[self.state]
        update = self.updates.create(user=user, state=new_state)
        self.state = new_state
        self.last_update = update
        self.last_state_update = update
        self.save()
        self.notify_reviewers()

    def notify_reviewers(self):
        send_changeset_proposed_notification.delay(pk=self.pk,
                                                   title=self.title,
                                                   author=self.author.username,
                                                   description=self.description)

    def unpropose(self, user):
        new_state = {'proposed': 'unproposed', 'reproposed': 'rejected'}[self.state]
        update = self.updates.create(user=user, state=new_state)
        self.state = new_state
        self.last_update = update
        self.last_state_update = update
        self.save()

    def start_review(self, user):
        assign_to = user
        if self.assigned_to == user:
            assign_to = None
        else:
            self.assigned_to = user

        if self.state != 'review':
            update = self.updates.create(user=user, state='review', assigned_to=assign_to)
            self.state = 'review'
            self.last_state_update = update
        elif assign_to is None:
            return
        else:
            update = self.updates.create(user=user, assigned_to=assign_to)

        self.last_update = update
        self.save()

    def reject(self, user, comment: str, final: bool):
        state = 'finallyrejected' if final else 'rejected'
        self.assigned_to = None
        update = self.updates.create(user=user, state=state, comment=comment)
        self.state = state
        self.last_state_update = update
        self.last_update = update
        self.save()

    def unreject(self, user):
        update = self.updates.create(user=user, state='review')
        self.state = 'review'
        self.last_state_update = update
        self.last_update = update
        self.save()

    def apply(self, user):
        if self.problems.any:
            raise ValueError("Can't apply if there's still problems!")
        with MapUpdate.lock():
            # todo: reimplement
            update = self.updates.create(user=user, state='applied')
            map_update = MapUpdate.objects.create(user=user, type='changeset')
            self.as_operations.prefetch().apply()
            self.state = 'applied'
            self.last_state_update = update
            self.last_update = update
            self.map_update = map_update
            self.save()

    def activate(self, request):
        request.session['changeset'] = self.pk

    """
    Methods for display
    """
    @property
    def changed_objects_count(self):
        """
        Get the number of changed objects.
        """
        return len(self.changes)

    def get_changed_objects_by_model(self, model):
        if isinstance(model, str):
            model = apps.get_model('mapdata', model)
        self.fill_changes_cache()
        return self.changed_objects.get(model, {})

    @property
    def count_display(self):
        """
        Get “%d changed objects” display text.
        """
        if self.pk is None:
            if self.direct_editing:
                return _('Direct editing active')
            return _('No objects changed')
        return (ngettext_lazy('%(num)d object changed', '%(num)d objects changed', 'num') %
                {'num': self.changed_objects_count})

    @property
    def last_update_cache_key(self):
        last_update = self.created if self.last_update_id is None else self.last_update.datetime
        return int_to_base36(self.last_update_id or 0)+'_'+int_to_base36(int(make_naive(last_update).timestamp()))

    @property
    def last_change_cache_key(self):
        last_change = self.created if self.last_change_id is None else self.last_change.datetime
        return int_to_base36(self.last_change_id or 0)+'_'+int_to_base36(int(make_naive(last_change).timestamp()))

    @property
    def cache_key_by_changes(self):
        return 'editor:changeset:' + self.raw_cache_key_by_changes

    @property
    def raw_cache_key_without_changes(self):
        if self.pk is None:
            return MapUpdate.current_cache_key()
        return ':'.join((str(self.pk), MapUpdate.current_cache_key()))

    @property
    def raw_cache_key_by_changes(self):
        if self.pk is None:
            return MapUpdate.current_cache_key()
        return ':'.join((str(self.pk), MapUpdate.current_cache_key(), self.last_change_cache_key))

    def get_absolute_url(self):
        if self.pk is None:
            if self.author:
                return reverse('editor.users.detail', kwargs={'pk': self.author_id})
            return ''
        return reverse('editor.changesets.detail', kwargs={'pk': self.pk})

    def serialize(self):
        return OrderedDict((
            ('id', self.pk),
            ('author', self.author_id),
            ('state', self.state),
            ('assigned_to', self.assigned_to_id),
            ('changed_objects_count', self.changed_objects_count),
            ('created', None if self.created is None else self.created.isoformat()),
            ('last_change', None if self.last_change is None else self.last_change.datetime.isoformat()),
            ('last_update', None if self.last_update is None else self.last_update.datetime.isoformat()),
            ('last_state_update', (None if self.last_state_update is None else
                                   self.last_state_update.datetime.isoformat())),
            ('last_state_update_user', (None if self.last_state_update is None else
                                        self.last_state_update.user_id)),
            ('last_state_update_comment', (None if self.last_state_update is None else
                                           self.last_state_update.comment)),
        ))

    def save(self, *args, **kwargs):
        if self._original_state == 'applied':
            raise TypeError('Applied change sets can not be edited.')
        super().save(*args, **kwargs)
        if self._request is not None:
            self.activate(self._request)
            self._request = None

    STATE_ICONS = {
        'unproposed': 'pencil',
        'proposed': 'send',
        'reproposed': 'send',
        'review': 'hourglass',
        'rejected': 'remove',
        'finallyrejected': 'remove',
        'applied': 'ok',
    }

    @property
    def icon(self):
        return self.STATE_ICONS[self.state]

    STATE_STYLES = {
        'unproposed': 'muted',
        'proposed': 'info',
        'reproposed': 'info',
        'review': 'info',
        'rejected': 'danger',
        'finallyrejected': 'danger',
        'applied': 'success',
    }

    @property
    def style(self):
        return self.STATE_STYLES[self.state]

    def get_changes_as_operations(self) -> ChangedObjectCollection.ChangesAsOperations:
        """
        preferably don't use this one but use as_operations or problems
        """
        cache_key = '%s:changes_as_operations' % self.cache_key_by_changes
        changes_as_operations = cache.get(cache_key)
        if not changes_as_operations:
            changes_as_operations = self.changes.as_operations
            cache.set(cache_key, changes_as_operations, 900)
        return changes_as_operations

    @property
    def as_operations(self) -> DatabaseOperationCollection:
        return self.get_changes_as_operations().operations

    @property
    def problems(self) -> ChangeProblems:
        if self.state == "applied":
            return ChangeProblems()
        return self.get_changes_as_operations().problems
