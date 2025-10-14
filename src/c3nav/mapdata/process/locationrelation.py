import operator
from collections import deque, defaultdict
from functools import reduce
from itertools import chain
from operator import itemgetter
from typing import NamedTuple, Self

from django.db import models
from django.db.models import Q
from django.db.models.aggregates import Count
from django.db.models.expressions import F, When, Case, Value

from c3nav.mapdata.models.locations import LocationTagAdjacency, SimpleLocationTagRelationPathSegmentTuple, \
    LocationTagRelation, LocationTagRelationPathSegment, LocationTag


class EffectiveLocationTagOrders(NamedTuple):
    depth_first_pre_order: dict[int | None, dict[int, int]]
    depth_first_post_order: dict[int | None, dict[int, int]]
    breadth_first_order: dict[int | None, dict[int, int]]

    depth_first_pre_order: dict[int | None, dict[int, int]]
    depth_first_post_order: dict[int | None, dict[int, int]]
    breadth_first_order: dict[int | None, dict[int, int]]

    @staticmethod
    def calc_breadth_first_order(root_tag_ids: list[int],
                                 children_for_parent: dict[int, list[int]]) -> dict[int | None, dict[int, int]]:
        result: dict[int | None, dict[int, int]] = defaultdict(dict)  # dict to maintain insertion order
        next_tags: deque[tuple[set[int], list[int]]] = deque([(set(), root_tag_ids)])
        #print("breadth first")
        while next_tags:
            #print(next_tags, children_for_parent, result)
            ancestor_ids, tag_ids = next_tags.popleft()
            for tag_id in tag_ids:
                result[None].setdefault(tag_id, len(result[None]))
                for ancestor_id in ancestor_ids:
                    result[ancestor_id].setdefault(tag_id, len(result[ancestor_id]))
                next_tags.append((ancestor_ids | {tag_id}, children_for_parent[tag_id]))

        return result

    @staticmethod
    def calc_depth_first_post_order(root_tag_ids: list[int],
                                    children_for_parent: dict[int, list[int]]) -> dict[int | None, dict[int, int]]:
        result: dict[int | None, dict[int, int]] = defaultdict(dict)  # dict to maintain insertion order
        next_tags: deque[tuple[tuple[int, ...], int, list[int]]] = deque([((None, ), None, root_tag_ids)])
        # print("root_tag_ids=", root_tag_ids, "children_for_parent=", children_for_parent)
        # print("depth first")

        def add(ancestors: set, descendant_id: int):
            new_ancestors = ancestors | {descendant_id}
            for child_id in children_for_parent[descendant_id]:
                add(new_ancestors, child_id)
            for ancestor_id in ancestors:
                result[ancestor_id].setdefault(descendant_id, len(result[ancestor_id]))

        start_ancestors = {None}
        for root_id in root_tag_ids:
            add(start_ancestors, root_id)

        return result

    @staticmethod
    def calc_depth_first_pre_order(root_tag_ids: list[int],
                                   children_for_parent: dict[int, list[int]]) -> dict[int | None, dict[int, int]]:
        result: dict[int | None, dict[int, int]] = defaultdict(dict)  # dict to maintain insertion order

        def add(ancestors: set, descendant_id: int):
            new_ancestors = ancestors | {descendant_id}
            for ancestor_id in ancestors:
                result[ancestor_id].setdefault(descendant_id, len(result[ancestor_id]))
            for child_id in children_for_parent[descendant_id]:
                add(new_ancestors, child_id)

        start_ancestors = {None}
        for root_id in root_tag_ids:
            add(start_ancestors, root_id)

        return result

    @classmethod
    def calculate(cls, root_tag_ids: list[int], children_for_parent: dict[int, list[int]]) -> Self:
        return cls(
            breadth_first_order=cls.calc_breadth_first_order(root_tag_ids, children_for_parent),
            depth_first_pre_order=cls.calc_depth_first_pre_order(root_tag_ids, children_for_parent),
            depth_first_post_order=cls.calc_depth_first_post_order(root_tag_ids, children_for_parent),
        )


