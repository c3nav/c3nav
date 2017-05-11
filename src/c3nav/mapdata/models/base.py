from collections import OrderedDict

from django.db import models

EDITOR_FORM_MODELS = OrderedDict()


class SerializableMixin(models.Model):
    class Meta:
        abstract = True

    def serialize(self, **kwargs):
        return self._serialize(**kwargs)

    @classmethod
    def serialize_type(cls, **kwargs):
        return OrderedDict((
            ('name', cls.__name__.lower()),
            ('name_plural', cls._meta.default_related_name),
            ('title', str(cls._meta.verbose_name)),
            ('title_plural', str(cls._meta.verbose_name_plural)),
        ))

    def _serialize(self, include_type=False, **kwargs):
        result = OrderedDict()
        if include_type:
            result['type'] = self.__class__.__name__.lower()
        result['id'] = self.id
        return result


class EditorFormMixin(SerializableMixin, models.Model):
    EditorForm = None

    class Meta:
        abstract = True
