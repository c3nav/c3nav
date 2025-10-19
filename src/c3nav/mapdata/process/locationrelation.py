from collections import deque, defaultdict
from itertools import chain
from operator import itemgetter
from typing import NamedTuple, Self

from django.db import models
from django.db.models import Q
from django.db.models.aggregates import Count
from django.db.models.expressions import F, When, Case, Value

from c3nav.mapdata.models.locations import LocationTagAdjacency, LocationTagRelation, LocationTag
from c3nav.mapdata.utils.relationpaths import SimpleLocationTagRelationTuple

type AbsoluteAncestorTuple = tuple[None, int, ...] | tuple[None, ]
type RelativeAncestorTuple = tuple[int, ...]
type AncestorTuple = AbsoluteAncestorTuple | RelativeAncestorTuple
type TagOrderResult = dict[None | int, dict[AncestorTuple, int]]


class EffectiveLocationTagOrders(NamedTuple):
    depth_first_pre_order: TagOrderResult
    depth_first_post_order: TagOrderResult
    breadth_first_order: TagOrderResult

    @staticmethod
    def calc_breadth_first_order(root_tag_ids: list[int],
                                 children_for_parent: dict[int, list[int]]) -> TagOrderResult:
        result: TagOrderResult = defaultdict(dict)
        next_tags: deque[tuple[AbsoluteAncestorTuple, list[int]]] = deque([((None, ), root_tag_ids)])

        while next_tags:
            ancestors, children = next_tags.popleft()
            for tag_id in children:
                for i, ancestor in enumerate(ancestors):
                    result[ancestor].setdefault(ancestors[i:] + (tag_id, ), len(result[ancestor]))
                # noinspection PyTypeChecker
                next_tags.append((ancestors + (tag_id, ), children_for_parent[tag_id]))

        return result

    @staticmethod
    def calc_depth_first_post_order(root_tag_ids: list[int],
                                    children_for_parent: dict[int, list[int]]) -> TagOrderResult:
        result: TagOrderResult = defaultdict(dict)

        def add(ancestors: AbsoluteAncestorTuple, descendant_id: int):
            new_ancestors = ancestors + (descendant_id, )
            for child_id in children_for_parent[descendant_id]:
                # noinspection PyTypeChecker
                add(new_ancestors, child_id)
            for i, ancestor in enumerate(ancestors):
                result[ancestor].setdefault(ancestors[i:] + (descendant_id, ), len(result[ancestor]))

        start_ancestors = (None, )
        for root_id in root_tag_ids:
            add(start_ancestors, root_id)

        return result

    @staticmethod
    def calc_depth_first_pre_order(root_tag_ids: list[int],
                                   children_for_parent: dict[int, list[int]]) -> TagOrderResult:
        result: TagOrderResult = defaultdict(dict)

        def add(ancestors: AbsoluteAncestorTuple, descendant_id: int):
            new_ancestors = ancestors + (descendant_id,)
            for i, ancestor in enumerate(ancestors):
                result[ancestor].setdefault(ancestors[i:] + (descendant_id,), len(result[ancestor]))
            for child_id in children_for_parent[descendant_id]:
                # noinspection PyTypeChecker
                add(new_ancestors, child_id)

        start_ancestors = (None, )
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
    expected_relations: dict[int, tuple[SimpleLocationTagRelationTuple, ...]] = {}
    num_hops = 0
    last_relations: tuple[SimpleLocationTagRelationTuple, ...] = tuple(chain(
        chain.from_iterable(
            (
                SimpleLocationTagRelationTuple(ancestor=parent_id, parent=parent_id, tag=child_id,
                                               prev=None, num_hops=0)
                for child_id in child_ids
            ) for parent_id, child_ids in children_by_parent.items()
        ),
        (
            SimpleLocationTagRelationTuple(ancestor=None, parent=None, tag=pk, prev=None, num_hops=0)
            for pk in LocationTag.objects.values_list("pk", flat=True)
        )
    ))
    while last_relations:
        cyclic_relations = tuple(p for p in last_relations if p.ancestor == p.tag)
        last_relations = tuple(p for p in last_relations if p.ancestor != p.tag)
        for relation in cyclic_relations:
            print(f"INCONSISTENCY! Circular hierarchy! Breaking parent→child {relation.parent}→{relation.tag}")
            fail = True
        expected_relations[num_hops] = last_relations

        num_hops += 1
        last_relations = tuple(chain.from_iterable(
            (
                SimpleLocationTagRelationTuple(ancestor=prev.ancestor, parent=prev.tag, tag=child_id,
                                               prev=prev, num_hops=num_hops)
                for child_id in child_ids
            ) for prev, child_ids in zip(last_relations, (children_by_parent.get(relation.tag, frozenset())
                                                          for relation in last_relations))
        ))

    num_deleted, num_deleted_per_model = LocationTagRelation.objects.exclude(
        # exclude things where things make sense
        Q(adjacency__child=F("descendant")) & (
            (Q(prev_relation__isnull=True) | (Q(adjacency__parent=F("prev_relation__adjacency__child"))
                                             & Q(ancestor=F("prev_relation__ancestor"))
                                             & Q(num_hops=F("prev_relation__num_hops")+1)))
            | (Q(prev_relation__isnull=False) | Q(adjacency__parent=F("ancestor")))
        )
    ).delete()
    if num_deleted:
        print("INCONSISTENCY: Invalid relations that don't fit modeling constraints, deleting", num_deleted, "of them")
        fail = True

    existing_relations_by_id = {
        pk: fields for pk, *fields in LocationTagRelation.objects.values_list(
            "pk", "prev_relation_id", "ancestor_id", "adjacency__parent_id", "adjacency__child_id", "num_hops",
        )
    }
    existing_relations_by_num_hops_and_id: dict[int, dict[int, SimpleLocationTagRelationTuple]] = {}
    existing_relation_id_by_tuple: dict[SimpleLocationTagRelationTuple | None, int | None] = {None: None}

    relations_by_num_hops: dict[int, list[tuple]] = {}
    for id, relation in existing_relations_by_id.items():
        relations_by_num_hops.setdefault(relation[4], []).append((id, relation))

    for num_hops, relations in sorted(relations_by_num_hops.items(), key=itemgetter(0)):
        num_hops_relations = {}
        existing_relations_by_num_hops_and_id[num_hops] = num_hops_relations

        last_num_hops_relations = {} if num_hops == 0 else existing_relations_by_num_hops_and_id.get(num_hops - 1, {})

        for pk, (prev_relation_id, ancestor_id, parent_id, child_id, n) in relations:
            t = SimpleLocationTagRelationTuple(
                prev=None if prev_relation_id is None else last_num_hops_relations[prev_relation_id],
                ancestor=ancestor_id,
                parent=parent_id,
                tag=child_id,
                num_hops=num_hops,
            )
            num_hops_relations[pk] = t
            existing_relation_id_by_tuple[t] = pk

    delete_ids: deque[int] = deque()

    # todo: check that prev path id is always correct

    max_num_hops = max(chain(existing_relations_by_num_hops_and_id.keys(), expected_relations.keys()), default=0)
    for num_hops in range(max_num_hops+1):
        existing_relations_for_hops = frozenset(existing_relations_by_num_hops_and_id.get(num_hops, {}).values())
        expected_relations_for_hops = frozenset(expected_relations.get(num_hops, ()))

        missing_relations = tuple(expected_relations_for_hops - existing_relations_for_hops)
        if missing_relations:
            print("INCONSISTENCY: Missing relations, creating:", missing_relations)
            fail = True
            existing_relation_id_by_tuple.update(
                dict(zip(missing_relations, (created_relation.pk for created_relation in LocationTagRelation.objects.bulk_create((
                    LocationTagRelation(
                        prev_relation_id=existing_relation_id_by_tuple[missing_relation.prev],
                        adjacency=adjacency_ids[(missing_relation.parent, missing_relation.tag)],
                        ancestor_id=missing_relation.ancestor,
                        descendant_id=missing_relation.tag,
                        num_hops=num_hops,
                    ) for missing_relation in missing_relations
                )))))
            )

        extra_relations = existing_relations_for_hops - expected_relations_for_hops
        if extra_relations:
            print("INCONSISTENCY: Extra relations, deleting:", extra_relations)
            delete_ids.extend(existing_relation_id_by_tuple[extra_relation] for extra_relation in extra_relations)
            fail = True

    if delete_ids:
        LocationTagRelation.objects.filter(pk__in=delete_ids).delete()

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
    # todo: look, location order isn't correct now that we have locations more than once etc
    pks, priorities, num_parents, num_children = zip(
        *LocationTag.objects.annotate(
            Count("parents"),
            Count("children"),
        ).select_for_update().values_list("pk", "priority", "parents__count", "children__count").order_by("-priority")
    )
    root_tag_ids = [pk for pk, parents in zip(pks, num_parents) if parents == 0]
    leaf_tag_ids = [pk for pk, children in zip(pks, num_children) if children == 0]

    children_for_parent: dict[int, list[int]] = defaultdict(list)
    for parent_id, child_id in LocationTagAdjacency.objects.order_by(
        "-child__priority", "child_id"
    ).values_list(
        "parent_id", "child_id"
    ).select_for_update():
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

    order_directions = ("downwards", downwards_orders), ("upwards", upwards_orders)
    local_orders_by_name: dict[str, dict[int, set[AncestorTuple]]] = dict(chain.from_iterable((
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
            ("breadth_first_order", *(d.breadth_first_order for dir_name, d in order_directions)),
            ("depth_first_pre_order", *(d.depth_first_pre_order for dir_name, d in order_directions)),
            ("depth_first_post_order", *(d.depth_first_post_order for dir_name, d in order_directions)),
        )
    )))

    relation_by_id: dict[int, AncestorTuple] = {}
    relation_by_path: dict[AncestorTuple, int] = {}
    for pk, prev_id, ancestor_id, descendant_id in LocationTagRelation.objects.order_by("num_hops").values_list(
            "pk", "prev_relation_id", "ancestor_id", "descendant_id", flat=True,
    ):
        path: AncestorTuple = relation_by_id.get(prev_id, (ancestor_id, )) + (descendant_id, )  # noqa
        relation_by_id[pk] = path
        relation_by_path[path] = pk

    field = models.PositiveIntegerField()
    LocationTagRelation.objects.update(**{
        f"effective_{order_name}": Case(
            *(
                When(pk__in={relation_by_path[path] for path in path}, then=Value(i, output_field=field))
                for i, path in order.items()
            ),
            default=Value(2 ** 31 - 1, output_field=field),
        )
        for order_name, order in local_orders_by_name.items()
    })

