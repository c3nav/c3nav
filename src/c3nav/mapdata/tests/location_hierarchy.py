from collections import defaultdict

from django.db.models.expressions import F
from django.db.models.query_utils import Q
from django.test.testcases import TransactionTestCase

from c3nav.mapdata.models.locations import DefinedLocation, LocationAdjacency, LocationRelationPath, LocationRelation


type LocationHierarchyState = dict[tuple[int, int], list[tuple[int, ...]]]


class LocationHierarchyTests(TransactionTestCase):
    def assertHierarchyState(self, state: LocationHierarchyState):
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

        relation_lookup: dict[tuple[int, int], list[tuple[int, ...]]] = {
            relation: [] for relation in LocationRelation.objects.values_list("ancestor_id", "descendant_id")
        }
        path_chains: dict[int | None, tuple[int, ...]] = {None: ()}

        for path_id, prev_path_id, ancestor, descendant in LocationRelationPath.objects.values_list(
                "pk", "prev_path_id", "relation__ancestor", "relation__descendant"
        ).order_by("num_hops"):
            path_chains[path_id] = (prev_path_chain := path_chains[prev_path_id]) + (descendant, )
            relation_lookup[(ancestor, descendant)].append(prev_path_chain)

        self.assertDictEqual(relation_lookup, state, "location hierarchy doesn't match")

    def test_simple_parent(self):
        location1 = DefinedLocation.objects.create()
        location2 = DefinedLocation.objects.create()
        location2.parents.add(location1)

        self.assertHierarchyState({
            (location1.id, location2.id): [()]
        })