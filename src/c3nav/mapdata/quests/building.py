import operator
from collections import Counter
from dataclasses import dataclass
from functools import reduce
from typing import Optional, ClassVar

from django.db.models import Q, F, Count
from django.utils.translation import gettext_lazy as _
from shapely import Point, LineString
from shapely.geometry import mapping

from c3nav.mapdata.forms import I18nModelFormMixin
from c3nav.mapdata.models import Space, GraphEdge
from c3nav.mapdata.models.geometry.space import LeaveDescription, CrossDescription
from c3nav.mapdata.quests.base import ChangeSetModelForm, register_quest, Quest
from c3nav.mapdata.utils.geometry import unwrap_geom


class InternalRoomNumberQuestForm(ChangeSetModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["internal_room_number"].help_text = ""
        self.fields["internal_room_number"].required = True

    class Meta:
        model = Space
        fields = ("internal_room_number", )

    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)

    @property
    def changeset_title(self):
        return f'Internal Room Number Quest: {self.instance.title}'


@register_quest
@dataclass
class InternalRoomNumberQuest(Quest):
    quest_type = "internal_room_number"
    quest_type_label = _('Internal Room Number')
    quest_type_icon = "label"
    form_class = InternalRoomNumberQuestForm
    obj: Space

    @property
    def quest_description(self) -> list[str]:
        return [
            _("Find the internal room number of this space. You find it on the door sign at the bottom."),
            _("If you are sure the space has no such sign, just enter a dash."),
        ]

    @property
    def point(self) -> Point:
        return mapping(self.obj.point)

    @classmethod
    def _qs_for_request(cls, request):
        return Space.qs_for_request(request).select_related('level').filter(internal_room_number__isnull=True)
