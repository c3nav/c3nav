from collections import defaultdict
from itertools import chain, product
from typing import Generator, NewType, NamedTuple

from django.db.models import Q

from c3nav.mapdata.models.locations import LocationTagRelationPathSegment, LocationTagAdjacency, LocationTagRelation, \
    CircularyHierarchyError


# …eh… this should just work without the int | ? but pycharm doesn't like it then… maybe it's pointless
type TagID = int | NewType("LocationID", int)
type AdjacencyID = int | NewType("AdjacencyID", int)
type RelationID = int | NewType("RelationID", int)
type RelationPathID = int | NewType("RelationPathID", int)

type AffectedAdjacencies = tuple[tuple[TagID, AdjacencyID], ...]
type AffectedAdjacenciesLookup = dict[TagID, AdjacencyID]


class LocationTagRelationTuple(NamedTuple):
    ancestor: TagID
    descendant: TagID


class LocationTagRelationPathSegmentTuple(NamedTuple):
    prev_path_id: RelationPathID | None
    adjacency_id: AdjacencyID
    relation_id: AdjacencyID
    num_hops: int


def unzip_paths_to_create(*data):
    if not data:
        return (), ()
    return zip(*data)


def generate_paths_to_create(
    created_relations: tuple[tuple[tuple[TagID, TagID], RelationID], ...],
    added_adjacencies: tuple[tuple[TagID, TagID, AdjacencyID], ...],
    relevant_relations: tuple[tuple[RelationID, TagID, TagID], ...],
    parent_relations: dict[TagID, dict[TagID, RelationID]],
) -> Generator[tuple[LocationTagRelationPathSegment, ...], tuple[LocationTagRelationPathSegment, ...], None]:
    relations_by_id = {relation_id: LocationTagRelationTuple(ancestor_id, descendant_id)
                       for relation_id, ancestor_id, descendant_id in relevant_relations}

    # query all the paths we need
    # even chained paths should all be contained in here, since we have all the relations that "lead to" them
    relevant_paths_by_id: dict[RelationPathID, LocationTagRelationPathSegmentTuple] = {
        path_id: LocationTagRelationPathSegmentTuple(*path)
        for path_id, *path in LocationTagRelationPathSegment.objects.filter(
            relation_id__in=relations_by_id.keys()
        ).values_list(
            "pk", "prev_path_id", "adjacency_id", "relation_id", "num_hops", named=True
        )
    }

    created_relations_lookup = dict(created_relations)
    added_adjacencies_lookup: dict[tuple[TagID, TagID], AdjacencyID] = {
        (parent_id, child_id): pk for parent_id, child_id, pk in added_adjacencies
    }

    parent_relation_ids = set(
        chain(one_parent_relations.values() for one_parent_relations in parent_relations.values())
    )

    # build path chains
    path_ids_by_relation: dict[RelationID, set[RelationPathID]] = defaultdict(set)
    next_paths_for_path_id: dict[RelationPathID | None, set[RelationPathID]] = defaultdict(set)
    for path_id, path in relevant_paths_by_id.items():
        path_ids_by_relation[path.relation_id].add(path_id)
        if path.relation_id not in parent_relation_ids:
            next_paths_for_path_id[path.prev_path_id].add(path_id)

    paths_to_create, relations = unzip_paths_to_create(*chain(
        # for each new relation that spans just one of the added adjacencies, create the singular path segment
        ((
            LocationTagRelationPathSegment(
                prev_path_id=None,
                adjacency_id=added_adjacencies_lookup[parent, child],
                relation_id=created_relations_lookup[parent, child],
                num_hops=0
            ), (parent, child)
        ) for (parent, child), adjacency in added_adjacencies_lookup.items()),

        # for each new relation that ends with one of the added adjacencies, create the new last segment(s)
        chain.from_iterable((
            ((
                # the parent relation might have several paths, we continue all of them by one
                LocationTagRelationPathSegment(
                    prev_path_id=path_id,
                    adjacency_id=orig_adjacency_id,
                    relation_id=created_relations_lookup[ancestor, child],
                    num_hops=relevant_paths_by_id[path_id].num_hops + 1
                ), (parent, child)
            ) for path_id in path_ids_by_relation[parent_relation_id])
            for (ancestor, parent, child), orig_adjacency_id, parent_relation_id in chain.from_iterable(
                # generate sequence of new relation ancestor and descendant that shoulud have been added,
                # with adjacency id and relation id if of the parent
                (
                    ((ancestor, parent, child), adjacency_id, relation_id)
                    # for every added adjacency, iterate over the parent relations
                    for ancestor, relation_id in parent_relations[parent].items()
                )
                for (parent, child), adjacency_id in added_adjacencies_lookup.items()
            )
        ))
    ))
    created_paths = yield paths_to_create

    if len(created_paths) != len(paths_to_create):
        # this shouldn't happen
        raise ValueError

    if not next_paths_for_path_id:
        # we're done, only empty left
        yield ()
        return

    # get path segments to copy that have no predecessor
    # no predecessor implies: (ancestor, descendant) of its relation are (parent, child) of its adjacency
    # this is why we can use ancestor of the paths segments relation to get the parent of its adjacency
    first_paths_by_parent: dict[TagID, list[RelationPathID]] = {}
    for path_id in next_paths_for_path_id.pop(None, ()):
        first_paths_by_parent.setdefault(
            relations_by_id[relevant_paths_by_id[path_id].relation_id].ancestor, []
        ).append(path_id)

    # copy first path segments of the child's relations and connect them to the created paths segents
    paths_to_create, path_and_ancestor = unzip_paths_to_create(*chain.from_iterable(
        # continue each path we just created with the first path segments of all child relations
        ((
            (LocationTagRelationPathSegment(
                prev_path_id=prev_created_path.pk,
                # the adjacency is identical, since we are copying this path segment
                adjacency_id=path_to_copy.adjacency_id,
                # the relation is easy to look up, cause it's unique
                relation_id=created_relations_lookup[prev_ancestor, new_descendant],
                num_hops=path_to_copy.num_hops + prev_created_path.num_hops + 1
            ), (path_to_copy_id, prev_ancestor))
            for path_to_copy_id, path_to_copy, new_descendant in (
                (path_to_copy_id, path_to_copy, relations_by_id[path_to_copy.relation_id].descendant)
                for path_to_copy_id, path_to_copy in (
                    (path_to_copy_id, relevant_paths_by_id[path_to_copy_id])
                    for path_to_copy_id in first_paths_by_parent.get(prev_descendant, ())
                )
            )
        ) for prev_created_path, (prev_ancestor, prev_descendant) in zip(created_paths, relations))
    ))

    created_paths = yield paths_to_create

    if len(created_paths) != len(paths_to_create):
        # this shouldn't happen
        raise ValueError

    while paths_to_create:
        paths_to_create, path_and_ancestor = unzip_paths_to_create(*chain.from_iterable(
            # continue each path we just created with the next path segments
            ((
                (LocationTagRelationPathSegment(
                    prev_path_id=prev_created_path.pk,
                    # the adjacency is identical, since we are copying this path segment
                    adjacency_id=path_to_copy.adjacency_id,
                    # the relation is easy to look up, cause it's unique
                    relation_id=created_relations_lookup[prev_ancestor, new_descendant],
                    num_hops=prev_created_path.num_hops + 1
                ), (path_to_copy_id, prev_ancestor))
                for path_to_copy_id, path_to_copy, new_descendant in (
                    (path_to_copy_id, path_to_copy, relations_by_id[path_to_copy.relation_id].descendant)
                    for path_to_copy_id, path_to_copy in (
                        (path_to_copy_id, relevant_paths_by_id[path_to_copy_id])
                        for path_to_copy_id in next_paths_for_path_id[prev_copied_path]
                    )
                )
            ) for prev_created_path, (prev_copied_path, prev_ancestor) in zip(created_paths, path_and_ancestor))
        ))

        created_paths = yield paths_to_create

        if len(created_paths) != len(paths_to_create):
            # this shouldn't happen
            raise ValueError


