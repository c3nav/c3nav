from typing import Callable

from django.db.models.expressions import F
from django.db.models.query_utils import Q
from django.test.testcases import TransactionTestCase

from c3nav.mapdata.models.locations import LocationTag, LocationTagRelationPathSegment, LocationTagRelation, \
    CircularyHierarchyError

type LocationHierarchyState = dict[tuple[int, int], set[tuple[int, ...]]]
type UpdateRelationFunc = Callable[[LocationTag, LocationTag], None]


class LocationHierarchyTests(TransactionTestCase):
    def assertHierarchyState(self, state: LocationHierarchyState, msg="location hierarchy doesn't match"):
        self.assertQuerySetEqual(LocationTagRelationPathSegment.objects.select_related(
            "prev_path", "adjacency", "relation"
        ).exclude(
            adjacency__child=F("relation__descendant")
        ), [], msg="Found relation path segment where adjacency child doesn't match relation descendant")

        self.assertQuerySetEqual(LocationTagRelationPathSegment.objects.select_related(
            "prev_path", "adjacency", "relation"
        ).exclude(
            Q(prev_path__isnull=True, num_hops=0) | Q(prev_path__num_hops=F("num_hops")-1)
        ), [], msg="Found relation path segment with num_hops not matching prev_path")

        self.assertQuerySetEqual(LocationTagRelationPathSegment.objects.select_related(
            "prev_path", "adjacency", "relation"
        ).exclude(
            Q(prev_path__isnull=True) | Q(relation__ancestor=F("prev_path__relation__ancestor"))
        ), [], msg="Found relation path segment with different relation ancestor than its prev_path")

        self.assertQuerySetEqual(LocationTagRelationPathSegment.objects.select_related(
            "prev_path", "adjacency", "relation"
        ).exclude(
            Q(prev_path__isnull=True) | Q(adjacency__parent=F("prev_path__adjacency__child"))
        ), [], msg="Found relation path segment where adjacency parent doesn't match prev_path's adjacency child")

        relation_lookup: dict[tuple[int, int], set[tuple[int, ...]]] = {
            relation: set() for relation in LocationTagRelation.objects.values_list("ancestor_id", "descendant_id")
        }
        path_chains: dict[int | None, tuple[int, ...]] = {None: ()}

        for path_id, prev_path_id, ancestor, descendant in LocationTagRelationPathSegment.objects.values_list(
                "pk", "prev_path_id", "relation__ancestor", "relation__descendant"
        ).order_by("num_hops"):
            path_chains[path_id] = (prev_path_chain := path_chains[prev_path_id]) + (descendant, )
            relation_lookup[(ancestor, descendant)].add(prev_path_chain)

        self.assertDictEqual(state, relation_lookup, msg)

    def _test_simple_add(self, add_parent_func: UpdateRelationFunc):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(3)])

        add_parent_func(locations[1], locations[0])
        self.assertHierarchyState({
            (locations[0].id, locations[1].id): {()},
        }, msg="0→1 hierarchy failed")

        add_parent_func(locations[2], locations[1])
        self.assertHierarchyState({
            (locations[0].id, locations[1].id): {()},
            (locations[1].id, locations[2].id): {()},
            (locations[0].id, locations[2].id): {(locations[1].id,)},
        }, msg="0→1→2 hierarchy failed")

        add_parent_func(locations[2], locations[0])
        self.assertHierarchyState({
            (locations[0].id, locations[1].id): {()},
            (locations[1].id, locations[2].id): {()},
            (locations[0].id, locations[2].id): {(), (locations[1].id,)},
        }, msg="0→1→2 + 0→2 hierarchy failed")

    def test_simple_add_parent(self):
        self._test_simple_add(lambda a, b: a.parents.add(b))

    def test_simple_add_child(self):
        self._test_simple_add(lambda a, b: b.children.add(a))

    def _test_simple_remove(self, remove_parent_func: UpdateRelationFunc):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(3)])

        locations[1].parents.add(locations[0])
        locations[2].parents.add(locations[1])
        locations[2].parents.add(locations[0])

        remove_parent_func(locations[1], locations[0])
        self.assertHierarchyState({
            (locations[1].id, locations[2].id): {()},
            (locations[0].id, locations[2].id): {()},
        }, msg="hierarchy removal failed")

        remove_parent_func(locations[2], locations[1])
        self.assertHierarchyState({
            (locations[0].id, locations[2].id): {()},
        }, msg="second hierarchy removal failed")

    def test_simple_remove_parent(self):
        self._test_simple_remove(lambda a, b: a.parents.remove(b))

    def test_simple_remove_child(self):
        self._test_simple_remove(lambda a, b: b.children.remove(a))

    def test_simple_clear_parents(self):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(3)])
        locations[1].parents.add(locations[0])
        locations[2].parents.add(locations[1])
        locations[2].parents.add(locations[0])

        locations[2].parents.clear()
        self.assertHierarchyState({
            (locations[0].id, locations[1].id): {()},
        }, msg="hierarchy clear failed")

    def test_simple_clear_children(self):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(3)])
        locations[1].parents.add(locations[0])
        locations[2].parents.add(locations[1])
        locations[2].parents.add(locations[0])

        locations[0].children.clear()
        self.assertHierarchyState({
            (locations[1].id, locations[2].id): {()},
        }, msg="hierarchy clear failed")

    def test_add_multiple_parents(self):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(4)])

        locations[2].parents.add(locations[0], locations[1])
        self.assertHierarchyState({
            (locations[0].id, locations[2].id): {()},
            (locations[1].id, locations[2].id): {()},
        }, msg="adding two parents once failed")

        locations[3].parents.add(locations[1], locations[2])
        self.assertHierarchyState({
            (locations[0].id, locations[2].id): {()},
            (locations[1].id, locations[2].id): {()},
            (locations[1].id, locations[3].id): {(), (locations[2].id, )},
            (locations[2].id, locations[3].id): {()},
            (locations[0].id, locations[3].id): {(locations[2].id, )},
        }, msg="adding two more parents failed")

    def test_add_multiple_children(self):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(4)])

        locations[0].children.add(locations[1], locations[2])
        self.assertHierarchyState({
            (locations[0].id, locations[1].id): {()},
            (locations[0].id, locations[2].id): {()},
        }, msg="adding two children once failed")

        locations[1].children.add(locations[2], locations[3])
        self.assertHierarchyState({
            (locations[0].id, locations[1].id): {()},
            (locations[0].id, locations[2].id): {(), (locations[1].id, )},
            (locations[1].id, locations[2].id): {()},
            (locations[1].id, locations[3].id): {()},
            (locations[0].id, locations[3].id): {(locations[1].id, )},
        }, msg="adding two more children failed")

    def _test_add_downwards_tree(self, add_parent_func: UpdateRelationFunc):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(4)])

        add_parent_func(locations[1], locations[0])
        add_parent_func(locations[2], locations[1])
        add_parent_func(locations[2], locations[0])
        add_parent_func(locations[0], locations[3])

        self.assertHierarchyState({
            (locations[0].id, locations[1].id): {()},
            (locations[1].id, locations[2].id): {()},
            (locations[0].id, locations[2].id): {(), (locations[1].id,)},
            (locations[3].id, locations[0].id): {()},
            (locations[3].id, locations[1].id): {(locations[0].id,)},
            (locations[3].id, locations[2].id): {(locations[0].id,), (locations[0].id, locations[1].id,)},
        }, msg="3→0→1→2 + 0→2 hierarchy failed")

    def test_add_downwards_tree_by_parent(self):
        self._test_add_downwards_tree(lambda a, b: a.parents.add(b))

    def test_add_downwards_tree_by_child(self):
        self._test_add_downwards_tree(lambda a, b: b.children.add(a))

    def _test_add_upwards_tree(self, add_parent_func: UpdateRelationFunc):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(4)])

        add_parent_func(locations[1], locations[0])
        add_parent_func(locations[2], locations[1])
        add_parent_func(locations[2], locations[0])
        add_parent_func(locations[3], locations[2])

        self.assertHierarchyState({
            (locations[0].id, locations[1].id): {()},
            (locations[1].id, locations[2].id): {()},
            (locations[0].id, locations[2].id): {(), (locations[1].id,)},
            (locations[2].id, locations[3].id): {()},
            (locations[1].id, locations[3].id): {(locations[2].id,)},
            (locations[0].id, locations[3].id): {(locations[2].id,), (locations[1].id, locations[2].id,)},
        }, msg="0→1→2→3 + 0→2 hierarchy failed")

    def test_add_upwards_tree_by_parent(self):
        self._test_add_upwards_tree(lambda a, b: a.parents.add(b))

    def test_add_upwards_tree_by_child(self):
        self._test_add_upwards_tree(lambda a, b: b.children.add(a))

    def test_circular_fails(self):
        locations = LocationTag.objects.bulk_create([LocationTag() for i in range(3)])
        locations[0].children.add(locations[1])
        locations[1].children.add(locations[2])
        with self.assertRaises(CircularyHierarchyError):
            locations[2].children.add(locations[0])