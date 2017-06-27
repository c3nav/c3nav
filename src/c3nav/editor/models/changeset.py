from collections import OrderedDict
from itertools import chain
from operator import attrgetter

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Max, Q
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.editor.models.changedobject import ChangedObject
from c3nav.editor.utils import is_created_pk
from c3nav.editor.wrappers import ModelWrapper
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
        self.changed_objects = None

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
                return changeset

            new_changeset.author = request.user

        new_changeset.session_id = request.session.session_key
        return new_changeset

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
        if issubclass(model, ModelWrapper):
            model = model._obj
        return set(self.created_objects.get(model, {}).keys())

    """
    Methods for display
    """
    @property
    def changed_objects_count(self):
        """
        Get the number of changed objects. Does not need a query if cache is already filled.
        """
        if self.changed_objects is None:
            location_redirect_type = ContentType.objects.get_for_model(LocationRedirect)
            return self.relevant_changed_objects().exclude(content_type=location_redirect_type).count()

        return sum((len(objects) for model, objects in self.changed_objects.items() if model != LocationRedirect))

    @property
    def count_display(self):
        """
        Get “%d changed objects” display text.
        """
        if self.pk is None:
            return _('No changed objects')
        return (ungettext_lazy('%(num)d changed object', '%(num)d changed objects', 'num') %
                {'num': self.changed_objects_count})

    @property
    def title(self):
        if self.pk is None:
            return ''
        return _('Changeset #%d') % self.pk

    @property
    def last_update(self):
        if self.changed_objects is None:
            return self.relevant_changed_objects().aggregate(Max('last_update'))['last_update__max']

        return max(chain(*self.changed_objects.values()), key=attrgetter('last_update'))

    @property
    def cache_key(self):
        if self.pk is None:
            return None
        return str(self.pk)+'-'+str(self.last_update)

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
