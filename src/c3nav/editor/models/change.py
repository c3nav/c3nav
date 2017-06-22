import json
import typing
from collections import OrderedDict

from django.apps import apps
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _

from c3nav.editor.utils import is_created_pk
from c3nav.editor.wrappers import ModelInstanceWrapper


class Change(models.Model):
    ACTIONS = (
        ('create', _('create object')),
        ('delete', _('delete object')),
        ('update', _('update attribute')),
        ('restore', _('restore attribute')),
        ('m2m_add', _('add many to many relation')),
        ('m2m_remove', _('add many to many relation')),
    )
    changeset = models.ForeignKey('editor.ChangeSet', on_delete=models.CASCADE, verbose_name=_('Change Set'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, verbose_name=_('Author'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    action = models.CharField(max_length=16, choices=ACTIONS, verbose_name=_('action'))
    discarded_by = models.OneToOneField('Change', null=True, on_delete=models.CASCADE, related_name='discards',
                                        verbose_name=_('discarded by other change'))
    model_name = models.CharField(max_length=50, verbose_name=_('model name'))
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
        if not self.model_name:
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
        if self.existing_object_pk is not None:
            return self.existing_object_pk
        if self.created_object_id is not None:
            return 'c'+str(self.created_object_id)
        if self.action == 'create':
            return 'c'+str(self.pk)
        raise TypeError('existing_model_pk or created_object have to be set.')

    def other_changes(self):
        """
        get queryset of other active changes on the same object
        """
        qs = self.changeset.changes.filter(~Q(pk=self.pk), model_name=self.model_name, discarded_by__isnull=True)
        if self.existing_object_pk is not None:
            return qs.filter(existing_object_pk=self.existing_object_pk)
        if self.action == 'create':
            return qs.filter(created_object_id=self.pk)
        return qs.filter(Q(pk=self.created_object_id) | Q(created_object_id=self.created_object_id))

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

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise TypeError('change objects can not be edited (use update to set discarded_by)')
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
            result += ('Update '+repr(self.model_name)+' #'+str(self.obj_pk)+': ' +
                       self.field_name+'='+self.field_value)
        elif self.action == 'restore':
            result += ('Restore '+repr(self.model_name)+' #'+str(self.obj_pk)+': '+self.field_name)
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
