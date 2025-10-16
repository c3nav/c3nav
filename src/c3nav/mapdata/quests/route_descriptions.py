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
from c3nav.mapdata.utils.geometry.generaty import good_representative_point
from c3nav.mapdata.utils.geometry.wrapped import unwrap_geom


class SpaceIdentifyableQuestForm(ChangeSetModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["identifyable"].label = _("Does this space qualify as “easily identifyable/findable”?")
        self.fields["identifyable"].help_text = ""
        self.fields["identifyable"].required = True

    class Meta:
        model = Space
        fields = ("identifyable", )

    def save(self, *args, **kwargs):
        self.instance.altitude_quest = False
        return super().save(*args, **kwargs)

    @property
    def changeset_title(self):
        return f'Altitude Quest: {self.instance.title}'


@register_quest
@dataclass
class SpaceIdentifyableQuest(Quest):
    quest_type = "space_identifyable"
    quest_type_label = _('Space identifyability')
    quest_type_icon = "beenhere"
    form_class = SpaceIdentifyableQuestForm
    obj: Space

    @property
    def quest_description(self) -> list[str]:
        return [
            _("If you are standing in any adjacent space to this one and you know that this space is named “%s”, "
              "will it be very straightforward to find it?") % self.obj.title,
            _("This applies mainly to rooms that are connected to a corridor where, if you pass their door, you will, "
              "thanks to a sign or other some other labeling, immediately able to tell that this is the door you want "
              "to go through."),
            _("Also, obviously, if this is a side room to another room, like a bathroom in a wardrobe."),
            _("If finding this space from adjacent spaces is not obvious, the answer is no."),
            _("Even if it's a bathroom or similar facility, the answer is no unless it is very obvious and easy to see"
              " where it is."),
        ]

    @property
    def point(self) -> Point:
        # todo: make this better!
        return good_representative_point(self.geometry)

    @classmethod
    def _qs_for_request(cls, request):
        return Space.objects.select_related('level').filter(identifyable=None).annotate(
            num_graph_nodes=Count('graphnodes')
        ).exclude(num_graph_nodes=0)


def get_door_edges_for_request(request, space_ids: Optional[list[int]] = None):
    qs = Space.objects.all()
    if space_ids:
        qs = qs.filter(pk__in=space_ids)
    spaces = {space.pk: space for space in qs.select_related("level")}
    existing = set(tuple(item) for item in LeaveDescription.objects.values_list("space_id", "target_space_id"))

    qs = GraphEdge.objects.filter(
        from_node__space__in=spaces,
        to_node__space__in=spaces,
        waytype=None,
    )
    if space_ids:
        qs = qs.filter(reduce(operator.or_, (Q(from_node__space_id=space_ids[i], to_node__space_id=space_ids[i+1])
                                             for i in range(len(space_ids) - 1))))
    return spaces, {
        (from_space, to_space): (from_point, to_point)
        for from_space, to_space, from_point, to_point in qs.exclude(
            from_node__space=F("to_node__space")
        ).values_list("from_node__space_id", "to_node__space_id", "from_node__geometry", "to_node__geometry")
        if (from_space, to_space) not in existing
    }


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
    quest_type_icon = "logout"
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
            _("This will be used all for all connections that lead from this space to the other, not just the "
              "highlighted one! So, if there is more than one connection between these two rooms, please be generic."),
            _("The description should make it possible to find the room exit no matter where in the room you are."),
            _("Examples: “Walk through the red door.”, „Walk through the doors with the Sign “Hall 3” above it.”"),
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
        spaces, edges = get_door_edges_for_request(request, space_ids)
        counter = Counter(from_space for from_space, to_space in edges.keys())
        return [
            cls(
                space=spaces[from_space],
                target_space=spaces[to_space],
                the_point=unwrap_geom(from_point),
            )
            for (from_space, to_space), (from_point, to_point) in edges.items()
            if spaces[to_space].identifyable is False and (space_ids or counter[from_space] > 1)
        ]

    @classmethod
    def get_for_request(cls, request, identifier: str):
        space_ids = identifier.split('-')
        if len(space_ids) != 2 or not all(i.isdigit() for i in space_ids):
            return None

        results = cls.get_all_for_request(request, space_ids=[int(i) for i in space_ids])
        result = results[0] if results else None
        if GraphEdge.objects.filter(from_node__space=result.space).exclude(to_node__space=result.space).count() < 2:
            return None
        return result

    def get_form_kwargs(self, request):
        instance = LeaveDescription()
        instance.space = self.space
        instance.target_space = self.target_space
        return {"instance": instance}


class CrossDescriptionQuestForm(I18nModelFormMixin, ChangeSetModelForm):
    class Meta:
        model = CrossDescription
        fields = ("description", )

    @property
    def changeset_title(self):
        return f'CrossDesscription Quest: {self.instance.origin_space.title} → {self.instance.space.title} → {self.instance.target_space.title}'


@register_quest
@dataclass
class CrossDescriptionQuest(Quest):
    quest_type = "cross_description"
    quest_type_label = _('Cross Description')
    quest_type_icon = "roundabout_right"
    form_class = CrossDescriptionQuestForm
    obj: ClassVar
    space: Space
    origin_space: Space
    target_space: Space
    the_point: Point

    @property
    def quest_description(self) -> list[str]:
        return [
            _("Please provide a description to be used when coming from “%(from_space)s” into “%(space)s” and exiting towardss “%(to_space)s”.") % {
                "from_space": self.origin_space.title,
                "space": self.space.title,
                "to_space": self.target_space.title,
            },
            _("This will be used combination of space connections that match this description, not just the "
              "highlighted ones! So, if there is more than connection between these two rooms, please be generic."),
            _("This description will replace the entire route descripting when passing through the room this way."),
            _("Examples: “Go straight ahead into the room right across.” “Turn right and go through the big doors.”"),
        ]

    @property
    def point(self) -> dict:
        return mapping(self.the_point)

    @property
    def level_id(self) -> int:
        return self.space.level.on_top_of_id or self.space.level_id

    @property
    def identifier(self) -> str:
        return f"{self.origin_space.pk}-{self.space.pk}-{self.target_space.pk}"

    @classmethod
    def get_all_for_request(cls, request, space_ids: Optional[list[int]] = None):
        spaces, edges = get_door_edges_for_request(request, space_ids)
        from_space_conns = {}
        for (from_space, to_space), (from_point, to_point) in edges.items():
            from_space_conns.setdefault(from_space, []).append((to_space, from_point))

        results = []
        for (origin_space, space), (first_point, origin_point) in edges.items():
            for target_space, target_point in from_space_conns.get(space, ()):
                if not (spaces[target_space].identifyable is False):
                    continue
                line = LineString([origin_point, target_point])
                the_point = line.interpolate(0.33, normalized=True) if line.length < 3 else line.interpolate(1)
                results.append(cls(
                    space=spaces[space],
                    origin_space=spaces[origin_space],
                    target_space=spaces[target_space],
                    the_point=the_point,
                ))
        return results

    @classmethod
    def get_for_request(cls, request, identifier: str):
        space_ids = identifier.split('-')
        if len(space_ids) != 3 or not (space_ids[0].isdigit() and space_ids[1].isdigit()):
            return None

        results = cls.get_all_for_request(request, space_ids=tuple(int(i) for i in space_ids))
        return results[0] if results else None

    def get_form_kwargs(self, request):
        instance = LeaveDescription()
        instance.space = self.space
        instance.origin_space = self.origin_space
        instance.target_space = self.target_space
        return {"instance": instance}
