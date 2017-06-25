import json
from collections import OrderedDict

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.editor.models.change import Change
from c3nav.editor.utils import is_created_pk
from c3nav.editor.wrappers import ModelInstanceWrapper, ModelWrapper
from c3nav.mapdata.models import LocationSlug
from c3nav.mapdata.models.locations import LocationRedirect
from c3nav.mapdata.utils.models import get_submodels


class ChangeSet(models.Model):
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('Author'))
    session_id = models.CharField(unique=True, null=True, max_length=32)
    proposed = models.DateTimeField(null=True, verbose_name=_('proposed'))
    applied = models.DateTimeField(null=True, verbose_name=_('applied'))
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT,
                                   related_name='applied_changesets', verbose_name=_('applied by'))

    class Meta:
        verbose_name = _('Change Set')
        verbose_name_plural = _('Change Sets')
        default_related_name = 'changesets'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_author = None
        self.changes_qs = None
        self.ever_created_objects = {}
        self.created_objects = {}
        self.updated_existing = {}
        self.deleted_existing = {}
        self.m2m_added = {}
        self.m2m_removed = {}
        self._last_change_pk = 0

    """
    Get Changesets for Request/Session/User
    """
    @classmethod
    def qs_base(cls, hide_applied=True):
        qs = cls.objects.select_related('author')
        if hide_applied:
            qs = qs.filter(applied__isnull=True)
        return qs

    @classmethod
    def qs_for_request(cls, request):
        """
        Returns a base QuerySet to get only changesets the current user is allowed to see
        """
        qs = cls.qs_base()
        if request.user.is_authenticated:
            qs = qs.filter(author=request.user)
        else:
            qs = qs.filter(author__isnull=True)
        return qs

    @classmethod
    def get_for_request(cls, request):
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
        qs = cls.qs_for_request(request)

        if request.session.session_key is not None:
            changeset = qs.filter(session_id=request.session.session_key).first()
            if changeset is not None:
                changeset.default_author = request.user
                if changeset.author_id is None and request.user.is_authenticated:
                    changeset.author = request.user
                    changeset.save()
                return changeset

        new_changeset = cls()
        new_changeset.request = request

        if request.user.is_authenticated:
            changeset = qs.filter(Q(author=request.user)).order_by('-created').first()
            if changeset is not None:
                if request.session.session_key is None:
                    request.session.save()
                changeset.session_id = request.session.session_key
                changeset.save()
                changeset.default_author = request.user
                return changeset

            new_changeset.author = request.user

        new_changeset.session_id = request.session.session_key
        new_changeset.default_author = request.user
        return new_changeset

    """
    Wrap Objects
    """
    def wrap(self, obj, author=None):
        """
        Wrap the given object in a changeset wrapper.
        :param obj: A model, a model instance or the name of a model as a string.
        :param author: Author to which ne changes will be assigned. This changesets default author (if set) if None.
        """
        self.parse_changes()
        if author is None:
            author = self.default_author
        if author is not None and not author.is_authenticated:
            author = None
        if isinstance(obj, str):
            return ModelWrapper(self, apps.get_model('mapdata', obj), author)
        if isinstance(obj, type) and issubclass(obj, models.Model):
            return ModelWrapper(self, obj, author)
        if isinstance(obj, models.Model):
            return ModelWrapper(self, type(obj), author).create_wrapped_model_class()(self, obj, author)
        raise ValueError

    """
    Parse Changes
    """
    def relevant_changes(self):
        """
        Get all changes of this queryset that have not been discarded and do not restore original data.
        You should not call this, but instead call parse_changes(), it will store the result in self.changes_qs.
        """
        qs = self.changes.filter(discarded_by__isnull=True).exclude(action='restore')
        qs = qs.exclude(action='delete', created_object_id__isnull=False)
        return qs

    def parse_changes(self, get_history=False):
        """
        Parse changes of this changeset so they can be reflected when querying data.
        Only executable once, if changes are added later they are automatically parsed.
        This method gets automatically called when parsed changes are needed or when adding a new change.
        The queryset used/created by this method can be found in changes_qs afterwards.
        :param get_history: Whether to get all changes (True) or only relevant ones (False)
        """
        if self.pk is None or self.changes_qs is not None:
            return

        if get_history:
            self.changes_qs = self.changes.all()
        else:
            self.changes_qs = self.relevant_changes()

        # noinspection PyTypeChecker
        for change in self.changes_qs:
            self._parse_change(change)

    def _parse_change(self, change):
        self._last_change_pk = change.pk

        model = change.model_class
        pk = change.obj_pk
        if change.action == 'create':
            new = {}
            self.created_objects.setdefault(model, {})[pk] = new
            self.ever_created_objects.setdefault(model, {})[pk] = new
            return
        elif change.action == 'delete':
            if not is_created_pk(pk):
                self.deleted_existing.setdefault(model, set()).add(pk)
            else:
                self.created_objects[model].pop(pk)
                self.m2m_added.get(model, {}).pop(pk, None)
                self.m2m_removed.get(model, {}).pop(pk, None)
            return

        name = change.field_name

        if change.action == 'restore' and change.field_value is None:
            if is_created_pk(pk):
                self.created_objects[model][pk].pop(name, None)
            else:
                self.updated_existing.setdefault(model, {}).setdefault(pk, {}).pop(name, None)
            return

        value = json.loads(change.field_value)
        if change.action == 'update':
            if is_created_pk(pk):
                self.created_objects[model][pk][name] = value
            else:
                self.updated_existing.setdefault(model, {}).setdefault(pk, {})[name] = value

        if change.action == 'restore':
            self.m2m_removed.get(model, {}).get(pk, {}).get(name, set()).discard(value)
            self.m2m_added.get(model, {}).get(pk, {}).get(name, set()).discard(value)
        elif change.action == 'm2m_add':
            m2m_removed = self.m2m_removed.get(model, {}).get(pk, {}).get(name, ())
            if value in m2m_removed:
                m2m_removed.remove(value)
            self.m2m_added.setdefault(model, {}).setdefault(pk, {}).setdefault(name, set()).add(value)
        elif change.action == 'm2m_remove':
            m2m_added = self.m2m_added.get(model, {}).get(pk, {}).get(name, ())
            if value in m2m_added:
                m2m_added.discard(value)
            self.m2m_removed.setdefault(model, {}).setdefault(pk, {}).setdefault(name, set()).add(value)

    """
    Analyse Changes
    """
    def get_objects(self):
        if self.changes_qs is None:
            raise TypeError

        # collect pks of relevant objects
        object_pks = {}
        for change in self.changes_qs:
            object_pks.setdefault(change.model_class, set()).add(change.obj_pk)
            model = None
            if change.action == 'update':
                if change.model_class == LocationRedirect:
                    if change.field_name == 'target':
                        object_pks.setdefault(LocationSlug, set()).add(json.loads(change.field_value))
                        continue
                elif not change.field_name.startswith('title_'):
                    field = change.model_class._meta.get_field(change.field_name)
                    model = getattr(field, 'related_model', None)
            if change.action in ('m2m_add', 'm2m_remove'):
                model = change.model_class._meta.get_field(change.field_name).related_model
            if model is not None:
                object_pks.setdefault(model, set()).add(json.loads(change.field_value))

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

        return objects

    """
    Lookup changes and created objects
    """
    def get_changed_values(self, model: models.Model, name: str) -> tuple:
        """
        Get all changes values for a specific field on existing models
        :param model: model class
        :param name: field name
        :return: returns a dictionary with primary keys as keys and new values as values
        """
        r = tuple((pk, values[name]) for pk, values in self.updated_existing.get(model, {}).items() if name in values)
        return r

    def get_created_object(self, model, pk, author=None, get_foreign_objects=False, allow_deleted=False):
        """
        Gets a created model instance.
        :param model: model class
        :param pk: primary key
        :param author: overwrite default author for changes made to that model
        :param get_foreign_objects: whether to fetch foreign objects and not just set their id to field.attname
        :param allow_deleted: return created objects that have already been deleted (needs get_history=True)
        :return: a wrapped model instance
        """
        self.parse_changes()
        if issubclass(model, ModelWrapper):
            model = model._obj

        objects = self.ever_created_objects if allow_deleted else self.created_objects

        objects = tuple(obj for obj in ((submodel, objects.get(submodel, {}).get(pk, None))
                                        for submodel in get_submodels(model)) if obj[1] is not None)
        if not objects:
            raise model.DoesNotExist
        if len(objects) > 1:
            raise model.MultipleObjectsReturned

        model, data = objects[0]

        obj = model()
        obj.pk = pk
        if hasattr(model._meta.pk, 'related_model'):
            setattr(obj, model._meta.pk.related_model._meta.pk.attname, pk)
        obj._state.adding = False

        for name, value in data.items():
            if name.startswith('title_'):
                if value:
                    obj.titles[name[6:]] = value
                continue

            field = model._meta.get_field(name)

            if field.many_to_many:
                continue

            if field.many_to_one:
                setattr(obj, field.attname, value)
                if is_created_pk(value):
                    setattr(obj, field.get_cache_name(), self.get_created_object(field.related_model, value))
                elif get_foreign_objects:
                    setattr(obj, field.get_cache_name(), self.wrap(field.related_model.objects.get(pk=value)))
                continue

            setattr(obj, name, field.to_python(value))
        return self.wrap(obj, author=author)

    def get_created_pks(self, model) -> set:
        """
        Returns a set with the primary keys of created objects from this model
        """
        if issubclass(model, ModelWrapper):
            model = model._obj
        return set(self.created_objects.get(model, {}).keys())

    """
    add changes
    """
    def _new_change(self, author, **kwargs):
        if self.pk is None:
            if self.session_id is None:
                try:
                    # noinspection PyUnresolvedReferences
                    session = self.request.session
                    if session.session_key is None:
                        session.save()
                    self.session_id = session.session_key
                except AttributeError:
                    pass  # ok, so lets keep it this way
            self.save()
        self.parse_changes()
        change = Change(changeset=self)
        change.changeset_id = self.pk
        author = self.default_author if author is None else author
        if author is not None and author.is_authenticated:
            change.author = author
        for name, value in kwargs.items():
            setattr(change, name, value)
        change.save()
        self._parse_change(change)
        return change

    def add_create(self, obj, author=None):
        """
        Creates a new object in this changeset. Called when a new ModelInstanceWrapper is saved.
        """
        change = self._new_change(author=author, action='create', model_class=type(obj._obj))
        obj.pk = 'c%d' % change.pk

    def _add_value(self, action, obj, name, value, author=None):
        return self._new_change(author=author, action=action, obj=obj, field_name=name,
                                field_value=json.dumps(value, ensure_ascii=False, cls=DjangoJSONEncoder))

    def add_restore(self, obj, name, value=None, author=None):
        """
        Restore a models field value (= remove it from the changeset).
        """
        return self._new_change(author=author, action='restore', obj=obj, field_name=name, field_value=value)

    def add_update(self, obj, name, value, author=None):
        """
        Update a models field value. Called when a ModelInstanceWrapper is saved.
        """
        if isinstance(obj, ModelInstanceWrapper):
            obj = obj._obj
        model = type(obj)
        field = model._meta.get_field('titles' if name.startswith('title_') else name)
        with transaction.atomic():
            if is_created_pk(obj.pk):
                current_obj = model()
            else:
                current_obj = model.objects.only(field.name).get(pk=obj.pk)
            try:
                current_value = getattr(current_obj, field.attname)
            except AttributeError:
                current_value = field.to_prep_value(getattr(current_obj, field.name))
            if name.startswith('title_'):
                current_value = current_value.get(name[6:], '')

            if current_value != value:
                change = self._add_value('update', obj, name, value, author)
            else:
                change = self.add_restore(obj, name, author)
            change.other_changes().filter(field_name=name).update(discarded_by=change)
        return change

    def add_m2m_add(self, obj, name, value, author=None):
        """
        Add an object to a m2m relation. Called by ManyRelatedManagerWrapper.
        """
        if isinstance(obj, ModelInstanceWrapper):
            obj = obj._obj
        with transaction.atomic():
            if is_created_pk(obj.pk) or is_created_pk(value) or not getattr(obj, name).filter(pk=value).exists():
                change = self._add_value('m2m_add', obj, name, value, author)
            else:
                change = self.add_restore(obj, name, value, author)
            change.other_changes().filter(field_name=name, field_value=change.field_value).update(discarded_by=change)
        return change

    def add_m2m_remove(self, obj, name, value, author=None):
        """
        Remove an object from a m2m reltation. Called by ManyRelatedManagerWrapper.
        """
        if isinstance(obj, ModelInstanceWrapper):
            obj = obj._obj
        with transaction.atomic():
            if is_created_pk(obj.pk) or is_created_pk(value) or not getattr(obj, name).filter(pk=value).exists():
                change = self.add_restore(obj, name, value, author)
            else:
                change = self._add_value('m2m_remove', obj, name, value, author)
            change.other_changes().filter(field_name=name, field_value=change.field_value).update(discarded_by=change)
        return change

    def add_delete(self, obj, author=None):
        """
        Delete an object. Called by ModelInstanceWrapper.delete().
        """
        with transaction.atomic():
            change = self._new_change(author=author, action='delete', obj=obj)
            change.other_changes().update(discarded_by=change)
        return change

    """
    Methods for display
    """
    @property
    def changes_count(self):
        """
        Get the number of relevant changes. Does not need a query if changes are already parsed.
        """
        if self.changes_qs is None:
            return self.relevant_changes().exclude(model_name='LocationRedirect', action='update').count()

        result = 0

        for model, objects in self.created_objects.items():
            result += len(objects)
            if model == LocationRedirect:
                continue
            result += sum(len(values) for values in objects.values())

        for objects in self.updated_existing.values():
            result += sum(len(values) for values in objects.values())

        result += sum(len(objs) for objs in self.deleted_existing.values())

        for m2m in self.m2m_added, self.m2m_removed:
            for objects in m2m.values():
                for obj in objects.values():
                    result += sum(len(values) for values in obj.values())

        return result

    @property
    def count_display(self):
        """
        Get “%d changes” display text.
        """
        if self.pk is None:
            return _('No changes')
        return ungettext_lazy('%(num)d change', '%(num)d changes', 'num') % {'num': self.changes_count}

    @property
    def title(self):
        if self.pk is None:
            return ''
        return _('Changeset #%d') % self.pk

    @property
    def cache_key(self):
        if self.pk is None:
            return None
        return str(self.pk)+'-'+str(self._last_change_pk)

    def get_absolute_url(self):
        if self.pk is None:
            return ''
        return reverse('editor.changesets.detail', kwargs={'pk': self.pk})

    def serialize(self):
        return OrderedDict((
            ('id', self.pk),
            ('author', self.author_id),
            ('created', None if self.created is None else self.created.isoformat()),
            ('proposed', None if self.proposed is None else self.proposed.isoformat()),
            ('applied', None if self.applied is None else self.applied.isoformat()),
            ('applied_by', None if self.applied_by_id is None else self.applied_by_id),
            ('changes', tuple(change.serialize() for change in self.changes.all())),
        ))
