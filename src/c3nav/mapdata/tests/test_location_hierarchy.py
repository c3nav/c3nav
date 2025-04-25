from collections import defaultdict

from django.db.models.expressions import F
from django.db.models.query_utils import Q
from django.test.testcases import TransactionTestCase

from c3nav.mapdata.models.locations import DefinedLocation, LocationAdjacency, LocationRelationPath, LocationRelation


type LocationHierarchyState = dict[tuple[int, int], set[tuple[int, ...]]]


class LocationHierarchyTests(TransactionTestCase):
    def assertHierarchyState(self, state: LocationHierarchyState, msg="location hierarchy doesn't match"):
        self.assertQuerySetEqual(LocationRelationPath.objects.exclude(
            adjacency__child=F("relation__descendant")
        ), [], msg="Found relation path segment where adjacency child doesn't match relation descendant")

        self.assertQuerySetEqual(LocationRelationPath.objects.exclude(
            Q(prev_path__isnull=True, num_hops=0) | Q(prev_path__num_hops=F("num_hops")-1)
        ), [], msg="Found relation path segment with num_hops not matching prev_path")

        self.assertQuerySetEqual(LocationRelationPath.objects.exclude(
            Q(prev_path__isnull=True) | Q(relation__ancestor=F("prev_path__relation__ancestor"))
        ), [], msg="Found relation path segment with different relation ancestor than its prev_path")

        self.assertQuerySetEqual(LocationRelationPath.objects.exclude(
            Q(prev_path__isnull=True) | Q(adjacency__parent=F("prev_path__adjacency__child"))
        ), [], msg="Found relation path segment where adjacency parent doesn't match prev_path's adjacency child")

        relation_lookup: dict[tuple[int, int], set[tuple[int, ...]]] = {
            relation: set() for relation in LocationRelation.objects.values_list("ancestor_id", "descendant_id")
        }
        path_chains: dict[int | None, tuple[int, ...]] = {None: ()}

        for path_id, prev_path_id, ancestor, descendant in LocationRelationPath.objects.values_list(
                "pk", "prev_path_id", "relation__ancestor", "relation__descendant"
        ).order_by("num_hops"):
            path_chains[path_id] = (prev_path_chain := path_chains[prev_path_id]) + (descendant, )
            relation_lookup[(ancestor, descendant)].add(prev_path_chain)

        self.assertDictEqual(relation_lookup, state, msg)

    def test_single_parents_operations(self):
        location1 = DefinedLocation.objects.create()
        location2 = DefinedLocation.objects.create()
        location3 = DefinedLocation.objects.create()

        location2.parents.add(location1)
        self.assertHierarchyState({
            (location1.id, location2.id): {()},
        }, msg="a→b hierarchy failed")

        location3.parents.add(location2)
        self.assertHierarchyState({
            (location1.id, location2.id): {()},
            (location2.id, location3.id): {()},
            (location1.id, location3.id): {(location2.id,)},
        }, msg="a→b→c hierarchy failed")

        location3.parents.add(location1)
        self.assertHierarchyState({
            (location1.id, location2.id): {()},
            (location2.id, location3.id): {()},
            (location1.id, location3.id): {(), (location2.id,)},
        }, msg="a→b→c + a→c hierarchy failed")

        location2.parents.remove(location1)
        self.assertHierarchyState({
            (location2.id, location3.id): {()},
            (location1.id, location3.id): {()},
        }, msg="hierarchy removal failed")

    def test_single_childrens_operations(self):
        location1 = DefinedLocation.objects.create()
        location2 = DefinedLocation.objects.create()
        location3 = DefinedLocation.objects.create()

        location1.children.add(location2)
        self.assertHierarchyState({
            (location1.id, location2.id): {()},
        }, msg="a→b hierarchy failed")

        location2.children.add(location3)
        self.assertHierarchyState({
            (location1.id, location2.id): {()},
            (location2.id, location3.id): {()},
            (location1.id, location3.id): {(location2.id,)},
        }, msg="a→b→c hierarchy failed")

        location1.children.add(location3)
        self.assertHierarchyState({
            (location1.id, location2.id): {()},
            (location2.id, location3.id): {()},
            (location1.id, location3.id): {(), (location2.id,)},
        }, msg="a→b→c + a→c hierarchy failed")

        location1.children.remove(location2)
        self.assertHierarchyState({
            (location2.id, location3.id): {()},
            (location1.id, location3.id): {()},
        }, msg="hierarchy removal failed")
