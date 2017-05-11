from collections import OrderedDict

from django.db import models

EDITOR_FORM_MODELS = OrderedDict()


class EditorFormMixin(models.Model):
    EditorForm = None

    class Meta:
        abstract = True

    def serialize(self, **kwargs):
        return self._serialize(**kwargs)

    def _serialize(self, include_type=False, **kwargs):
        result = OrderedDict()
        if include_type:
            result['type'] = self.__class__.__name__.lower()
        result['id'] = self.id
        return result
