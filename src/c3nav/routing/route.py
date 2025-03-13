# flake8: noqa
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence, Optional, NamedTuple, Union

import numpy as np
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.models import Location
from c3nav.mapdata.schemas.locations import LocationProtocol
from c3nav.mapdata.schemas.model_base import LocationPoint
from c3nav.mapdata.locations import LocationManager
from c3nav.routing.models import RouteOptions

if TYPE_CHECKING:
    from c3nav.routing.router import Router, RouterNode, RouterEdge, RouterNodeAndEdge, RouterSpace, RouterLevel


def describe_location(location: LocationProtocol) -> LocationProtocol:
    if isinstance(location, Location) and hasattr(location, "can_describe") and location.can_describe:
        final_location = LocationManager.get_visible().get(location.pk)
        if final_location is not None:
            location = final_location
    return location


class RouteNodeWithOptionalEdge(NamedTuple):
    node: Union[int, "RouterNode"]
    edge: Optional["RouterEdge"]


@dataclass
class RouteLocation:
    location: LocationProtocol
    point: Optional[LocationPoint]  # point of the actual target
    dotted: bool


@dataclass
class Route:
    router: "Router"
    origin: RouteLocation
    destination: RouteLocation
    path_nodes: Sequence[int]
    options: RouteOptions
    origin_addition: Optional["RouterNodeAndEdge"]
    destination_addition: Optional["RouterNodeAndEdge"]
    origin_xyz: np.ndarray | None
    destination_xyz: np.ndarray | None

    def get_end_distance(self, node_with_edge: RouteNodeWithOptionalEdge, xyz: tuple[float, float, float]):
        if xyz is None:
            return 0
        node = (
            node_with_edge.node
            if isinstance(node_with_edge.node, RouterNode)
            else self.router.nodes[node_with_edge.node]
        )
        return np.linalg.norm(node.xyz - xyz)

    def serialize(self):  # todo: move this into schema
        nodes: list[RouteNodeWithOptionalEdge] = [
            RouteNodeWithOptionalEdge(node=node, edge=None) for node in self.path_nodes
        ]
        if self.origin_addition and any(self.origin_addition):
            nodes.insert(0, RouteNodeWithOptionalEdge(node=self.origin_addition.node, edge=None))
            nodes[1] = RouteNodeWithOptionalEdge(node=nodes[1].node, edge=self.origin_addition.edge)
        if self.destination_addition and any(self.destination_addition):
            nodes.append(
                RouteNodeWithOptionalEdge(node=self.destination_addition.node, edge=self.destination_addition.edge)
            )

        # calculate distances from origin and destination to the origin and destination nodes
        origin_distance = self.get_end_distance(nodes[0], self.origin_xyz)
        destination_distance = self.get_end_distance(nodes[-1], self.destination_xyz)

        items: deque[RouteItem] = deque()
        last_node = None
        last_item = None
        walk_factor = self.options.walk_factor
        distance = origin_distance
        duration = origin_distance * walk_factor
        for i, (node, edge) in enumerate(nodes):
            if edge is None:
                edge = self.router.edges[last_node, node] if last_node else None
            node_obj = self.router.nodes[node] if isinstance(node, (int, np.int32, np.int64)) else node
            item = RouteItem(self, node_obj, edge, last_item)
            if edge:
                distance += edge.distance
                duration += item.router_waytype.get_duration(edge, walk_factor)
            items.append(item)
            last_item = item
            last_node = node

        distance += destination_distance
        duration += destination_distance * walk_factor

        # descriptions for waytypes
        next_item = None
        last_primary_level = None
        for item in reversed(items):
            icon = 'arrow'
            if not item.level.on_top_of_id:
                last_primary_level = item.level
            if item.waytype:
                icon = item.waytype.icon_name or 'arrow'
                if item.waytype.join_edges and next_item and next_item.waytype == item.waytype:
                    continue
                if item.waytype.icon_name:
                    icon = item.waytype.icon_name
                    if item.waytype.up_separate:
                        icon += '-up' if item.edge.rise > 0 else '-down'
                icon += '.svg'
                description = item.waytype.description
                if item.waytype.up_separate and item.edge.rise > 0:
                    description = item.waytype.description_up
                # noinspection PyComparisonWithNone
                if (item.waytype.level_change_description != False and last_primary_level and
                        ((item.last_item and item.level != item.last_item.level) or
                         item.level.on_top_of_id)):  # != False because it's lazy
                    level_change_description = (
                        str(item.waytype.level_change_description).replace('{level}', str(last_primary_level.title))
                    )
                    description = str(description).replace(
                        '{level_change_description}', ' ' + level_change_description + ' '
                    ).replace('  ', ' ').replace(' .', '.')
                    last_primary_level = None
                else:
                    description = description.replace('{level_change_description}', '')
                item.descriptions.append((icon, description))
            next_item = item

        # add space transfer descriptions
        last_space = None
        current_space = None
        for item in items:
            if item.new_space:
                next_space = item.space
                if item.last_item and not item.descriptions:
                    description = None
                    if last_space:
                        description = current_space.cross_descriptions.get((last_space.pk, next_space.pk), None)
                    if description is None:
                        description = current_space.leave_descriptions.get(next_space.pk, None)
                    if description is None:
                        description = item.space.enter_description
                    # noinspection PyComparisonWithNone
                    if description == None:  # could be a lazy None
                        description = _('Go to %(space_title)s.') % {'space_title': item.space.title}

                    item.descriptions.append(('more_vert', description))

                last_space = current_space
                current_space = next_space

        # add description for last space
        remaining_distance = destination_distance
        for item in reversed(items):
            if item.descriptions:
                break
            if item.edge:
                remaining_distance += item.edge.distance
        if remaining_distance:
            item.descriptions.append(
                ('more_vert', _('%d m remaining to your destination.') % max(remaining_distance, 1))
            )

        items[-1].descriptions.append(('done', _('You have reached your destination.')))

        duration = round(duration)
        seconds = int(duration) % 60
        minutes = int(duration/60)
        if minutes:
            duration_str = '%d min %d s' % (minutes, seconds)
        else:
            duration_str = '%d s' % seconds

        distance = round(distance, 1)
        distance_str = '%d m' % distance
        summary = '%s (%s)' % (duration_str, distance_str)

        return OrderedDict((
            ('origin', self.origin),
            ('destination', self.destination),
            ('distance', round(distance, 2)),
            ('duration', round(duration)),
            ('distance_str', distance_str),
            ('duration_str', duration_str),
            ('summary', summary),
            ('options_summary', self.options_summary),
            ('items', items),
        ))

    @property
    def options_summary(self):
        options_summary = [
            {
                'fastest': _('fastest'),
                'shortest': _('shortest')
            }[self.options['mode']],
        ]

        restrictions_option = self.options.get('restrictions', 'normal')
        if restrictions_option == "avoid":
            options_summary.append(_('avoid restrictions'))
        elif restrictions_option == "prefer":
            options_summary.append(_('prefer restrictions'))

        waytypes_excluded = sum((name.startswith('waytype_') and value != 'allow')
                                for name, value in self.options.items())

        if waytypes_excluded:
            options_summary.append(_('avoid some path types'))
        else:
            options_summary.append(_('all path types'))

        return ', '.join(str(s) for s in options_summary)


