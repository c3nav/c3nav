from collections import OrderedDict

from django.db import models

EDITOR_FORM_MODELS = OrderedDict()


class EditorFormMixin(models.Model):
    EditorForm = None

    class Meta:
        abstract = True
