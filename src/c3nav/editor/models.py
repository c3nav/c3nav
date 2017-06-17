import json
import typing
from collections import OrderedDict

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor, ManyToManyDescriptor
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.editor.wrappers import ModelInstanceWrapper, ModelWrapper, is_created_pk


class ChangeSet(models.Model):
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('Author'))
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
        self.parsed = False
        self.created_objects = {}
        self.updated_existing = {}
        self.deleted_existing = {}
        self.m2m_added = {}
        self.m2m_removed = {}
        self._last_change_pk = 0

    def parse_changes(self):
        if self.parsed:
            return
        for change in self.changes.all():
            self._parse_change(change)
        self.parsed = True

    def _parse_change(self, change):
        self._last_change_pk = change.pk

        if change.action == 'delchange':
            raise NotImplementedError

        model = change.model_class
        if change.action == 'create':
            self.created_objects.setdefault(model, {})[change.pk] = {}
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
        value = json.loads(change.field_value)

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

        if change.existing_object_pk is None:
            if change.action == 'update':
                self.created_objects[model][change.created_object_id][name] = value
            return

        if change.action == 'update':
            self.updated_existing.setdefault(model, {}).setdefault(pk, {})[name] = value

    def get_changed_values(self, model, name):
        r = tuple((pk, values[name]) for pk, values in self.updated_existing.get(model, {}).items() if name in values)
        return r

    def get_created_values(self, model, name):
        r = tuple((pk, values[name]) for pk, values in self.updated_existing.get(model, {}).items() if name in values)
        return r

    def get_created_object(self, model, pk, author=None, get_foreign_objects=False):
        if is_created_pk(pk):
            pk = pk[1:]
        pk = int(pk)
        self.parse_changes()
        if issubclass(model, ModelWrapper):
            model = model._obj
        obj = model()
        obj.pk = 'c'+str(pk)
        for name, value in self.created_objects[model][pk].items():
            if name.startswith('title_'):
                obj.titles[name[6:]] = value
                continue

            class_value = getattr(model, name)

            if isinstance(class_value, ManyToManyDescriptor):
                continue

            if isinstance(class_value, ForwardManyToOneDescriptor):
                field = class_value.field
                setattr(obj, field.attname, value)
                if is_created_pk(pk):
                    setattr(obj, class_value.cache_name, self.get_created_object(field.model, value))
                elif get_foreign_objects or True:
                    setattr(obj, class_value.cache_name, self.wrap(field.related_model.objects.get(pk=value)))
                continue

            setattr(obj, name, model._meta.get_field(name).to_python(value))
        return self.wrap(obj, author=author)

    def get_created_pks(self, model):
        if issubclass(model, ModelWrapper):
            model = model._obj
        return set(self.created_objects.get(model, {}).keys())

    @property
    def cache_key(self):
        return str(self.pk)+'-'+str(self._last_change_pk)

    @classmethod
    def qs_base(cls, hide_applied=True):
        qs = cls.objects.prefetch_related('changes').select_related('author')
        if hide_applied:
            qs = qs.filter(applied__isnull=True)
        return qs

    @classmethod
    def qs_for_request(cls, request):
        qs = cls.qs_base()
        if request.user.is_authenticated():
            qs = qs.filter(Q(author__isnull=True) | Q(author=request.user))
        else:
            qs = qs.filter(author__isnull=True)
        return qs

    @classmethod
    def get_for_request(cls, request):
        qs = cls.qs_for_request(request)
        changeset_pk = request.session.get('changeset_pk', None)
        if changeset_pk is not None:
            changeset = qs.filter(pk=changeset_pk).first()
            if changeset is not None:
                changeset.default_author = request.user
                if changeset.author_id is None and request.user.is_authenticated():
                    changeset.author = request.user
                    changeset.save()
                return changeset

        new_changeset = cls()

        if request.user.is_authenticated():
            changeset = qs.filter(Q(author=request.user)).order_by('-created').first()
            if changeset is not None:
                request.session['changeset_pk'] = changeset.pk
                changeset.default_author = request.user
                return changeset

            new_changeset.author = request.user

        new_changeset.save()
        request.session['changeset_pk'] = new_changeset.pk
        new_changeset.default_author = request.user
        return new_changeset

    def get_absolute_url(self):
        return reverse('editor.changesets.detail', kwargs={'pk': self.pk})

    @cached_property
    def undeleted_changes_count(self):
        return len([True for change in self.changes.all() if change.deletes_change_id is None])

    @property
    def title(self):
        return _('Changeset #%d') % self.pk

    @property
    def count_display(self):
        return ungettext_lazy('%(num)d Change', '%(num)d Changes', 'num') % {'num': self.undeleted_changes_count}

    def wrap(self, obj, author=None):
        self.parse_changes()
        if author is None:
            author = self.default_author
        if author is not None and not author.is_authenticated():
            author = None
        if isinstance(obj, str):
            return ModelWrapper(self, apps.get_model('mapdata', obj), author)
        if isinstance(obj, type) and issubclass(obj, models.Model):
            return ModelWrapper(self, obj, author)
        if isinstance(obj, models.Model):
            return ModelWrapper(self, type(obj), author).create_wrapped_model_class()(self, obj, author)
        raise ValueError

    def _new_change(self, author, **kwargs):
        self.parse_changes()
        change = Change(changeset=self)
        change.changeset_id = self.pk
        author = self.default_author if author is None else author
        if author is not None and author.is_authenticated():
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
        return self._new_change(author=author, action=action, obj=obj,
                                field_name=name, field_value=json.dumps(value, ensure_ascii=False))

    def add_update(self, obj, name, value, author=None):
        return self._add_value('update', obj, name, value, author)

    def add_m2m_add(self, obj, name, value, author=None):
        return self._add_value('m2m_add', obj, name, value, author)

    def add_m2m_remove(self, obj, name, value, author=None):
        return self._add_value('m2m_remove', obj, name, value, author)

    def add_delete(self, obj, author=None):
        return self._new_change(author=author, action='delete', obj=obj)

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