class RouteItem:
    def __init__(self, route, node, edge, last_item):
        self.route = route
        self.node = node
        self.edge = edge
        self.last_item = last_item
        self.descriptions = []

    @cached_property
    def waytype(self):
        if self.edge and self.edge.waytype:
            return self.route.router.waytypes[self.edge.waytype]

    @cached_property
    def router_waytype(self):
        if self.edge:
            return self.route.router.waytypes[self.edge.waytype]

    @cached_property
    def space(self) -> "RouterSpace":
        return self.route.router.spaces[self.node.space]

    @cached_property
    def level(self) -> "RouterLevel":
        return self.route.router.levels[self.space.level_id]

    @cached_property
    def new_space(self):
        return not self.last_item or self.space.pk != self.last_item.space.pk

    @cached_property
    def new_level(self):
        return not self.last_item or self.level.pk != self.last_item.level.pk

    def serialize(self):  # todo: move this into schema
        result = OrderedDict((
            ('id', self.node.pk),
            ('coordinates', (self.node.x, self.node.y, self.node.altitude)),
            ('waytype', (self.route.router.waytypes[self.edge.waytype] if self.edge and self.edge.waytype else None)),
        ))
        if self.waytype:
            result['waytype'] = self.waytype

        if self.new_space:
            # todo: we should describe spaces more nicely
            result['space'] = self.space

        if self.new_level:
            # todo: we should describe levels more nicely
            result['level'] = self.level

        result['descriptions'] = [(icon, instruction) for (icon, instruction) in self.descriptions]
        return result


class NoRoute:
    distance = np.inf
