from dataclasses import dataclass
from operator import attrgetter
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils.translation import gettext_lazy as _
from shapely import Point
from shapely.geometry import mapping

from c3nav.mapdata.forms import I18nModelFormMixin
from c3nav.mapdata.models import GraphEdge, Space
from c3nav.mapdata.models.geometry.space import RangingBeacon, LeaveDescription
from c3nav.mapdata.quests.base import register_quest, Quest, ChangeSetModelForm
from c3nav.mapdata.utils.geometry import unwrap_geom


class RangingBeaconAltitudeQuestForm(ChangeSetModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["altitude"].label = (
            _('How many meters above ground is the access point “%s” mounted?') % self.instance.title
        )

    def clean_altitude(self):
        data = self.cleaned_data["altitude"]
        if not data:
            raise ValidationError(_("The AP should not be 0m above ground."))
        return data

    class Meta:
        model = RangingBeacon
        fields = ("altitude", )

    def save(self, *args, **kwargs):
        self.instance.altitude_quest = False
        return super().save(*args, **kwargs)

    @property
    def changeset_title(self):
        return f'Altitude Quest: {self.instance.title}'


@register_quest
@dataclass
class RangingBeaconAltitudeQuest(Quest):
    quest_type = "ranging_beacon_altitude"
    quest_type_label = _('Ranging Beacon Altitude')
    form_class = RangingBeaconAltitudeQuestForm
    obj: RangingBeacon

    @property
    def point(self) -> Point:
        return mapping(self.obj.geometry)

    @classmethod
    def _qs_for_request(cls, request):
        return RangingBeacon.qs_for_request(request).select_related('space',
                                                                    'space__level').filter(altitude_quest=True)


class LeaveDescriptionQuestForm(I18nModelFormMixin, ChangeSetModelForm):
    class Meta:
        model = LeaveDescription
        fields = ("description", )

    @property
    def changeset_title(self):
        return f'LeaveDesscription Quest: {self.instance.space.title} → {self.instance.target_space.title}'


@register_quest
@dataclass
class LeaveDescriptionQuest(Quest):
    quest_type = "leave_description"
    quest_type_label = _('Leave Description')
    form_class = LeaveDescriptionQuestForm
    obj: ClassVar
    space: Space
    target_space: Space
    the_point: Point

    @property
    def quest_description(self) -> list[str]:
        return [
            _("Please provide a description to be used when leaving “%(from_space)s” towards “%(to_space)s”.") % {
                "from_space": self.space.title,
                "to_space": self.target_space.title,
            },
            _("This will be used all doors that lead from this space to the other, not just the highlighted one! "
              "So please be generic if there is more then one."),
        ]

    @property
    def point(self) -> dict:
        return mapping(self.the_point)

    @property
    def level_id(self) -> int:
        return self.space.level.on_top_of_id or self.space.level_id

    @property
    def identifier(self) -> str:
        return f"{self.space.pk}-{self.target_space.pk}"

    @classmethod
    def get_all_for_request(cls, request, space_ids: tuple[int, int] = ()):
        qs = Space.qs_for_request(request)
        if space_ids:
            qs = qs.filter(pk__in=space_ids)
        spaces = {space.pk: space for space in qs.select_related("level")}
        existing = set(tuple(item) for item in LeaveDescription.objects.values_list("space_id", "target_space_id"))
        more_filter = {} if not space_ids else {"from_node__space_id": space_ids[0], "to_node__space_id": space_ids[1]}
        edges = {
            (from_space, to_space): (from_point, to_point)
            for from_space, to_space, from_point, to_point in GraphEdge.objects.filter(
                from_node__space__in=spaces,
                to_node__space__in=spaces,
                **more_filter,
            ).exclude(
                from_node__space=F("to_node__space")
            ).values_list("from_node__space_id", "to_node__space_id", "from_node__geometry", "to_node__geometry")
            if (from_space, to_space) not in existing
        }
        return [
            cls(
                space=spaces[from_space],
                target_space=spaces[to_space],
                the_point=unwrap_geom(from_point),
            )
            for (from_space, to_space), (from_point, to_point) in edges.items()
        ]

    @classmethod
    def get_for_request(cls, request, identifier: str):
        space_ids = identifier.split('-')
        if len(space_ids) != 2 or not (space_ids[0].isdigit() and space_ids[1].isdigit()):
            return None

        results = cls.get_all_for_request(request, space_ids=tuple(int(i) for i in space_ids))
        return results[0] if results else None

    def get_form_kwargs(self, request):
        instance = LeaveDescription()
        instance.space = self.space
        instance.target_space = self.target_space
        return {"instance": instance}
