from collections import defaultdict
from itertools import chain, product
from typing import Generator, NewType, NamedTuple, Optional

from django.db.models import Q

from c3nav.mapdata.models.locations import LocationTagAdjacency, LocationTagRelation, CircularyHierarchyError


# …eh… this should just work without the int | ? but pycharm doesn't like it then… maybe it's pointless
type TagID = int | NewType("LocationID", int)
type AdjacencyID = int | NewType("AdjacencyID", int)
type RelationID = int | NewType("RelationID", int)

type AffectedAdjacencies = tuple[tuple[TagID, AdjacencyID], ...]
type AffectedAdjacenciesLookup = dict[TagID, AdjacencyID]


class LocationTagRelationTuple(NamedTuple):
    prev_relation_id: RelationID | None
    adjacency_id: AdjacencyID
    ancestor_id: TagID
    descendant_id: TagID
    num_hops: int


class SimpleLocationTagRelationTuple(NamedTuple):
    prev: Optional["SimpleLocationTagRelationTuple"]
    ancestor: int | None
    parent: int
    tag: int
    num_hops: int



def unzip_relations_to_create(*data):
    if not data:
        return (), ()
    return zip(*data)


def generate_relations_to_create(
    added_adjacencies: tuple[tuple[TagID, TagID, AdjacencyID], ...],
    relevant_relations: dict[RelationID, LocationTagRelationTuple],
    parent_relations: dict[TagID, dict[TagID, set[RelationID]]],
) -> Generator[tuple[LocationTagRelation, ...], tuple[LocationTagRelation, ...], None]:
    added_adjacencies_lookup: dict[tuple[TagID, TagID], AdjacencyID] = {
        (parent_id, child_id): pk for parent_id, child_id, pk in added_adjacencies
    }

    parent_relation_ids = set(
        chain(chain.from_iterable(one_parent_relations.values()) for one_parent_relations in parent_relations.values())
    )

    # build relation chains
    next_relations_for_relation_id: dict[RelationID | None, set[RelationID]] = defaultdict(set)
    for relation_id, relation in relevant_relations.items():
        if relation_id not in parent_relation_ids:
            next_relations_for_relation_id[relation.prev_relation_id].add(relation_id)

    relations_to_create, relations = unzip_relations_to_create(*chain(
        # for each new relation that spans just one of the added adjacencies, create the singular relation
        ((
            LocationTagRelation(
                prev_relation_id=None,
                adjacency_id=added_adjacencies_lookup[parent, child],
                ancestor_id=parent,
                descendant_id=child,
                num_hops=0
            ), (parent, child)
        ) for (parent, child), adjacency in added_adjacencies_lookup.items()),

        # for each new relation that ends with one of the added adjacencies, create the new last segment(s)
        chain.from_iterable((
            ((
                # there might be multiple parent relations, we continue all of them by one
                LocationTagRelation(
                    prev_relation_id=relation_id,
                    adjacency_id=orig_adjacency_id,
                    ancestor_id=ancestor,
                    descendant_id=child,
                    num_hops=relevant_relations[relation_id].num_hops + 1
                ), (parent, child)
            ) for relation_id in a_parent_relation_ids)
            for (ancestor, parent, child), orig_adjacency_id, a_parent_relation_ids in chain.from_iterable(
                # generate sequence of new relation ancestor and descendant that shoulud have been added,
                # with adjacency id and relation id if of the parent
                (
                    ((ancestor, parent, child), adjacency_id, relation_ids)
                    # for every added adjacency, iterate over the parent relations
                    for ancestor, relation_ids in parent_relations[parent].items()
                )
                for (parent, child), adjacency_id in added_adjacencies_lookup.items()
            )
        ))
    ))
    if any((ancestor == descendant) for ancestor, descendant in relations):
        raise CircularyHierarchyError("Circular relations are now allowed")
    created_relations = yield relations_to_create

    if len(created_relations) != len(relations_to_create):
        # this shouldn't happen
        raise ValueError

    if not next_relations_for_relation_id:
        # we're done, only empty left
        yield ()
        return

    # get relations to copy that have no predecessor
    # no predecessor implies: (ancestor, descendant) of its relation are (parent, child) of its adjacency
    # this is why we can use ancestor of the relations to get the parent of its adjacency
    first_relations_by_parent: dict[TagID, list[RelationID]] = {}
    for relation_id in next_relations_for_relation_id.pop(None, ()):
        first_relations_by_parent.setdefault(
            relevant_relations[relation_id].ancestor_id, []
        ).append(relation_id)

    # copy first relations of the child's relations and connect them to the created relations
    relations_to_create, relation_and_ancestor = unzip_relations_to_create(*chain.from_iterable(
        # continue each relation chain we just created with the first relation of all child relations
        ((
            (LocationTagRelation(
                prev_relation_id=prev_created_relation.pk,
                # the adjacency is identical, since we are copying this relation
                adjacency_id=relation_to_copy.adjacency_id,
                ancestor_id=prev_ancestor,
                descendant_id=new_descendant,
                num_hops=relation_to_copy.num_hops + prev_created_relation.num_hops + 1
            ), (relation_to_copy_id, prev_ancestor))
            for relation_to_copy_id, relation_to_copy, new_descendant in (
                (relation_to_copy_id, relation_to_copy, relation_to_copy.descendant_id)
                for relation_to_copy_id, relation_to_copy in (
                    (relation_to_copy_id, relevant_relations[relation_to_copy_id])
                    for relation_to_copy_id in first_relations_by_parent.get(prev_descendant, ())
                )
            )
        ) for prev_created_relation, (prev_ancestor, prev_descendant) in zip(created_relations, relations))
    ))

    created_relations = yield relations_to_create

    if len(created_relations) != len(relations_to_create):
        # this shouldn't happen
        raise ValueError

    while relations_to_create:
        relations_to_create, relation_and_ancestor = unzip_relations_to_create(*chain.from_iterable(
            # continue each relation we just created with the next relation
            ((
                (LocationTagRelation(
                    prev_relation_id=prev_created_relation.pk,
                    # the adjacency is identical, since we are copying this relation
                    adjacency_id=relation_to_copy.adjacency_id,
                    ancestor_id=prev_ancestor,
                    descendant_id=new_descendant,
                    num_hops=prev_created_relation.num_hops + 1
                ), (relation_to_copy_id, prev_ancestor))
                for relation_to_copy_id, relation_to_copy, new_descendant in (
                    (relation_to_copy_id, relation_to_copy, relation_to_copy.descendant_id)
                    for relation_to_copy_id, relation_to_copy in (
                        (relation_to_copy_id, relevant_relations[relation_to_copy_id])
                        for relation_to_copy_id in next_relations_for_relation_id[prev_copied_relation]
                    )
                )
            ) for prev_created_relation, (prev_copied_relation, prev_ancestor) in zip(created_relations, relation_and_ancestor))
        ))

        created_relations = yield relations_to_create

        if len(created_relations) != len(relations_to_create):
            # this shouldn't happen
            raise ValueError


