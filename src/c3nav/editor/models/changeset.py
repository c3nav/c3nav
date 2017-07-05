from collections import OrderedDict
from contextlib import contextmanager
from itertools import chain

from django.apps import apps
from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy
from rest_framework.exceptions import PermissionDenied

from c3nav.editor.models.changedobject import ChangedObject
from c3nav.editor.utils import is_created_pk
from c3nav.editor.wrappers import ModelWrapper
from c3nav.mapdata.models import LocationSlug
from c3nav.mapdata.models.locations import LocationRedirect
from c3nav.mapdata.utils.models import get_submodels


class ChangeSet(models.Model):
    STATES = (
        ('unproposed', _('unproposed')),
        ('proposed', _('proposed')),
        ('review', _('in review')),
        ('rejected', _('rejected')),
        ('reproposed', _('reproposed')),
        ('finallyrejected', _('finally rejected')),
        ('applied', _('accepted')),
    )
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    last_change = models.ForeignKey('editor.ChangeSetUpdate', null=True, related_name='+',
                                    verbose_name=_('last object change'))
    last_update = models.ForeignKey('editor.ChangeSetUpdate', null=True, related_name='+',
                                    verbose_name=_('last update'))
    last_state_update = models.ForeignKey('editor.ChangeSetUpdate', null=True, related_name='+',
                                          verbose_name=_('last state update'))
    state = models.CharField(max_length=20, db_index=True, choices=STATES, default='unproposed')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('Author'))
    title = models.CharField(max_length=100, default='', verbose_name=_('Title'))
    description = models.TextField(max_length=1000, default='', verbose_name=_('Description'))
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT,
                                    related_name='assigned_changesets', verbose_name=_('assigned to'))

    class Meta:
        verbose_name = _('Change Set')
        verbose_name_plural = _('Change Sets')
        default_related_name = 'changesets'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.changed_objects = None

        self.created_objects = {}
        self.updated_existing = {}
        self.deleted_existing = {}
        self.m2m_added = {}
        self.m2m_removed = {}

        self._object_changed = False
        self._request = None

    """
    Get Changesets for Request/Session/User
    """
    @classmethod
    def qs_for_request(cls, request):
        """
        Returns a base QuerySet to get only changesets the current user is allowed to see
        """
        if request.user.is_authenticated:
            return ChangeSet.objects.filter(author=request.user)
        return ChangeSet.objects.none()

    @classmethod
    def get_for_request(cls, request, select_related=None):
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
            qs = ChangeSet.objects.select_related(*select_related).exclude(state='applied')
            if request.user.is_authenticated:
                qs = qs.filter(author=request.user)
            else:
                qs = qs.filter(author__isnull=True)
            try:
                return qs.get(pk=changeset_pk)
            except ChangeSet.DoesNotExist:
                pass

        changeset = ChangeSet()
        changeset._request = request

        if request.user.is_authenticated:
            changeset.author = request.user

        return changeset

    """
    Wrap Objects
    """
    def wrap_model(self, model):
        if isinstance(model, str):
            model = apps.get_model('mapdata', model)
        assert isinstance(model, type) and issubclass(model, models.Model)
        return ModelWrapper(self, model)

    def wrap_instance(self, instance):
        assert isinstance(instance, models.Model)
        return self.wrap_model(instance.__class__).create_wrapped_model_class()(self, instance)

    def relevant_changed_objects(self):
        return self.changed_objects_set.exclude(existing_object_pk__isnull=True, deleted=True)

    def fill_changes_cache(self, include_deleted_created=False):
        """
        Get all changed objects and fill this ChangeSet's changes cache.
        Only executable once, if something is changed later the cache will be automatically updated.
        This method gets called automatically when the cache is needed.
        Only call it if you need to set include_deleted_created to True.
        :param include_deleted_created: Fetch created objects that were deleted.
        :rtype: True if the method was executed, else False
        """
        if self.changed_objects is not None:
            return False

        if self.pk is None:
            self.changed_objects = {}
            return False

        if include_deleted_created:
            qs = self.changed_objects_set.all()
        else:
            qs = self.relevant_changed_objects()

        self.changed_objects = {}
        for change in qs:
            change.update_changeset_cache()

        return True

    """
    Analyse Changes
    """
    def get_objects(self):
        if self.changed_objects is None:
            raise TypeError

        # collect pks of relevant objects
        object_pks = {}
        for change in chain(*(objects.values() for objects in self.changed_objects.values())):
            change.add_relevant_object_pks(object_pks)

        # retrieve relevant objects
        objects = {}
        for model, pks in object_pks.items():
            created_pks = set(pk for pk in pks if is_created_pk(pk))
            existing_pks = pks - created_pks
            model_objects = {}
            if existing_pks:
                for obj in model.objects.filter(pk__in=existing_pks):
                    if model == LocationSlug:
                        obj = obj.get_child()
                    model_objects[obj.pk] = obj
            if created_pks:
                for pk in created_pks:
                    model_objects[pk] = self.get_created_object(model, pk, allow_deleted=True)._obj
            objects[model] = model_objects

        # add LocationSlug objects as their correct model
        for pk, obj in objects.get(LocationSlug, {}).items():
            objects.setdefault(obj.__class__, {})[pk] = obj

        return objects

    def get_changed_values(self, model: models.Model, name: str) -> tuple:
        """
        Get all changes values for a specific field on existing models
        :param model: model class
        :param name: field name
        :return: returns a dictionary with primary keys as keys and new values as values
        """
        r = tuple((pk, values[name]) for pk, values in self.updated_existing.get(model, {}).items() if name in values)
        return r

    def get_changed_object(self, obj) -> ChangedObject:
        model = obj.__class__
        pk = obj.pk
        if pk is None:
            return ChangedObject(changeset=self, model_class=model)

        self.fill_changes_cache()

        objects = tuple(obj for obj in ((submodel, self.changed_objects.get(submodel, {}).get(pk, None))
                                        for submodel in get_submodels(model)) if obj[1] is not None)
        if len(objects) > 1:
            raise model.MultipleObjectsReturned
        if objects:
            return objects[0][1]

        if is_created_pk(pk):
            raise model.DoesNotExist

        return ChangedObject(changeset=self, model_class=model, existing_object_pk=pk)

    def get_created_object(self, model, pk, get_foreign_objects=False, allow_deleted=False):
        """
        Gets a created model instance.
        :param model: model class
        :param pk: primary key
        :param get_foreign_objects: whether to fetch foreign objects and not just set their id to field.attname
        :param allow_deleted: return created objects that have already been deleted (needs get_history=True)
        :return: a wrapped model instance
        """
        self.fill_changes_cache()
        if issubclass(model, ModelWrapper):
            model = model._obj

        obj = self.get_changed_object(model(pk=pk))
        if obj.deleted and not allow_deleted:
            raise model.DoesNotExist
        return obj.get_obj(get_foreign_objects=get_foreign_objects)

    def get_created_pks(self, model) -> set:
        """
        Returns a set with the primary keys of created objects from this model
        """
        self.fill_changes_cache()
        if issubclass(model, ModelWrapper):
            model = model._obj
        return set(self.created_objects.get(model, {}).keys())

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
        return (self.author == request.user or (self.author is None and not request.user.is_authenticated and
                                                request.session.get('changeset', None) == self.pk))

    def can_see(self, request):
        return self.is_author(request)

    @contextmanager
    def lock_to_edit(self, request=None):
        with transaction.atomic():
            if self.pk is not None:
                changeset = ChangeSet.objects.select_for_update().get(pk=self.pk)
                if request is not None and not changeset.can_edit(request):
                    raise PermissionDenied

                self._object_changed = False
                yield changeset
                if self._object_changed and request is not None:
                    update = changeset.updates.create(user=request.user if request.user.is_authenticated else None,
                                                      objects_changed=True)
                    changeset.last_update = update
                    changeset.last_change = update
                    changeset.save()
            else:
                yield

    def can_edit(self, request):
        if not self.proposed:
            return self.is_author(request)
        elif self.state == 'review':
            return self.assigned_to == request.user
        return False

    def can_delete(self, request):
        return self.can_edit(request) and self.state == 'unproposed'

    def can_propose(self, request):
        return self.can_edit(request) and not self.proposed

    def can_unpropose(self, request):
        return self.author_id == request.user.pk and self.state in ('proposed', 'reproposed')

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

    def unpropose(self, user):
        new_state = {'proposed': 'unproposed', 'reproposed': 'rejected'}[self.state]
        update = self.updates.create(user=user, state=new_state)
        self.state = new_state
        self.last_update = update
        self.last_state_update = update
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
        self.fill_changes_cache()
        count = 0
        changed_locationslug_pks = set()
        for model, objects in self.changed_objects.items():
            if issubclass(model, LocationSlug):
                if model == LocationRedirect:
                    continue
                changed_locationslug_pks.update(objects.keys())
            count += sum(1 for obj in objects.values() if not obj.is_created or not obj.deleted)

        count += len(set(obj.updated_fields['target']
                         for obj in self.changed_objects.get(LocationRedirect, {}).values()) - changed_locationslug_pks)
        return count

    @property
    def count_display(self):
        """
        Get “%d changed objects” display text.
        """
        if self.pk is None:
            return _('No objects changed')
        return (ungettext_lazy('%(num)d object changed', '%(num)d objects changed', 'num') %
                {'num': self.changed_objects_count})

    @property
    def cache_key(self):
        if self.pk is None:
            return None
        return str(self.pk)+'-'+str(self.last_change)

    def get_absolute_url(self):
        if self.pk is None:
            return ''
        return reverse('editor.changesets.detail', kwargs={'pk': self.pk})

    def serialize(self):
        return OrderedDict((
            ('id', self.pk),
            ('author', self.author_id),
            ('created', None if self.created is None else self.created.isoformat()),
        ))

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self._request is not None:
            self.activate(self._request)