def process_location_tag_relations():
    build_children_by_parent: dict[int | None, deque[int]] = defaultdict(deque)
    adjacency_ids: dict[tuple[int, int], int] = {}
    for pk, parent_id, child_id in LocationTagAdjacency.objects.values_list("pk", "parent_id", "child_id"):
        adjacency_ids[(parent_id, child_id)] = pk
        build_children_by_parent[parent_id].append(child_id)
    children_by_parent: dict[int | None, frozenset[int]] = {
        parent_id: frozenset(children_ids) for parent_id, children_ids in build_children_by_parent.items()
    }

    fail = False

    # create ancestors
    expected_paths: dict[int, tuple[SimpleLocationTagRelationPathSegmentTuple, ...]] = {}
    num_hops = 0
    last_paths: tuple[SimpleLocationTagRelationPathSegmentTuple, ...] = tuple(chain.from_iterable(
        (
            SimpleLocationTagRelationPathSegmentTuple(ancestor=parent_id, parent=parent_id, tag=child_id,
                                                      prev=None, num_hops=0)
            for child_id in child_ids
        ) for parent_id, child_ids in children_by_parent.items()
    ))
    while last_paths:
        cyclic_paths = tuple(p for p in last_paths if p.ancestor == p.tag)
        last_paths = tuple(p for p in last_paths if p.ancestor != p.tag)
        for path in cyclic_paths:
            print(f"INCONSISTENCY! Circular hierarchy! Breaking parent→child {path.parent}→{path.tag}")
            fail = True
        expected_paths[num_hops] = last_paths

        num_hops += 1
        last_paths = tuple(chain.from_iterable(
            (
                SimpleLocationTagRelationPathSegmentTuple(ancestor=prev.ancestor, parent=prev.tag, tag=child_id,
                                                          prev=prev, num_hops=num_hops)
                for child_id in child_ids
            ) for prev, child_ids in zip(last_paths, (children_by_parent.get(path.tag, frozenset()) for path in last_paths))
        ))

    expected_relations = {(path.ancestor, path.tag) for path in chain.from_iterable(expected_paths.values())}
    relation_ids = {
        (ancestor_id, descendant_id): pk
        for pk, ancestor_id, descendant_id in LocationTagRelation.objects.values_list("pk", "ancestor_id", "descendant_id")
    }
    existing_relations = set(relation_ids.keys())

    missing_relations = expected_relations - existing_relations
    if missing_relations:
        print("INCONSISTENCY: Missing relations, creating:", missing_relations)
        fail = True
        relation_ids.update({
            relation.pk: (relation.ancestor_id, relation.descendant_id)
            for relation in LocationTagRelation.objects.bulk_create((
                LocationTagRelation(
                    ancestor_id=ancestor_id,
                    descendant_id=descendant_id,
                ) for ancestor_id, descendant_id in missing_relations
            ))
        })

    extra_relations = existing_relations - expected_relations
    if extra_relations:
        print("INCONSISTENCY: Extra relations, deleting:", missing_relations)
        fail = True
        LocationTagRelation.objects.filter(
            pk__in=(relation_ids[extra_relation] for extra_relation in extra_relations)
        ).delete()
        for extra_relation in missing_relations:
            del relation_ids[extra_relation]

    num_deleted, num_deleted_per_model = LocationTagRelationPathSegment.objects.exclude(
        # exclude things where things make sense
        Q(adjacency__child=F("relation__descendant")) & (
            (Q(prev_path__isnull=True) | (Q(adjacency__parent=F("prev_path__adjacency__child"))
                                          & Q(relation__ancestor=F("prev_path__relation__ancestor"))
                                          & Q(num_hops=F("prev_path__num_hops")+1)))
            | (Q(prev_path__isnull=False) | Q(adjacency__parent=F("relation__ancestor")))
        )
    ).delete()
    if num_deleted:
        print("INCONSISTENCY: Invalid paths that don't fit modeling constraints, deleting", num_deleted, "of them")
        fail = True

    existing_paths_by_id = {
        pk: fields for pk, *fields in LocationTagRelationPathSegment.objects.values_list(
            "pk", "prev_path_id", "relation__ancestor_id",
            "adjacency__parent_id", "adjacency__child_id", "num_hops",
        )
    }
    existing_paths_by_num_hops_and_id: dict[int, dict[int, SimpleLocationTagRelationPathSegmentTuple]] = {}
    existing_path_id_by_tuple: dict[SimpleLocationTagRelationPathSegmentTuple | None, int | None] = {None: None}

    paths_by_num_hops: dict[int, list[tuple]] = {}
    for id, path in existing_paths_by_id.items():
        paths_by_num_hops.setdefault(path[4], []).append((id, path))

    for num_hops, paths in sorted(paths_by_num_hops.items(), key=itemgetter(0)):
        num_hops_paths = {}
        existing_paths_by_num_hops_and_id[num_hops] = num_hops_paths

        last_num_hops_paths = {} if num_hops == 0 else existing_paths_by_num_hops_and_id.get(num_hops - 1, {})

        for pk, (prev_path_id, ancestor_id, parent_id, child_id, n) in paths:
            t = SimpleLocationTagRelationPathSegmentTuple(
                prev=None if prev_path_id is None else last_num_hops_paths[prev_path_id],
                ancestor=ancestor_id,
                parent=parent_id,
                tag=child_id,
                num_hops=num_hops,
            )
            num_hops_paths[pk] = t
            existing_path_id_by_tuple[t] = pk

    delete_ids: deque[int] = deque()

    max_num_hops = max(chain(existing_paths_by_num_hops_and_id.keys(), expected_paths.keys()), default=0)
    for num_hops in range(max_num_hops+1):
        existing_paths_for_hops = frozenset(existing_paths_by_num_hops_and_id.get(num_hops, {}).values())
        expected_paths_for_hops = frozenset(expected_paths.get(num_hops, ()))

        missing_paths = tuple(expected_paths_for_hops - existing_paths_for_hops)
        if missing_relations:
            print("INCONSISTENCY: Missing paths, creating:", missing_paths)
            fail = True
            existing_path_id_by_tuple.update(
                dict(zip(missing_paths, (created_path.pk for created_path in LocationTagRelationPathSegment.objects.bulk_create((
                    LocationTagRelationPathSegment(
                        prev_path=existing_path_id_by_tuple[missing_path.prev],
                        adjacency=adjacency_ids[(missing_path.parent, missing_path.tag)],
                        relation=relation_ids[(missing_path.ancestor, missing_path.tag)],
                        num_hops=num_hops,
                    ) for missing_path in missing_paths
                )))))
            )

        extra_paths = existing_paths_for_hops - expected_paths_for_hops
        if extra_relations:
            print("INCONSISTENCY: Extra paths, deleting:", extra_paths)
            delete_ids.extend(existing_path_id_by_tuple[extra_path] for extra_path in extra_paths)
            fail = True

    if delete_ids:
        LocationTagRelationPathSegment.objects.filter(pk__in=delete_ids).delete()

    if fail:
        raise ValueError("verify_location_relation failed")

    recalculate_locationtag_effective_order()


