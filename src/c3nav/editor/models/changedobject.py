import typing
from collections import OrderedDict
from decimal import Decimal
from itertools import chain

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import CharField, DecimalField, Field, TextField
from django.utils.translation import gettext_lazy as _

from c3nav.editor.wrappers import ModelInstanceWrapper, is_created_pk
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

    def __init__(self, *args, model_class=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_object = None
        self._m2m_added_cache = {name: set(values) for name, values in self.m2m_added.items()}
        self._m2m_removed_cache = {name: set(values) for name, values in self.m2m_removed.items()}
        if model_class is not None:
            self.model_class = model_class
        for field in self.model_class._meta.get_fields():
            if field.name in self.updated_fields and isinstance(field, DecimalField):
                self.updated_fields[field.name] = Decimal(self.updated_fields[field.name])

    @property
    def model_class(self) -> typing.Optional[typing.Type[models.Model]]:
        return self.content_type.model_class()

    @model_class.setter
    def model_class(self, value: typing.Optional[typing.Type[models.Model]]):
        self.content_type = ContentType.objects.get_for_model(value)

    @property
    def obj_pk(self) -> typing.Union[int, str]:
        if not self.is_created:
            return self.existing_object_pk
        return 'c'+str(self.pk)

    @property
    def obj(self) -> ModelInstanceWrapper:
        return self.get_obj(get_foreign_objects=True)

    @property
    def is_created(self):
        return self.existing_object_pk is None

    def get_obj(self, get_foreign_objects=False) -> ModelInstanceWrapper:
        model = self.model_class

        if not self.is_created:
            if self._set_object is None:
                try:
                    obj = model.objects.get(pk=self.existing_object_pk)
                except model.DoesNotExist:
                    obj = model(pk=self.existing_object_pk)
                self._set_object = self.changeset.wrap_instance(obj)

            # noinspection PyTypeChecker
            return self._set_object

        pk = self.obj_pk

        obj = model()
        obj.pk = pk
        if model._meta.pk.is_relation:
            setattr(obj, model._meta.pk.related_model._meta.pk.attname, pk)
        obj._state.adding = False
        return self.changeset.wrap_instance(obj)

    def add_relevant_object_pks(self, object_pks, many=True):
        object_pks.setdefault(self.model_class, set()).add(self.obj_pk)
        for name, value in self.updated_fields.items():
            if '__i18n__' in name:
                continue
            field = self.model_class._meta.get_field(name)
            if field.is_relation:
                object_pks.setdefault(field.related_model, set()).add(value)

        if many:
            for name, value in chain(self._m2m_added_cache.items(), self._m2m_removed_cache.items()):
                field = self.model_class._meta.get_field(name)
                object_pks.setdefault(field.related_model, set()).update(value)

    def update_changeset_cache(self):
        if self.pk is None:
            return

        model = self.model_class
        pk = self.obj_pk

        self.changeset.changed_objects.setdefault(model, {})[pk] = self

        if self.is_created:
            if not self.deleted:
                self.changeset.created_objects.setdefault(model, {})[pk] = self.updated_fields
        else:
            if not self.deleted:
                self.changeset.updated_existing.setdefault(model, {})[pk] = self.updated_fields
                self.changeset.deleted_existing.setdefault(model, set()).discard(pk)
            else:
                self.changeset.updated_existing.setdefault(model, {}).pop(pk, None)
                self.changeset.deleted_existing.setdefault(model, set()).add(pk)

        if not self.deleted:
            self.changeset.m2m_added.setdefault(model, {})[pk] = self._m2m_added_cache
            self.changeset.m2m_removed.setdefault(model, {})[pk] = self._m2m_removed_cache
        else:
            self.changeset.m2m_added.get(model, {}).pop(pk, None)
            self.changeset.m2m_removed.get(model, {}).pop(pk, None)

    def apply_to_instance(self, instance: ModelInstanceWrapper, created_pks=None):
        for name, value in self.updated_fields.items():
            if '__i18n__' in name:
                name, i18n, lang = name.split('__')
                field = instance._meta.get_field(name)
                if not value:
                    getattr(instance, field.attname).pop(lang, None)
                else:
                    getattr(instance, field.attname)[lang] = value
                continue

            field = instance._meta.get_field(name)
            if not field.is_relation:
                setattr(instance, field.name, field.to_python(value))
            elif field.many_to_one or field.one_to_one:
                if is_created_pk(value):
                    if created_pks is None:
                        try:
                            obj = self.changeset.get_created_object(field.related_model, value, allow_deleted=True)
                        except field.related_model.DoesNotExist:
                            pass
                        else:
                            setattr(instance, field.get_cache_name(), obj)
                    else:
                        try:
                            delattr(instance, field.get_cache_name())
                        except AttributeError:
                            pass
                        try:
                            value = created_pks[field.related_model][value]
                        except KeyError:
                            raise ApplyToInstanceError
                else:
                    try:
                        delattr(instance, field.get_cache_name())
                    except AttributeError:
                        pass
                setattr(instance, field.attname, value)
            else:
                raise NotImplementedError

    def clean_updated_fields(self, objects=None):
        if self.is_created:
            current_obj = self.model_class()
        elif objects is not None:
            current_obj = objects[self.model_class][self.existing_object_pk]
        else:
            current_obj = self.model_class.objects.get(pk=self.existing_object_pk)

        delete_fields = set()
        for name, new_value in self.updated_fields.items():
            if '__i18n__' in name:
                orig_name, i18n, lang = name.split('__')
                field = self.model_class._meta.get_field(orig_name)
                current_value = getattr(current_obj, field.attname).get(lang, '')
            else:
                field = self.model_class._meta.get_field(name)

                if not field.is_relation:
                    current_value = field.get_prep_value(getattr(current_obj, field.name))
                elif field.many_to_one or field.one_to_one:
                    current_value = getattr(current_obj, field.attname)
                else:
                    raise NotImplementedError

            if current_value == new_value:
                delete_fields.add(name)

        self.updated_fields = {name: value for name, value in self.updated_fields.items() if name not in delete_fields}
        return delete_fields

    def handle_deleted_object_pks(self, deleted_object_pks):
        if self.obj_pk in deleted_object_pks[self.model_class]:
            self.delete()
            return False

        for name, value in self.updated_fields.items():
            if '__i18n__' in name:
                continue
            field = self.model_class._meta.get_field(name)
            if field.is_relation:
                if value in deleted_object_pks[field.related_model]:
                    deleted_object_pks[self.model_class].add(self.obj_pk)
                    self.delete()
                    return False

        changed = False
        for name, value in chain(self._m2m_added_cache.items(), self._m2m_removed_cache.items()):
            field = self.model_class._meta.get_field(name)
            if deleted_object_pks[field.related_model] & value:
                value.difference_update(deleted_object_pks[field.related_model])
                changed = True

        return changed

    def save_instance(self, instance):
        old_updated_fields = self.updated_fields
        self.updated_fields = {}

        if instance.pk is None and self.model_class == LocationRedirect and not is_created_pk(instance.target_id):
            obj = LocationRedirect.objects.filter(pk__in=self.changeset.deleted_existing.get(LocationRedirect, ()),
                                                  slug=instance.slug, target_id=instance.target_id).first()
            if obj is not None:
                self.changeset.get_changed_object(obj).restore()
                return

        for field in self.model_class._meta.get_fields():
            if not isinstance(field, Field) or field.primary_key:
                continue

            elif not field.is_relation:
                value = getattr(instance, field.attname)
                if isinstance(field, I18nField):
                    for lang, subvalue in value.items():
                        self.updated_fields['%s__i18n__%s' % (field.name, lang)] = subvalue
                elif isinstance(field, (CharField, TextField)):
                    self.updated_fields[field.name] = None if field.null and not value else field.get_prep_value(value)
                else:
                    self.updated_fields[field.name] = field.get_prep_value(value)
            elif field.many_to_one or field.one_to_one:
                try:
                    value = getattr(instance, field.get_cache_name())
                except AttributeError:
                    value = getattr(instance, field.attname)
                else:
                    value = None if value is None else value.pk
                self.updated_fields[field.name] = value

        self.clean_updated_fields()
        for name, value in self.updated_fields.items():
            if old_updated_fields.get(name, None) != value:
                self.changeset._object_changed = True
                break
        self.save()
        if instance.pk is None and self.pk is not None:
            instance.pk = self.obj_pk

    def can_delete(self):
        for field in self.model_class._meta.get_fields():
            if not field.one_to_many:
                continue
            related_model = field.related_model
            if related_model._meta.app_label != 'mapdata':
                continue
            if related_model.__name__ in ('AccessPermission', 'Report'):
                continue
            kwargs = {field.field.name+'__pk': self.obj_pk}
            if self.changeset.wrap_model(related_model).objects.filter(**kwargs).exists():
                return False
        return True

    def get_unique_collisions(self, max_one=False):
        result = set()
        if not self.deleted:
            return result
        uniques = tuple(self.model_class._meta.unique_together)
        uniques += tuple((field.name, )
                         for field in self.model_class._meta.get_fields()
                         if field.related_model is None and field.unique and not field.primary_key)
        for unique in uniques:
            names = tuple((name if self.model_class._meta.get_field(name).related_model is None else name+'__pk')
                          for name in unique)
            values = tuple(getattr(self.obj, self.model_class._meta.get_field(name).attname) for name in unique)
            if None in values:
                continue
            if self.changeset.wrap_model(self.model_class).objects.filter(**dict(zip(names, values))).exists():
                result |= set(unique)
                if result and max_one:
                    return result
        return result

    def get_missing_dependencies(self, force_query=False, max_one=False):
        result = set()
        if not self.deleted:
            return result
        for field in self.model_class._meta.get_fields():
            if not field.many_to_one:
                continue
            if field.name not in self.updated_fields:
                continue
            related_model = field.related_model
            if related_model._meta.app_label != 'mapdata':
                continue

            pk = self.updated_fields[field.name]

            if force_query:
                # query here to avoid a race condition
                related_content_type = ContentType.objects.get_for_model(related_model)
                qs = self.changeset.changed_objects_set.filter(content_type=related_content_type)
                if is_created_pk(pk):
                    if not qs.filter(pk=int(pk[1:]), deleted=False).exists():
                        result.add(field.name)
                else:
                    if qs.filter(existing_object_pk=pk, deleted=True).exists():
                        result.add(field.name)
            else:
                if is_created_pk(pk):
                    if pk not in self.changeset.created_objects.get(related_model, ()):
                        result.add(field.name)
                else:
                    if pk in self.changeset.deleted_existing.get(related_model, ()):
                        result.add(field.name)

            if result and max_one:
                return result

        return result

    def mark_deleted(self):
        if not self.can_delete():
            return False
        self.changeset._object_changed = True
        self.deleted = True
        self.save()
        return True

    def clean_m2m(self, objects):
        current_obj = objects[self.model_class][self.obj_pk]
        changed = False
        for name in set(self._m2m_added_cache.keys()) | set(self._m2m_removed_cache.keys()):
            changed = changed or self.m2m_set(name, obj=self.changeset.wrap_instance(current_obj))
        return changed

    def m2m_set(self, name, set_pks=None, obj=None):
        if obj is not None:
            pks = set(related_obj.pk for related_obj in getattr(obj, name).all())
        elif not self.is_created:
            field = self.model_class._meta.get_field(name)
            rel_name = field.remote_field.related_name
            pks = set(field.related_model.objects.filter(**{rel_name+'__pk': self.obj_pk}).values_list('pk', flat=True))
        else:
            pks = set()

        m2m_added_before = self._m2m_added_cache.get(name, set())
        m2m_removed_before = self._m2m_removed_cache.get(name, set())

        if set_pks is None:
            self._m2m_added_cache.get(name, set()).difference_update(pks)
            self._m2m_removed_cache.get(name, set()).intersection_update(pks)
        else:
            self._m2m_added_cache[name] = set_pks - pks
            self._m2m_removed_cache[name] = pks - set_pks

        if not self._m2m_added_cache.get(name, set()):
            self._m2m_added_cache.pop(name, None)
        if not self._m2m_removed_cache.get(name, set()):
            self._m2m_removed_cache.pop(name, None)

        if (m2m_added_before != self._m2m_added_cache.get(name, set()) or
                m2m_removed_before != self._m2m_removed_cache.get(name, set())):
            self.changeset._object_changed = True
            self.save()
            return True
        return False

    def m2m_add(self, name, pks: set):
        self._m2m_added_cache.setdefault(name, set()).update(pks)
        self._m2m_removed_cache.setdefault(name, set()).difference_update(pks)
        self.m2m_set(name)

    def m2m_remove(self, name, pks: set):
        self._m2m_removed_cache.setdefault(name, set()).update(pks)
        self._m2m_added_cache.setdefault(name, set()).difference_update(pks)
        self.m2m_set(name)

    def restore(self):
        if self.deleted is False:
            return
        if self.get_missing_dependencies(force_query=True, max_one=True) or self.get_unique_collisions(max_one=True):
            raise PermissionError
        self.deleted = False
        self.save(standalone=True)

    @property
    def does_something(self):
        return (self.updated_fields or self._m2m_added_cache or self._m2m_removed_cache or self.is_created or
                (not self.is_created and self.deleted))

    def save(self, *args, standalone=False, **kwargs):
        self.m2m_added = {name: tuple(values) for name, values in self._m2m_added_cache.items()}
        self.m2m_removed = {name: tuple(values) for name, values in self._m2m_removed_cache.items()}
        if not self.does_something:
            if self.pk:
                self.delete()
        else:
            self.changeset._object_changed = True
            if not standalone and self.changeset.pk is None:
                self.changeset.save()
                self.changeset = self.changeset
        if self.does_something:
            super().save(*args, **kwargs)
        if not standalone and not self.changeset.fill_changes_cache():
            self.update_changeset_cache()

    def delete(self, **kwargs):
        self.changeset._object_changed = True
        super().delete(**kwargs)

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