def handle_locationtag_adjacency_added(adjacencies: set[tuple[TagID, TagID]]):
    # get added adjacencies
    added_adjacencies: tuple[tuple[TagID, TagID, AdjacencyID], ...] = tuple(LocationTagAdjacency.objects.filter(  # noqa
        Q.create([Q(parent_id=parent, child_id=child) for parent, child in adjacencies], connector=Q.OR)
    ).values_list("parent_id", "child_id", "pk"))

    if any((parent == child) for parent, child in adjacencies):
        raise CircularyHierarchyError("Circular relations are now allowed")

    # generate sets of all parents and all childrens of the added adjacenties
    parents: frozenset[TagID]
    children: frozenset[TagID]
    parents, children = (frozenset(ids) for ids in zip(*adjacencies))

    # get all downwards relations to any of the parents or from any of the children
    relevant_relations: dict[RelationID, LocationTagRelationTuple] = {  # noqa
        relation_id: LocationTagRelationTuple(*relation)
        for relation_id, *relation in LocationTagRelation.objects.filter(
            Q(ancestor_id__in=children) | Q(descendant_id__in=parents)
        ).values_list(
            "pk", "prev_relation_id", "adjacency_id", "ancestor_id", "descendant_id", "num_hops",
            named=True,
        )
    }

    # sort relations into what parents or children they end at
    parent_relations: dict[TagID, dict[TagID, set[RelationID]]] = defaultdict(lambda: defaultdict(set))
    child_relations: dict[TagID, dict[TagID, set[RelationID]]] = defaultdict(lambda: defaultdict(set))
    parent_for_child_relations: dict[RelationID, TagID] = {}
    for pk, relation in relevant_relations.items():
        if relation.ancestor_id in children:
            child_relations[relation.ancestor_id][relation.descendant_id].add(pk)
            parent_for_child_relations[pk] = relation.descendant_id
        elif relation.descendant_id in parents:
            parent_relations[relation.descendant_id][relation.ancestor_id].add(pk)
        else:
            raise ValueError


    if any((ancestor == descendant) for ancestor, descendant in chain.from_iterable((
        chain(
            product(parent_relations[parent].keys(), child_relations[child].keys()),
            product(parent_relations[parent].keys(), (child, )),
            product((parent, ), child_relations[child].keys()),
        )
        for parent, child in adjacencies
    ))):
        raise CircularyHierarchyError("Circular relations are now allowed")

    # create new relations
    it = generate_relations_to_create(
        added_adjacencies=added_adjacencies,
        relevant_relations=relevant_relations,
        parent_relations=parent_relations,
    )
    relations_to_create = next(it)
    while relations_to_create:
        created_relations = LocationTagRelation.objects.bulk_create(relations_to_create)
        relations_to_create = it.send(tuple(created_relations))
