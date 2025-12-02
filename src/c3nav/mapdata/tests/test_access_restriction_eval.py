from typing import Iterable
from unittest.mock import Mock, call

from django.test.testcases import TestCase

from c3nav.mapdata.permissions import AccessRestrictionsAllIDs, \
    NoAccessRestrictions, AccessRestrictionsOneID, AccessRestrictionsOr, AccessRestrictionsAnd


class AccessRestrictionQueryset(TestCase):
    """
    Building
    """
    def test_build_one(self):
        self.assertIs(AccessRestrictionsOneID.build(None), NoAccessRestrictions)
        self.assertEqual(AccessRestrictionsOneID.build(1), AccessRestrictionsAllIDs(frozenset({1})))

    def test_build_all_ids(self):
        self.assertIs(AccessRestrictionsAllIDs.build(()), NoAccessRestrictions)
        self.assertEqual(AccessRestrictionsAllIDs.build((1, 2)), AccessRestrictionsAllIDs(frozenset({1, 2})))

    def test_can_see_no_restrictions(self):
        self.assertTrue(NoAccessRestrictions.can_see(frozenset()))
        self.assertTrue(NoAccessRestrictions.can_see(frozenset({2})))

    """
    Can see
    """
    def assertBatchCanSee(self, value,
                          assert_false: Iterable[Iterable[int]],
                          assert_true: Iterable[Iterable[int]]):
        for item in assert_false:
            item = frozenset(item)
            self.assertFalse(value.can_see(item), f"can_see({item}) is not False")
        for item in assert_true:
            item = frozenset(item)
            self.assertTrue(value.can_see(item), f"can_see({item}) is not True")

    def test_batch_can_see(self):
        results = {frozenset({1}): True,
                   frozenset({2}): True,
                   frozenset({3}): False,
                   frozenset({4}): False}
        try:
            values = Mock(can_see=Mock(side_effect=lambda i: results[i]))
            try:
                self.assertBatchCanSee(values, assert_true=({1}, {2}), assert_false=({3}, {4}))
            except AssertionError:
                self.fail("assertBatchCanSee failed when it shouldn't")
            values.can_see.assert_has_calls([call(key) for key in results.keys()], any_order=True)
            self.assertEqual(values.can_see.call_count, 4)

            for key in tuple(results.keys()):
                results[key] = not results[key]
                values.reset_mock()
                with self.assertRaises(AssertionError):
                    self.assertBatchCanSee(values, assert_true=({1}, {2}), assert_false=({3}, {4}))
                values.can_see.assert_called_with(key)
                self.assertLessEqual(values.can_see.call_count, 4)
                results[key] = not results[key]
        except Exception as e:
            e.add_note(f"with values: {results}")
            raise

    def test_can_see_all_ids_one(self):
        self.assertBatchCanSee(
            AccessRestrictionsAllIDs.build((1,)).simplify(),
            assert_false=({}, {2}),
            assert_true=({1, 2}, {1}),
        )

    def test_can_see_all_ids(self):
        self.assertBatchCanSee(
            AccessRestrictionsAllIDs.build((1, 2)).simplify(),
            assert_false=({}, {2}, {1}),
            assert_true=({1, 2},),
        )
        value = AccessRestrictionsAllIDs.build((1, 2)).simplify()

    def test_none_or_ids(self):
        self.assertIs(NoAccessRestrictions | AccessRestrictionsOneID.build(1), NoAccessRestrictions)
        self.assertIs(AccessRestrictionsOneID.build(1) | NoAccessRestrictions, NoAccessRestrictions)

    def test_none_and_ids(self):
        only_1 = AccessRestrictionsOneID.build(1)
        self.assertEqual(NoAccessRestrictions & only_1, only_1)
        self.assertEqual(only_1 & NoAccessRestrictions, only_1)

    def test_ids_or_ids(self):
        value = (AccessRestrictionsAllIDs.build({1, 2})
                 | AccessRestrictionsOneID.build(3)).simplify()
        self.assertIsInstance(value, AccessRestrictionsOr)
        self.assertBatchCanSee(
            value,
            assert_false=({}, {1}, {2}, {4}),
            assert_true=({1, 2}, {1, 2, 3}, {3}, {3, 1}, {3, 4})
        )

    def test_ids_and_ids(self):
        value = (AccessRestrictionsAllIDs.build({1, 2})
                 & AccessRestrictionsAllIDs.build({3})).simplify()
        self.assertIsInstance(value, AccessRestrictionsAllIDs)
        self.assertBatchCanSee(
            value,
            assert_false=({}, {1}, {3}, {1, 2}, {1, 4}),
            assert_true=({1, 2, 3}, {1, 2, 3, 4})
        )

    def test_and_or(self):
        value = (
            (AccessRestrictionsAllIDs.build({1, 2})
             | AccessRestrictionsAllIDs.build({3, 4}))
            & (AccessRestrictionsAllIDs.build({5})
               | AccessRestrictionsAllIDs.build({6}))
        ).simplify()
        self.assertIsInstance(value, AccessRestrictionsAnd)
        self.assertBatchCanSee(
            value,
            assert_false=({}, {1}, {2}, {3}, {4}, {5}, {6}, {7},
                          {1, 2}, {3, 4}, {1, 3, 6}, {1, 3, 7},
                          {1, 2}, {3, 4}, {1, 3, 5, 6}, {1, 2, 7}),
            assert_true=({1, 2, 5}, {3, 4, 5}, {1, 2, 3, 4, 5}, {1, 2, 3, 5},
                         {1, 2, 6}, {3, 4, 6}, {1, 2, 5, 6}, {3, 4, 6, 7}),
        )

    """
    Analysis
    """
    def test_relevant_permissions(self):
        self.assertSetEqual(
            NoAccessRestrictions.relevant_permissions,
            set(),
        )
        self.assertSetEqual(
            (
                (AccessRestrictionsAllIDs.build({1, 2})
                 | AccessRestrictionsAllIDs.build({3, 4}))
                & (AccessRestrictionsAllIDs.build({5})
                   | AccessRestrictionsAllIDs.build({6}))
            ).simplify().relevant_permissions,
            {1, 2, 3, 4, 5, 6},
        )

    def test_no_minimum_permissions(self):
        self.assertSetEqual(
            NoAccessRestrictions.minimum_permissions,
            set(),
        )
        self.assertSetEqual(
            (AccessRestrictionsAllIDs.build({1, 2})
             | AccessRestrictionsAllIDs.build({3, 4})).simplify().minimum_permissions,
            set(),
        )
        self.assertSetEqual(
            (
                (AccessRestrictionsAllIDs.build({1, 2})
                 | AccessRestrictionsAllIDs.build({3, 4}))
                & (AccessRestrictionsAllIDs.build({5})
                   | AccessRestrictionsAllIDs.build({6}))
            ).simplify().minimum_permissions,
            set(),
        )

    def test_all_some_minimum_permissions(self):
        self.assertSetEqual(
            AccessRestrictionsAllIDs.build((1, 2)).minimum_permissions,
            {1, 2},
        )
        self.assertSetEqual(
            (AccessRestrictionsAllIDs.build((1, 3, 2))
             | AccessRestrictionsAllIDs.build((1, 3, 4))).minimum_permissions,
            {1, 3},
        )
        self.assertSetEqual(
            ((AccessRestrictionsAllIDs.build((1, 3, 2))
              | AccessRestrictionsAllIDs.build((1, 3, 4)))
             & AccessRestrictionsOneID.build(6)).minimum_permissions,
            {1, 3, 6},
        )

    """
    Flatten
    """
    def test_flatten_none(self):
        self.assertEqual(NoAccessRestrictions.flatten(), frozenset())

    def test_flatten_all_ids(self):
        value = AccessRestrictionsAllIDs.build((1, 3, 2))
        self.assertSetEqual(value.flatten(), frozenset({frozenset({1, 2, 3})}))

    def test_flatten_or(self):
        value = (
            AccessRestrictionsAllIDs.build((1, 2)) |
            AccessRestrictionsOneID.build(3)
        )
        self.assertSetEqual(value.flatten(), frozenset({
            frozenset({1, 2}),
            frozenset({3}),
        }))

    def test_flatten_and(self):
        value = (
            AccessRestrictionsAllIDs.build((1, 2))
            | AccessRestrictionsOneID.build(3)
        ) & (
            AccessRestrictionsOneID.build(4)
            | AccessRestrictionsAllIDs.build((5, 6))
        ) & (
            AccessRestrictionsOneID.build(7)
            | AccessRestrictionsOneID.build(8)
        )
        self.assertSetEqual(value.flatten(), frozenset({
            frozenset({1, 2, 4, 7}),
            frozenset({1, 2, 4, 8}),
            frozenset({1, 2, 5, 6, 7}),
            frozenset({1, 2, 5, 6, 8}),
            frozenset({3, 4, 7}),
            frozenset({3, 4, 8}),
            frozenset({3, 5, 6, 7}),
            frozenset({3, 5, 6, 8}),
        }))

    """
    Simplify
    """
    def test_simplify_none(self):
        self.assertIs(NoAccessRestrictions.simplify(), NoAccessRestrictions)

    def test_simplify_all_ids(self):
        value = AccessRestrictionsAllIDs.build((1, 3, 2))
        self.assertIs(value.simplify(), value)

    def test_simplify_or(self):
        self.assertIsInstance(
            (AccessRestrictionsAllIDs.build((1, 3, 2))
             | AccessRestrictionsAllIDs.build((1, 3, 4))).simplify(),
            AccessRestrictionsAnd,
        )

    def test_simplify_and(self):
        value = ((AccessRestrictionsAllIDs.build((1, 2))
                  | AccessRestrictionsAllIDs.build((1, 3, 4)))
                 & (AccessRestrictionsAllIDs.build((5, 6))
                    | AccessRestrictionsAllIDs.build((5, 8))))
        self.assertIsInstance(value, AccessRestrictionsAnd)
        self.assertIsNone(value.ids)
        value = value.simplify()
        self.assertIsInstance(value, AccessRestrictionsAnd)
        self.assertIsInstance(value.ids, AccessRestrictionsAllIDs)

