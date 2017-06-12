import typing

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.db.models import Q
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.editor.wrappers import ModelInstanceWrapper, ModelWrapper


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

    @classmethod
    def qs_base(cls):
        return cls.objects.prefetch_related('changes').select_related('author')

    @classmethod
    def get_for_request(cls, request):
        qs_base = cls.qs_base().filter(applied__isnull=True)
        changeset_pk = request.session.get('changeset_pk', None)
        if changeset_pk is not None:
            if request.user.is_authenticated():
                qs = qs_base.filter(Q(author__isnull=True) | Q(author=request.user))
            else:
                qs = qs_base.filter(author__isnull=True)

            changeset = qs.filter(pk=changeset_pk).first()
            if changeset is not None:
                changeset.default_author = request.user
                if changeset.author_id is None and request.user.is_authenticated():
                    changeset.author = request.user
                    changeset.save()
                return changeset

        new_changeset = cls()

        if request.user.is_authenticated():
            changeset = qs_base.filter(Q(author=request.user)).order_by('-created').first()
            if changeset is not None:
                request.session['changeset_pk'] = changeset.pk
                changeset.default_author = request.user
                return changeset

            new_changeset.author = request.user

        new_changeset.save()
        request.session['changeset_pk'] = new_changeset.pk
        new_changeset.default_author = request.user
        return new_changeset

    @cached_property
    def undeleted_changes_count(self):
        return len([True for change in self.changes.all() if change.deletes_change_id is None])

    @property
    def count_display(self):
        return ungettext_lazy('%(num)d Change', '%(num)d Changes', 'num') % {'num': self.undeleted_changes_count}

    def wrap(self, obj, author=None):
        if author is None:
            author = self.default_author
        if not author.is_authenticated():
            author = None
        if isinstance(obj, str):
            return ModelWrapper(self, apps.get_model('mapdata', obj), author)
        if issubclass(obj, models.Model):
            return ModelWrapper(self, obj, author)
        if isinstance(obj, models.Model):
            return ModelInstanceWrapper(self, obj, author)
        raise ValueError

    def _new_change(self, author, **kwargs):
        change = Change(changeset=self)
        change.changeset_id = self.pk
        if author is not None and author.is_authenticated():
            change.author = author
        for name, value in kwargs.items():
            setattr(change, name, value)
        print(repr(change))
        return change

    def add_create(self, author, model_class):
        return self._new_change(author, action='create', model_class=model_class)

    def add_update(self, author, obj, name, value):
        return self._new_change(author, action='update', obj=obj, field_name=name, field_value=str(value))

    def add_delete(self, author, obj):
        return self._new_change(author, action='delete', obj=obj)

    def update_object(self, author, obj, values):
        if not values:
            return
        for name, value in values.items():
            self.add_update(author, obj, name, value)


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_object = None

    @property
    def model_class(self) -> typing.Type[models.Model]:
        if self.model_name is None:
            raise TypeError('model_name is not set, can not get model')
        return apps.get_model('mapdata', self.model_name)

    @model_class.setter
    def model_class(self, value: typing.Type[models.Model]):
        if not issubclass(value, models.Model):
            raise ValueError('value is not a django model')
        if value._meta.abstract:
            raise ValueError('value is an abstract model')
        if value._meta.app_label != 'mapdata':
            raise ValueError('value is not a mapdata model')
        self.model_name = value.__name__

    @property
    def obj(self) -> models.Model:
        if self.existing_object_pk is not None:
            if self.created_object is not None:
                raise TypeError('existing_object_pk and created_object can not both be set.')
            if self._set_object is not None:
                if isinstance(self._set_object, self.model_class) and self._set_object.pk != self.existing_object_pk:
                    return self._set_object
                self._set_object = None
            self._set_object = self.model_class.objects.get(pk=self.existing_object_pk)
            return self._set_object
        elif self.created_object is not None:
            if self.created_object.model_class != self.model_class:
                raise TypeError('created_object model and change model do not match.')
            if self.created_object.changeset_id != self.changeset_id:
                raise TypeError('created_object belongs to a different changeset.')
            return self.created_object
        raise TypeError('existing_model_pk or created_object have to be set.')

    @obj.setter
    def obj(self, value: models.Model):
        if isinstance(value, Change):
            if value.changeset_id != self.changeset_id:
                raise ValueError('value is a Change instance but belongs to a different changeset.')
            if value.action != 'create':
                raise ValueError('value is a Change instance but has action not set to create')
            self.model_class = value.model_class
            self.created_object = value
            self.created_object_id = value.pk
            self.existing_object_pk = None
            return

        model_class_before = self.model_class
        self.model_class = value.__class__
        if value.pk is None:
            self.model_class = model_class_before
            raise ValueError('object is not saved yet and cannot be referenced')
        self.existing_object_pk = value.pk
        self.created_object = None

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
        self.full_clean()
        if self.pk is not None:
            raise TypeError('change objects can not be edited.')
        if self.changeset.proposed is not None or self.changeset.applied is not None:
            raise TypeError('can not add change object to uneditable changeset.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError('change objects can not be deleted directly.')

    def __repr__(self):
        result = '<Change on ChangeSet #'+str(self.changeset_id)+': '
        if self.action == 'create':
            result += 'Create object of type '+repr(self.model_class)
        elif self.action == 'update':
            result += 'Update object '+repr(self.obj)+': '+self.field_name+'='+self.field_value
        elif self.action == 'delete':
            result += 'Delete object '+repr(self.obj)
        result += '>'
        return result