def _tuples_by_value(tuples: dict[tuple[int, int], int]) -> dict[int, set[tuple[int, int]]]:
    #print("tuples_by_value", tuples)
    result: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for t, val in tuples.items():
        result[val].add(t)
    return result


def recalculate_locationtag_effective_order():
    pks, priorities, num_parents, num_children = zip(
        *LocationTag.objects.annotate(
            Count("parents"),
            Count("children"),
        ).values_list("pk", "priority", "parents__count", "children__count").order_by("-priority")
    )
    root_tag_ids = [pk for pk, parents in zip(pks, num_parents) if parents == 0]
    leaf_tag_ids = [pk for pk, children in zip(pks, num_children) if children == 0]

    children_for_parent: dict[int, list[int]] = defaultdict(list)
    for parent_id, child_id in LocationTagAdjacency.objects.order_by(
        "-child__priority", "child_id"
    ).values_list(
        "parent_id", "child_id"
    ):
        children_for_parent[parent_id].append(child_id)

    parents_for_child: dict[int, list[int]] = defaultdict(list)
    for parent_id, child_id in LocationTagAdjacency.objects.order_by(
        "-parent__priority", "parent_id"
    ).values_list(
        "parent_id", "child_id"
    ):
        parents_for_child[child_id].append(parent_id)

    downwards_orders = EffectiveLocationTagOrders.calculate(root_tag_ids, children_for_parent)
    upwards_orders =  EffectiveLocationTagOrders.calculate(leaf_tag_ids, parents_for_child)

    orders_by_name = ("downwards", downwards_orders), ("upwards", upwards_orders)
    #print(orders_by_name)
    global_orders_by_name: dict[str, dict[int, int]] = dict(chain.from_iterable((
        (
            (f"{dir_name}_{order_name}", order)
            for order_name, order in (
                ("breadth_first_order", orders.breadth_first_order.pop(None)),
                ("depth_first_pre_order", orders.depth_first_pre_order.pop(None)),
                ("depth_first_post_order", orders.depth_first_post_order.pop(None)),
            )
        ) for dir_name, orders in orders_by_name)
    ))
    #from pprint import pprint
    #pprint(global_orders_by_name)

    local_orders_by_name: dict[str, dict[int, set[tuple[int, int]]]] = dict(chain.from_iterable((
        (
            (f"downwards_{order_name}", _tuples_by_value(dict(chain.from_iterable(
                (((ancestor, descendant), i) for descendant, i in descendants.items())
                for ancestor, descendants in downwards.items()
            )))),
            (f"upwards_{order_name}", _tuples_by_value(dict(chain.from_iterable(
                 (((descendant, ancestor), i) for descendant, i in descendants.items())
                 for ancestor, descendants in upwards.items()
            )))),
        ) for order_name, downwards, upwards in (
            ("breadth_first_order", *(d.breadth_first_order for dir_name, d in orders_by_name)),
            ("depth_first_pre_order", *(d.depth_first_pre_order for dir_name, d in orders_by_name)),
            ("depth_first_post_order", *(d.depth_first_post_order for dir_name, d in orders_by_name)),
        )
    )))

    field = models.PositiveIntegerField()
    LocationTag.objects.update(**{
        f"effective_{order_name}": Case(
            *(
                When(pk=tag_id, then=Value(i, output_field=field))
                for tag_id, i in order.items()
            ),
            default=Value(2 ** 31 - 1, output_field=field),
        )
        for order_name, order in global_orders_by_name.items()
    })
    print("local_orders_by_name", local_orders_by_name)
    LocationTagRelation.objects.update(**{
        f"effective_{order_name}": Case(
            *(
                When(condition=reduce(operator.or_, (Q(ancestor_id=ancestor_id, descendant_id=descendant_id)
                                                     for ancestor_id, descendant_id in tuples)),
                     then=Value(i, output_field=field))
                for i, tuples in order.items()
            ),
            default=Value(2 ** 31 - 1, output_field=field),
        )
        for order_name, order in local_orders_by_name.items()
    })

