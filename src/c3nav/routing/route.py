# flake8: noqa
import copy
from collections import OrderedDict, deque

import numpy as np
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _


def describe_location(location, locations):
    if location.can_describe:
        final_location = locations.get(location.pk)
        if final_location is not None:
            location = final_location
    # todo: oh my god this needs to be improved
    from c3nav.routing.router import BaseRouterProxy
    if isinstance(location, BaseRouterProxy):
        location = location.src
    return location


class Route:
    def __init__(self, router, origin, destination, path_nodes, options,
                 origin_addition, destination_addition, origin_xyz, destination_xyz,
                 visible_locations):
        self.router = router
        self.origin = origin
        self.destination = destination
        self.path_nodes = path_nodes
        self.options = options
        self.origin_addition = origin_addition
        self.destination_addition = destination_addition
        self.origin_xyz = origin_xyz
        self.destination_xyz = destination_xyz
        self.visible_locations = visible_locations

    def serialize(self):  # todo: move this into schema
        nodes = [[node, None] for node in self.path_nodes]
        if self.origin_addition and any(self.origin_addition):
            nodes.insert(0, (self.origin_addition[0], None))
            nodes[1][1] = self.origin_addition[1]
        if self.destination_addition and any(self.destination_addition):
            nodes.append(self.destination_addition)

        if self.origin_xyz is not None:
            node = nodes[0][0]
            if not hasattr(node, 'xyz'):
                node = self.router.nodes[node]
            origin_distance = np.linalg.norm(node.xyz - self.origin_xyz)
        else:
            origin_distance = 0

        if self.destination_xyz is not None:
            node = nodes[-1][0]
            if not hasattr(node, 'xyz'):
                node = self.router.nodes[node]
            destination_distance = np.linalg.norm(node.xyz - self.destination_xyz)
        else:
            destination_distance = 0

        items = deque()
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
            ('origin', describe_location(self.origin, self.visible_locations)),
            ('destination', describe_location(self.destination, self.visible_locations)),
            ('distance', round(distance, 2)),
            ('duration', round(duration)),
            ('distance_str', distance_str),
            ('duration_str', duration_str),
            ('summary', summary),
            ('options_summary', self.options_summary),
            ('items', tuple(item.serialize(locations=self.visible_locations) for item in items)),
        ))

    @property
    def options_summary(self):
        options_summary = [
            {
                'fastest': _('fastest route'),
                'shortest': _('shortest route')
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
            options_summary.append(_('some path types avoided'))

        if len(options_summary) == 1:
            options_summary.append(_('default options'))

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
    def space(self):
        return self.route.router.spaces[self.node.space]

    @cached_property
    def level(self):
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
            ('waytype', (self.route.router.waytypes[self.edge.waytype].serialize(detailed=False)
                         if self.edge and self.edge.waytype else None)),
        ))
        if self.waytype:
            result['waytype'] = self.waytype.serialize(detailed=False)

        if self.new_space:
            result['space'] = describe_location(self.space, self.route.visible_locations)

        if self.new_level:
            result['level'] = describe_location(self.level, self.route.visible_locations)

        result['descriptions'] = [(icon, instruction) for (icon, instruction) in self.descriptions]
        return result


class NoRoute:
    distance = np.inf
