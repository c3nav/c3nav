import json
from collections import OrderedDict

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.db.models import Q
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor, ManyToManyDescriptor
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.editor.models.change import Change
from c3nav.editor.wrappers import ModelWrapper, is_created_pk
from c3nav.mapdata.models import LocationSlug
from c3nav.mapdata.models.locations import LocationRedirect


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
        qs = cls.qs_base()
        if request.user.is_authenticated:
            qs = qs.filter(author=request.user)
        else:
            qs = qs.filter(author__isnull=True)
        return qs

    @classmethod
    def get_for_request(cls, request):
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
        qs = self.changes.filter(discarded_by__isnull=True).exclude(action='restore')
        qs = qs.exclude(action='delete', created_object_id__isnull=False)
        return qs

    def parse_changes(self, get_history=False):
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
        if change.action == 'create':
            new = {}
            self.created_objects.setdefault(model, {})[change.pk] = new
            self.ever_created_objects.setdefault(model, {})[change.pk] = new
            return
        elif change.action == 'delete':
            if change.existing_object_pk is not None:
                self.deleted_existing.setdefault(model, set()).add(change.existing_object_pk)
            else:
                self.created_objects[model].pop(change.created_object_id)
                self.m2m_added.get(model, {}).pop('c'+str(change.created_object_id), None)
                self.m2m_removed.get(model, {}).pop('c'+str(change.created_object_id), None)
            return

        pk = change.obj_pk
        name = change.field_name

        if change.action == 'restore':
            if change.existing_object_pk is None:
                self.created_objects[model][change.created_object_id].pop(name, None)
            else:
                self.updated_existing.setdefault(model, {}).setdefault(pk, {}).pop(name, None)

        value = json.loads(change.field_value)
        if change.action == 'update':
            if change.existing_object_pk is None:
                self.created_objects[model][change.created_object_id][name] = value
            else:
                self.updated_existing.setdefault(model, {}).setdefault(pk, {})[name] = value

        if change.action == 'm2m_add':
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
    def get_changed_values(self, model, name):
        r = tuple((pk, values[name]) for pk, values in self.updated_existing.get(model, {}).items() if name in values)
        return r

    def get_created_object(self, model, pk, author=None, get_foreign_objects=False, allow_deleted=False):
        if is_created_pk(pk):
            pk = pk[1:]
        pk = int(pk)
        self.parse_changes()
        if issubclass(model, ModelWrapper):
            model = model._obj

        objects = self.ever_created_objects if allow_deleted else self.created_objects

        objects = tuple(obj for obj in ((submodel, objects.get(submodel, {}).get(pk, None))
                                        for submodel in ModelWrapper.get_submodels(model)) if obj[1] is not None)
        if not objects:
            raise model.DoesNotExist
        if len(objects) > 1:
            raise model.MultipleObjectsReturned

        model, data = objects[0]

        obj = model()
        obj.pk = 'c' + str(pk)
        if hasattr(model._meta.pk, 'related_model'):
            setattr(obj, model._meta.pk.related_model._meta.pk.attname, obj.pk)
        obj._state.adding = False

        for name, value in data.items():
            if name.startswith('title_'):
                if value:
                    obj.titles[name[6:]] = value
                continue

            class_value = getattr(model, name)

            if isinstance(class_value, ManyToManyDescriptor):
                continue

            if isinstance(class_value, ForwardManyToOneDescriptor):
                field = class_value.field
                setattr(obj, field.attname, value)
                if is_created_pk(value):
                    setattr(obj, class_value.cache_name, self.get_created_object(field.related_model, value))
                elif get_foreign_objects:
                    setattr(obj, class_value.cache_name, self.wrap(field.related_model.objects.get(pk=value)))
                continue

            setattr(obj, name, model._meta.get_field(name).to_python(value))
        return self.wrap(obj, author=author)

    def get_created_pks(self, model):
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
        change = self._new_change(author=author, action='create', model_class=type(obj._obj))
        obj.pk = 'c%d' % change.pk

    def _add_value(self, action, obj, name, value, author=None):
        return self._new_change(author=author, action=action, obj=obj, field_name=name,
                                field_value=json.dumps(value, ensure_ascii=False, cls=DjangoJSONEncoder))

    def add_update(self, obj, name, value, author=None):
        with transaction.atomic():
            change = self._add_value('update', obj, name, value, author)
            change.other_changes().filter(field_name=name).update(discarded_by=change)
        return change

    def add_restore(self, obj, name, author=None):
        with transaction.atomic():
            change = self._new_change(author=author, action='restore', obj=obj, field_name=name)
            change.other_changes().filter(field_name=name).update(discarded_by=change)
        return change

    def add_m2m_add(self, obj, name, value, author=None):
        with transaction.atomic():
            change = self._add_value('m2m_add', obj, name, value, author)
            change.other_changes().filter(field_name=name, field_value=change.field_value).update(discarded_by=change)
        return change

    def add_m2m_remove(self, obj, name, value, author=None):
        with transaction.atomic():
            change = self._add_value('m2m_remove', obj, name, value, author)
            change.other_changes().filter(field_name=name, field_value=change.field_value).update(discarded_by=change)
        return change

    def add_delete(self, obj, author=None):
        with transaction.atomic():
            change = self._new_change(author=author, action='delete', obj=obj)
            change.other_changes().update(discarded_by=change)
        return change

    """
    Methods for display
    """
    @property
    def changes_count(self):
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
