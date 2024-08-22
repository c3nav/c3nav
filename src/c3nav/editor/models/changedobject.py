import typing
from collections import OrderedDict
from decimal import Decimal
from itertools import chain

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import CharField, DecimalField, Field, TextField
from django.utils.translation import gettext_lazy as _

from c3nav.editor.wrappers import is_created_pk
from c3nav.mapdata.fields import I18nField
from c3nav.mapdata.models.locations import LocationRedirect


class ChangedObjectManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('content_type')


class ApplyToInstanceError(Exception):
    pass


class NoopChangedObject:
    pk = None

    @classmethod
    def apply_to_instance(cls, *args, **kwargs):
        pass


class ChangedObject(models.Model):
    changeset = models.ForeignKey('editor.ChangeSet', on_delete=models.CASCADE, verbose_name=_('Change Set'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    existing_object_pk = models.PositiveIntegerField(null=True, verbose_name=_('id of existing object'))
    updated_fields = models.JSONField(default=dict, verbose_name=_('updated fields'),
                                      encoder=DjangoJSONEncoder)
    m2m_added = models.JSONField(default=dict, verbose_name=_('added m2m values'))
    m2m_removed = models.JSONField(default=dict, verbose_name=_('removed m2m values'))
    deleted = models.BooleanField(default=False, verbose_name=_('object was deleted'))

    objects = ChangedObjectManager()

    class Meta:
        verbose_name = _('Changed object')
        verbose_name_plural = _('Changed objects')
        default_related_name = 'changed_objects_set'
        base_manager_name = 'objects'
        unique_together = ('changeset', 'content_type', 'existing_object_pk')
        ordering = ['created', 'pk']

    def __repr__(self):
        return '<ChangedObject #%s on ChangeSet #%s>' % (str(self.pk), str(self.changeset_id))

    def serialize(self):
        return OrderedDict((
            ('pk', self.pk),
            ('type', self.model_class.__name__.lower()),
            ('object_pk', self.obj_pk),
            ('is_created', self.is_created),
            ('deleted', self.deleted),
            ('updated_fields', self.updated_fields),
            ('m2m_added', self.m2m_added),
            ('m2m_removed', self.m2m_removed),
        ))
