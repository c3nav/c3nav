from typing import Callable, NamedTuple

from django.db.models.expressions import F
from django.db.models.query_utils import Q
from django.test.testcases import TransactionTestCase

from c3nav.mapdata.models.locations import LocationTag, LocationTagRelationPathSegment, LocationTagRelation, \
    CircularyHierarchyError

class AncestorDescendantTuple(NamedTuple):
    ancestor: int
    descendant: int

type HierarchyPath = tuple[int, ...]
type HierarchyPathSet = set[HierarchyPath]

type LocationHierarchyState = dict[AncestorDescendantTuple, HierarchyPathSet]
type UpdateRelationFunc = Callable[[LocationTag, LocationTag], None]


class LocationHierarchyTests(TransactionTestCase):
    def _create_tags(self, num: int):
        return LocationTag.objects.bulk_create([LocationTag() for i in range(num)])  # pragma: no branch

    def assertHierarchyState(self, state: LocationHierarchyState, msg="location hierarchy doesn't match"):
        """
        :param state: a set of ancestry paths for every AncestorDescendantTuple
        :param msg: message to fail with if the hierarchy state doesn't match
        """
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

        relation_lookup: dict[tuple[int, int], set[tuple[int, ...]]] = {    # pragma: no branch
            rel: set() for rel in LocationTagRelation.objects.values_list("ancestor_id", "descendant_id")
        }
        path_chains: dict[int | None, tuple[int, ...]] = {None: ()}

        for path_id, prev_path_id, ancestor, descendant in LocationTagRelationPathSegment.objects.values_list(
                "pk", "prev_path_id", "relation__ancestor", "relation__descendant"
        ).order_by("num_hops"):
            path_chains[path_id] = (prev_path_chain := path_chains[prev_path_id]) + (descendant, )
            relation_lookup[AncestorDescendantTuple(ancestor, descendant)].add(prev_path_chain)

        self.assertDictEqual(state, relation_lookup, msg)

    def _test_simple_add(self, add_parent_func: UpdateRelationFunc):
        """
        Create three location tags, turn them into a chain step by step, then add a shortcut from the start to the end
        verify the hierarchy state after each step

        :param add_parent_func: function that takes two location tags a and b, and adds a as a child to b
        """
        locations = self._create_tags(3)

        add_parent_func(locations[1], locations[0])
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[1].id): {()},
        }, msg="0→1 hierarchy failed")

        add_parent_func(locations[2], locations[1])
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[1].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[2].id): {(locations[1].id,)},
        }, msg="0→1→2 hierarchy failed")

        add_parent_func(locations[2], locations[0])
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[1].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[2].id): {(), (locations[1].id,)},
        }, msg="0→1→2 + 0→2 hierarchy failed")

    def test_simple_add_parent(self):
        """
        Run test simple add, create the parent child relationships by adding a parent to the child
        """
        self._test_simple_add(lambda a, b: a.parents.add(b))

    def test_simple_add_child(self):
        """
        Run test simple add, create the parent child relationships by adding a child to the parent
        """
        self._test_simple_add(lambda a, b: b.children.add(a))

    def _test_simple_remove(self, remove_parent_func: UpdateRelationFunc):
        """
        Create three location tags and turn them into a hierarchy chain with a shortcut from the top to bottom.
        Remove parent relations between the first links and the second link step by step.
        Verify the hierarchy state after each step.

        :param remove_parent_func: function that takes two location tags a and b, wehre a is a child of b,
                                   and removes that relationship
        """
        locations = self._create_tags(3)
        locations[1].parents.add(locations[0])
        locations[2].parents.add(locations[1])
        locations[2].parents.add(locations[0])

        remove_parent_func(locations[1], locations[0])
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[2].id): {()},
        }, msg="hierarchy removal failed")

        remove_parent_func(locations[2], locations[1])
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[2].id): {()},
        }, msg="second hierarchy removal failed")

    def test_simple_remove_parent(self):
        """
        Run test simple add, remove the parent child relationships by removing the parent from the child
        """
        self._test_simple_remove(lambda a, b: a.parents.remove(b))

    def test_simple_remove_child(self):
        """
        Run test simple add, remove the parent child relationships by removing the child from the parent
        """
        self._test_simple_remove(lambda a, b: b.children.remove(a))

    def test_simple_clear_parents(self):
        """
        Create three location tags and turn them into a hierarchy chain with a shortcut from the top to bottom.
        Clear all the parents of the bottom location tag and verify the hierarchy.
        """
        locations = self._create_tags(3)
        locations[1].parents.add(locations[0])
        locations[2].parents.add(locations[1])
        locations[2].parents.add(locations[0])

        locations[2].parents.clear()
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[1].id): {()},
        }, msg="hierarchy clear failed")

    def test_simple_clear_children(self):
        """
        Create three location tags and turn them into a hierarchy chain with a shortcut from the top to bottom.
        Clear all the children of the top location tag and verify the hierarchy.
        """
        locations = self._create_tags(3)
        locations[1].parents.add(locations[0])
        locations[2].parents.add(locations[1])
        locations[2].parents.add(locations[0])

        locations[0].children.clear()
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
        }, msg="hierarchy clear failed")

    def test_add_multiple_parents(self):
        """
        Create four location tags.
        Step 1: Add #0 and #1 as parents of #2 and verify the location state
        Step 2: Add #1 and #2 as parents of #3 and verify the location state
        """
        locations = self._create_tags(4)
        locations[2].parents.add(locations[0], locations[1])
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
        }, msg="adding two parents once failed")

        locations[3].parents.add(locations[1], locations[2])
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[3].id): {(), (locations[2].id, )},
            AncestorDescendantTuple(locations[2].id, locations[3].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[3].id): {(locations[2].id, )},
        }, msg="adding two more parents failed")

    def test_add_multiple_children(self):
        """
        Create four location tags.
        Step 1: Add #1 and #2 as children of #0 and verify the location state
        Step 2: Add #2 and #3 as parents of #1 and verify the location state
        """
        locations = self._create_tags(4)
        locations[0].children.add(locations[1], locations[2])
        self.assertHierarchyState({
            AncestorDescendantTuple (locations[0].id, locations[1].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[2].id): {()},
        }, msg="adding two children once failed")

        locations[1].children.add(locations[2], locations[3])
        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[1].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[2].id): {(), (locations[1].id, )},
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[3].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[3].id): {(locations[1].id, )},
        }, msg="adding two more children failed")

    def _test_add_downwards_tree(self, add_parent_func: UpdateRelationFunc):
        """
        Create four location tags. Make the first three into a chain with a shortcut from top to bottom.
        Then make the top one (#0) into a child of #3. This adds an entire downwards "tree" to #3.
        Verify the location state.
        """
        locations = self._create_tags(4)

        add_parent_func(locations[1], locations[0])
        add_parent_func(locations[2], locations[1])
        add_parent_func(locations[2], locations[0])
        add_parent_func(locations[0], locations[3])

        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[1].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[2].id): {(), (locations[1].id,)},
            AncestorDescendantTuple(locations[3].id, locations[0].id): {()},
            AncestorDescendantTuple(locations[3].id, locations[1].id): {(locations[0].id,)},
            AncestorDescendantTuple(locations[3].id, locations[2].id): {(locations[0].id,), (locations[0].id, locations[1].id,)},
        }, msg="3→0→1→2 + 0→2 hierarchy failed")

    def test_add_downwards_tree_by_parent(self):
        """
        Run test add downwards tree, create the parent child relationships by adding the parent to the child
        """
        self._test_add_downwards_tree(lambda a, b: a.parents.add(b))

    def test_add_downwards_tree_by_child(self):
        """
        Run test add downwards tree, create the parent child relationships by adding the child to the parent
        """
        self._test_add_downwards_tree(lambda a, b: b.children.add(a))

    def _test_add_upwards_tree(self, add_parent_func: UpdateRelationFunc):
        """
        Create four location tags. Make the first three into a chain with a shortcut from top to bottom.
        Then make the bottom one (#0) into a parent of #3. This adds an entire upwards "tree" to #3.
        Verify the location state.
        """
        locations = self._create_tags(4)

        add_parent_func(locations[1], locations[0])
        add_parent_func(locations[2], locations[1])
        add_parent_func(locations[2], locations[0])
        add_parent_func(locations[3], locations[2])

        self.assertHierarchyState({
            AncestorDescendantTuple(locations[0].id, locations[1].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[2].id): {()},
            AncestorDescendantTuple(locations[0].id, locations[2].id): {(), (locations[1].id,)},
            AncestorDescendantTuple(locations[2].id, locations[3].id): {()},
            AncestorDescendantTuple(locations[1].id, locations[3].id): {(locations[2].id,)},
            AncestorDescendantTuple(locations[0].id, locations[3].id): {(locations[2].id,), (locations[1].id, locations[2].id,)},
        }, msg="0→1→2→3 + 0→2 hierarchy failed")

    def test_add_upwards_tree_by_parent(self):
        """
        Run test add upwards tree, create the parent child relationships by adding the parent to the child
        """
        self._test_add_upwards_tree(lambda a, b: a.parents.add(b))

    def test_add_upwards_tree_by_child(self):
        """
        Run test add upwards tree, create the parent child relationships by adding the child to the parent
        """
        self._test_add_upwards_tree(lambda a, b: b.children.add(a))

    def test_circular_fails(self):
        """
        Create three location tags and turn them into a chain.
        Try to add the bottom one as a parent to the top one, creating a circle. This needs to fail.
        """
        locations = self._create_tags(3)
        locations[0].children.add(locations[1])
        locations[1].children.add(locations[2])
        with self.assertRaises(CircularyHierarchyError):
            locations[2].children.add(locations[0])