class Change(models.Model):
    ACTIONS = (
        ('delchange', _('delete change')),
        ('create', _('create object')),
        ('delete', _('delete object')),
        ('update', _('update attribute')),
        ('m2m_add', _('add many to many relation')),
        ('m2m_remove', _('add many to many relation')),
    )
    changeset = models.ForeignKey(ChangeSet, on_delete=models.CASCADE, verbose_name=_('Change Set'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('Author'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    action = models.CharField(max_length=16, choices=ACTIONS, verbose_name=_('action'))
    deletes_change = models.OneToOneField('Change', null=True, on_delete=models.CASCADE, related_name='deleted_by',
                                          verbose_name=_('deletes change'))
    model_name = models.CharField(max_length=50, null=True, verbose_name=_('model name'))
    existing_object_pk = models.PositiveIntegerField(null=True, verbose_name=_('id of existing object'))
    created_object = models.ForeignKey('Change', null=True, on_delete=models.CASCADE, related_name='changed_by',
                                       verbose_name=_('changed object'))
    field_name = models.CharField(max_length=50, null=True, verbose_name=_('field name'))
    field_value = models.TextField(null=True, verbose_name=_('new field value'))

    class Meta:
        verbose_name = _('Change')
        verbose_name_plural = _('Changes')
        default_related_name = 'changes'
        ordering = ['created', 'pk']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_object = None

    @property
    def model_class(self) -> typing.Optional[typing.Type[models.Model]]:
        if self.model_name is None:
            return None
        return apps.get_model('mapdata', self.model_name)

    @model_class.setter
    def model_class(self, value: typing.Optional[typing.Type[models.Model]]):
        if value is None:
            self.model_name = None
            return
        if not issubclass(value, models.Model):
            raise ValueError('value is not a django model')
        if value._meta.abstract:
            raise ValueError('value is an abstract model')
        if value._meta.app_label != 'mapdata':
            raise ValueError('value is not a mapdata model')
        self.model_name = value.__name__

    @property
    def obj_pk(self) -> typing.Union[int, str]:
        if self._set_object is not None:
            return self._set_object.pk
        if self.existing_object_pk is not None:
            return self.existing_object_pk
        if self.created_object_id is not None:
            return 'c'+str(self.created_object_id)
        raise TypeError('existing_model_pk or created_object have to be set.')

    @property
    def obj(self) -> ModelInstanceWrapper:
        if self._set_object is not None:
            return self._set_object

        if self.existing_object_pk is not None:
            if self.created_object is not None:
                raise TypeError('existing_object_pk and created_object can not both be set.')
            self._set_object = self.changeset.wrap(self.model_class.objects.get(pk=self.existing_object_pk))
            # noinspection PyTypeChecker
            return self._set_object
        elif self.created_object is not None:
            if self.created_object.model_class != self.model_class:
                raise TypeError('created_object model and change model do not match.')
            if self.created_object.changeset_id != self.changeset_id:
                raise TypeError('created_object belongs to a different changeset.')
            return self.changeset.get_created_object(self.model_class, self.created_object_id)
        raise TypeError('existing_model_pk or created_object have to be set.')

    @obj.setter
    def obj(self, value: typing.Union[models.Model, ModelInstanceWrapper]):
        if not isinstance(value, ModelInstanceWrapper):
            value = self.changeset.wrap(value)

        if is_created_pk(value.pk):
            if value._changeset.id != self.changeset.pk:
                raise ValueError('value is a Change instance but belongs to a different changeset.')
            self.model_class = type(value._obj)
            self.created_object = Change.objects.get(pk=value.pk[1:])
            self.created_object_id = int(value.pk[1:])
            self.existing_object_pk = None
            self._set_object = value
            return

        model_class_before = self.model_class
        self.model_class = type(value._obj) if isinstance(value, ModelInstanceWrapper) else type(value)
        if value.pk is None:
            self.model_class = model_class_before
            raise ValueError('object is not saved yet and cannot be referenced')
        self.existing_object_pk = value.pk
        self.created_object = None
        self._set_object = value

    def clean(self):
        if self.action == 'delchange':
            if self.deletes_change is None:
                raise ValidationError('deletes_change has to be set if action is delchange.')
            if self.deletes_change.changeset_id != self.changeset_id:
                raise ValidationError('deletes_change refers to a change from a different changeset.')

            for field_name in ('model_name', 'existing_object_pk', 'created_object', 'field_name', 'field_value'):
                if getattr(self, field_name) is not None:
                    raise ValidationError('%s must not be set if action is delchange.' % field_name)
            return

        if self.deletes_change is not None:
            raise ValidationError('deletes_change can only be set if action is delchange.')

        if self.model_name is None:
            raise ValidationError('model_name has to be set if action is not delchange.')

        try:
            # noinspection PyUnusedLocal
            tmp = self.model_class if self.action == 'create' else self.obj  # noqa
        except TypeError as e:
            raise ValidationError(str(e))
        except ObjectDoesNotExist:
            raise ValidationError('existing object does not exist.')

        if self.action in ('create', 'delete'):
            for field_name in ('field_name', 'field_value'):
                if getattr(self, field_name) is not None:
                    raise ValidationError('%s must not be set if action is create or delete.' % field_name)

    def save(self, *args, **kwargs):
        self.clean()
        if self.pk is not None:
            raise TypeError('change objects can not be edited.')
        if self.changeset.proposed is not None or self.changeset.applied is not None:
            raise TypeError('can not add change object to uneditable changeset.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError('change objects can not be deleted directly.')

    def __repr__(self):
        result = '<Change #%s on ChangeSet #%s: ' % (str(self.pk), str(self.changeset_id))
        if self.action == 'create':
            result += 'Create '+repr(self.model_name)
        elif self.action == 'update':
            result += ('Update object '+repr(self.model_name)+' #'+str(self.obj_pk)+': ' +
                       self.field_name+'='+self.field_value)
        elif self.action == 'delete':
            result += 'Delete object '+repr(self.model_name)+' #'+str(self.obj_pk)
        elif self.action == 'm2m_add':
            result += ('Update (m2m) object '+repr(self.model_name)+' #'+str(self.obj_pk)+': ' +
                       self.field_name+'.add('+self.field_value+')')
        elif self.action == 'm2m_remove':
            result += ('Update (m2m) object '+repr(self.model_name)+' #'+str(self.obj_pk)+': ' +
                       self.field_name+'.remove('+self.field_value+')')
        result += '>'
        return result

    def serialize(self):
        result = OrderedDict((
            ('id', self.pk),
            ('author', self.author_id),
            ('created', None if self.created is None else self.created.isoformat()),
            ('action', self.action),
            ('object_type', self.model_class.__name__.lower()),
            ('object_id', ('c'+str(self.pk)) if self.action == 'create' else self.obj_pk),
        ))
        if self.action in ('update', 'm2m_add', 'm2m_remove'):
            result.update(OrderedDict((
                ('name', self.field_name),
                ('value', json.loads(self.field_value)),
            )))
        return result
