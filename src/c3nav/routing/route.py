# flake8: noqa
import copy
from collections import OrderedDict, deque

import numpy as np
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _


def describe_location(location, locations):
    if location.can_describe:
        final_location = locations.get(location.pk)
        if final_location is not None:
            location = final_location
        else:
            location.can_describe = False
    return location.serialize(detailed=False, describe_only=True, simple_geometry=True)


class Route:
    def __init__(self, router, origin, destination, distance, path_nodes, origin_addition, destination_addition):
        self.router = router
        self.origin = origin
        self.destination = destination
        self.distance = distance
        self.path_nodes = path_nodes
        self.origin_addition = origin_addition
        self.destination_addition = destination_addition

    def serialize(self, locations):
        nodes = [[node, None] for node in self.path_nodes]
        if self.origin_addition and any(self.origin_addition):
            nodes.insert(0, (self.origin_addition[0], None))
            nodes[1][1] = self.origin_addition[1]
        if self.destination_addition and any(self.origin_addition):
            nodes.append(self.destination_addition)

        items = deque()
        last_node = None
        last_item = None
        distance = 0
        for i, (node, edge) in enumerate(nodes):
            if edge is None:
                edge = self.router.edges[last_node, node] if last_node else None
            node_obj = self.router.nodes[node] if isinstance(node, (int, np.int32, np.int64)) else node
            item = RouteItem(self, node_obj, edge, last_item)
            if edge:
                distance += edge.distance
            items.append(item)
            last_item = item
            last_node = node
        return OrderedDict((
            ('origin', describe_location(self.origin, locations)),
            ('destination', describe_location(self.destination, locations)),
            ('distance', round(distance, 2)),
            ('items', tuple(item.serialize(locations=locations) for item in items)),
        ))


class RouteItem:
    def __init__(self, route, node, edge, last_item):
        self.route = route
        self.node = node
        self.edge = edge
        self.last_item = last_item

    @cached_property
    def waytype(self):
        if self.edge and self.edge.waytype:
            return self.route.router.waytypes[self.edge.waytype]

    @cached_property
    def space(self):
        return self.route.router.spaces[self.node.space]

    @cached_property
    def level(self):
        return self.route.router.levels[self.space.level_id]

    def serialize(self, locations):
        result = OrderedDict((
            ('id', self.node.pk),
            ('coordinates', (self.node.x, self.node.y, self.node.altitude)),
            ('waytype', (self.route.router.waytypes[self.edge.waytype].serialize(detailed=False)
                         if self.edge and self.edge.waytype else None)),
        ))
        if self.waytype:
            result['waytype'] = self.waytype.serialize(detailed=False)

        if not self.last_item or self.space.pk != self.last_item.space.pk:
            result['space'] = describe_location(self.space, locations)

        if not self.last_item or self.level.pk != self.last_item.level.pk:
            result['level'] = describe_location(self.level, locations)
        return result



class NoRoute:
    distance = np.inf