def handle_locationtag_adjacency_added(adjacencies: set[tuple[TagID, TagID]]):
    # get added adjacencies
    added_adjacencies: tuple[tuple[TagID, TagID, AdjacencyID], ...] = tuple(LocationTagAdjacency.objects.filter(  # noqa
        Q.create([Q(parent_id=parent, child_id=child) for parent, child in adjacencies], connector=Q.OR)
    ).values_list("parent_id", "child_id", "pk"))

    # generate sets of all parents and all childrens of the added adjacenties
    parents: frozenset[TagID]
    children: frozenset[TagID]
    parents, children = (frozenset(ids) for ids in zip(*adjacencies))

    # get all downwards relations to any of the parents or from any of the children
    relevant_relations: tuple[tuple[RelationID, TagID, TagID], ...] = tuple(  # noqa
        LocationTagRelation.objects.filter(
            Q(ancestor_id__in=children) | Q(descendant_id__in=parents)
        ).values_list(
            "pk", "ancestor_id", "descendant_id"
        )
    )

    # sort relations into what parents or children they end at
    parent_relations: dict[TagID, dict[TagID, RelationID]] = defaultdict(dict)
    child_relations: dict[TagID, dict[TagID, RelationID]] = defaultdict(dict)
    parent_for_child_relations: dict[RelationID, TagID] = {}
    for pk, ancestor_id, descendant_id in relevant_relations:
        if ancestor_id in children:
            child_relations[ancestor_id][descendant_id] = pk
            parent_for_child_relations[pk] = descendant_id
        elif descendant_id in parents:
            parent_relations[descendant_id][ancestor_id] = pk

        else:
            raise ValueError

    relations_to_create: frozenset[tuple[TagID, TagID]] = frozenset(chain.from_iterable((
        chain(
            product(parent_relations[parent].keys(), child_relations[child].keys()),
            product(parent_relations[parent].keys(), (child, )),
            product((parent, ), child_relations[child].keys()),
        )
        for parent, child in adjacencies
    ))) | adjacencies
    if any((ancestor == descendant) for ancestor, descendant in relations_to_create):
        raise CircularyHierarchyError("Circular relations are now allowed")

    already_existing_relations: tuple[tuple[tuple[TagID, TagID], RelationID], ...] = tuple((
        ((ancestor_id, descendant_id), pk) for ancestor_id, descendant_id, pk in LocationTagRelation.objects.filter(
            # todo: more performant with index?
            Q.create([Q(ancestor_id=ancestor, descendant_id=descendant)
                      for ancestor, descendant in relations_to_create], Q.OR)
        ).values_list("ancestor_id", "descendant_id", "pk")
    ))
    if already_existing_relations:
        relations_to_create -= frozenset(tuple(zip(*already_existing_relations))[0])
    relations_to_create: tuple[tuple[TagID, TagID], ...] = tuple(relations_to_create)

    created_relations_ids: tuple[tuple[tuple[TagID, TagID], RelationID], ...] = tuple(
        ((created_relation.ancestor_id, created_relation.descendant_id), created_relation.id)
        for created_relation in LocationTagRelation.objects.bulk_create((
            LocationTagRelation(ancestor_id=ancestor, descendant_id=descendant)
            for ancestor, descendant in relations_to_create
        ))
    )

    # check that we really got as many relations back as we put into bulk_create()
    if len(created_relations_ids) != len(relations_to_create):
        raise ValueError ("location_hierarchy_changed post_add handler bulk_insert len() mismatch")

    # create new paths
    from c3nav.mapdata.utils.relationpaths import generate_paths_to_create
    it = generate_paths_to_create(
        created_relations=already_existing_relations + created_relations_ids,
        added_adjacencies=added_adjacencies,
        relevant_relations=relevant_relations,
        parent_relations=parent_relations,
    )
    paths_to_create = next(it)
    while paths_to_create:
        created_paths = LocationTagRelationPathSegment.objects.bulk_create(paths_to_create)
        paths_to_create = it.send(tuple(created_paths))
