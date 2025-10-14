from django.test.testcases import TransactionTestCase

from c3nav.mapdata.models import AccessRestriction, Theme
from c3nav.mapdata.models.locations import LocationTag, LabelSettings
from c3nav.mapdata.render.theme import ColorManager


class LocationInheritanceTests(TransactionTestCase):
    def setUp(self):
        LocationTag.objects.all().delete()
        self.access_restriction = AccessRestriction.objects.create(titles={"en": "Restriction 1"})
        self.label_settings = LabelSettings.objects.create()
        self.theme = Theme.objects.create(description="MyTheme")

    def _create_tags(self, priorities: tuple[int, ...]):
        return LocationTag.objects.bulk_create([LocationTag(priority=priority) for priority in priorities])  # pragma: no branch

    def _recalculate(self):
        LocationTag.evaluate_location_tag_relations()

    def test_triple_tree_and_two_singles(self):
        parent = LocationTag.objects.create(priority=5, titles={"en": "parent"}) # 8
        children = [
            LocationTag.objects.create(priority=3, titles={"en": "child1"}), # 9
            LocationTag.objects.create(priority=1, titles={"en": "child2"}), # 10
            LocationTag.objects.create(priority=2, titles={"en": "child3"}), # 11
        ]
        singles = [
            LocationTag.objects.create(priority=3, titles={"en": "single1"}), # 12 → 2
            LocationTag.objects.create(priority=6, titles={"en": "single2"}), # 13 → 0
        ]
        for child in children:
            child.parents.add(parent)
        LocationTag.evaluate_location_tag_relations()

        self.assertQuerySetEqual(
            LocationTag.objects.order_by("effective_downwards_breadth_first_order"),
            (singles[1], parent, singles[0], children[0], children[2], children[1]),
            msg="downwards breadth first order doesnt match"
        )
        print(LocationTag.objects.values_list("pk", "effective_downwards_depth_first_pre_order"))
        self.assertQuerySetEqual(
            LocationTag.objects.order_by("effective_downwards_depth_first_pre_order"),
            (singles[1], parent, children[0], children[2], children[1], singles[0]),
            msg="downwards depth first pre-order doesnt match"
        )
        self.assertQuerySetEqual(
            LocationTag.objects.order_by("effective_downwards_depth_first_post_order"),
            (singles[1], children[0], children[2], children[1], parent, singles[0]),
            msg="downwards depth first post-order doesnt match"
        )
        self.assertQuerySetEqual(
            LocationTag.objects.order_by("effective_upwards_breadth_first_order"),
            (singles[1], children[0], singles[0], children[2], children[1], parent),
            msg="upwards breadth first order doesnt match"
        )
        self.assertQuerySetEqual(
            LocationTag.objects.order_by("effective_upwards_depth_first_pre_order"),
            (singles[1], children[0], parent, singles[0], children[2], children[1]),
            msg="upwards depth first pre-order doesnt match"
        )
        self.assertQuerySetEqual(
            LocationTag.objects.order_by("effective_upwards_depth_first_post_order"),
            (singles[1], parent, children[0], singles[0], children[2], children[1]),
            msg="upwards depth first post-order doesnt match"
        )
