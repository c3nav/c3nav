# flake8: noqa
import copy
from collections import OrderedDict, deque

import numpy as np
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _


class Route:
    def __init__(self, router, origin, destination, distance, path_nodes):
        self.router = router
        self.origin = origin
        self.destination = destination
        self.distance = distance
        self.path_nodes = path_nodes

    def serialize(self):
        items = deque()
        last_node = None
        last_item = None
        for i, node in enumerate(self.path_nodes):
            item = RouteItem(self, self.router.nodes[node],
                             self.router.edges[last_node, node] if last_node else None,
                             last_item)
            items.append(item)
            last_item = item
            last_node = node
        return OrderedDict((
            ('items', tuple(item.serialize() for item in items)),
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

    def serialize(self):
        result = OrderedDict((
            ('id', self.node.pk),
            ('coords', (self.node.x, self.node.y, self.node.altitude)),
            ('waytype', (self.route.router.waytypes[self.edge.waytype].serialize(detailed=False)
                         if self.edge and self.edge.waytype else None)),
        ))
        if self.waytype:
            result['waytype'] = self.waytype.serialize(detailed=False)

        if not self.last_item or self.space.pk != self.last_item.space.pk:
            result['space'] = self.space.serialize(detailed=False)

        if not self.last_item or self.level.pk != self.last_item.level.pk:
            result['level'] = self.level.serialize(detailed=False)
        return result



class NoRoute:
    distance = np.inf
