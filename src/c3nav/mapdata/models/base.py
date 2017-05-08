from collections import OrderedDict

from django.db import models
from django.db.models.base import ModelBase
from django.utils.translation import get_language

from c3nav.mapdata.lastupdate import set_last_mapdata_update

FEATURE_TYPES = OrderedDict()


class EditorFormMixin():
    EditorForm = None

    @property
    def title(self):
        if not hasattr(self, 'titles'):
            return self.name
        lang = get_language()
        if lang in self.titles:
            return self.titles[lang]
        return next(iter(self.titles.values())) if self.titles else self.name
