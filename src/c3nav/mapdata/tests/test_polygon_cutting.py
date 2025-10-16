from typing import Union

from django.test.testcases import TestCase
from shapely import Polygon, LineString, GeometryCollection, MultiPolygon, normalize

from c3nav.mapdata.utils.geometry.generaty import cut_polygons_with_lines


class PolygonCuttingTests(TestCase):
    def _assertCutResult(self,
                         polygons: Union[Polygon, MultiPolygon, GeometryCollection], lines: list[LineString],
                         expected_result: tuple[Union[Polygon, MultiPolygon], ...]):

        actual_result = tuple(cut_polygons_with_lines(polygons, lines))
        # print("actual", actual_result)
        # print("expected", expected_result)
        # print("expected normalized", [normalize(item) for item in expected_result])
        self.assertSetEqual(  # pragma: no branch
            {normalize(item) for item in actual_result},
            {normalize(item) for item in expected_result}
        )

    # tests with no polygon, thus no change
    def test_no_polygon_no_lines(self):
        polygons = GeometryCollection()
        self._assertCutResult(polygons, [], ())

    def test_no_polygon_one_line(self):
        polygons = GeometryCollection()
        line = LineString([(20, 20), (20, 21)])
        self._assertCutResult(polygons, [line], ())

    def test_no_polygon_two_lines(self):
        polygons = GeometryCollection()
        lines = [
            LineString([(20, 20), (20, 21)]),
            LineString([(22, 22), (22, 21)]),
        ]
        self._assertCutResult(polygons, lines, ())

    def test_no_polygon_two_intersecting_lines(self):
        polygons = GeometryCollection()
        lines = [
            LineString([(0, 0), (20, 0)]),
            LineString([(10, -10), (10, 20)]),
        ]
        self._assertCutResult(polygons, lines, ())

    def test_no_polygon_self_intersecting_line(self):
        polygons = GeometryCollection()
        lines = [
            LineString([(0, 0), (20, 0), (10, 5), (10, -2)]),
        ]
        self._assertCutResult(polygons, lines, ())

    def test_no_polygon_consecutive_lines(self):
        polygons = GeometryCollection()
        lines = [
            LineString([(0, 0), (20, 0)]),
            LineString([(20, 0), (21, 0), (21, 2)]),
        ]
        self._assertCutResult(polygons, lines, ())

    # tests with no lines, thus no change
    def test_no_lines_no_holes(self):
        polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        self._assertCutResult(polygon, [], (polygon, ))

    def test_no_lines_with_hole(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 6), (6, 6), (6, 4)]])
        self._assertCutResult(polygon, [], (polygon, ))

    def test_no_lines_two_polygons(self):
        polygons = (
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(10, 0), (11, 0), (11, 1), (10, 1)]),
        )
        self._assertCutResult(MultiPolygon(polygons), [], polygons)

    def test_no_lines_polygon_in_polygon(self):
        polygons = (
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(1, 1), (1, 9), (9, 9), (9, 1)]]),
            Polygon([(2, 2), (8, 2), (8, 8), (2, 8)]),
        )
        self._assertCutResult(MultiPolygon(polygons), [], polygons)

    def test_no_lines_polygon_in_polygon_touching(self):
        polygons = (
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(1, 1), (1, 9), (9, 9), (9, 1)]]),
            Polygon([(2, 2), (8, 2), (8, 8), (6, 9), (2, 8)]),
        )
        self._assertCutResult(MultiPolygon(polygons), [], polygons)

    def test_no_lines_touching_polygons(self):
        polygons = (
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 1), (1, 2), (2, 2), (2, 1)]),
        )
        self._assertCutResult(MultiPolygon(polygons), [], polygons)

    def test_no_lines_separate_holes(self):
        polygon = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [
                [(1, 1), (1, 2), (2, 2), (2, 1)],
                [(3, 3), (3, 4), (4, 4), (4, 3)],
            ],
        )
        self._assertCutResult(polygon, [], (polygon, ))

    def test_no_lines_corner_touching_holes(self):
        polygon = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [
                [(1, 1), (1, 3), (3, 3), (3, 1)],
                [(3, 3), (4, 3), (4, 4), (3, 4)],
            ],
        )
        self._assertCutResult(polygon, [], (polygon, ))

    def test_no_lines_corner_side_touching_holes(self):
        polygon = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [
                [(1, 1), (1, 3), (3, 3), (3, 1)],
                [(3, 2), (4, 3), (5, 2), (4, 1)],
            ],
        )
        self._assertCutResult(polygon, [], (polygon, ))

    # test with lines outside, thus no change
    def test_line_outside_no_holes(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(20, 20), (20, 21)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_outside_with_hole(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 6), (6, 6), (6, 4)]])
        line = LineString([(20, 20), (20, 21)])
        self._assertCutResult(polygon, [line], (polygon, ))

    # test with lines outside, but touching, thus no change
    def test_line_touching_outside_point(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(10, 5), (15, 5)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_touching_outside_multi_contact(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(10, 5), (15, 5), (10, 4)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_touching_outside_fully_on_ring(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(0, 1), (0, 5)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_touching_outside_partially_on_ring(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(0, 1), (0, 11)])
        self._assertCutResult(polygon, [line], (polygon, ))

    # test with lines in hole, touching or not, thus no change
    def test_line_in_hole(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 8), (8, 8), (8, 4)]])
        line = LineString([(5, 5), (6, 6)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_in_hole_touches_point(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 8), (8, 8), (8, 4)]])
        line = LineString([(5, 5), (8, 6)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_in_hole_fully_on_ring(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 8), (8, 8), (8, 4)]])
        line = LineString([(8, 6), (8, 7)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_in_hole_partially_on_ring(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 8), (8, 8), (8, 4)]])
        line = LineString([(5, 5), (8, 6), (8, 7)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_in_hole_through_two_touching_holes(self):
        polygon = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [
                [(1, 1), (1, 3), (3, 3), (3, 1)],
                [(3, 3), (5, 3), (5, 5), (3, 5)],
            ],
        )
        line = LineString([(2, 2), (4, 4)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_through_two_touching_holes_multi_contact(self):
        polygon = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [
                [(1, 1), (1, 3), (3, 3), (3, 1)],
                [(3, 3), (5, 3), (5, 5), (3, 5)],
            ],
        )
        line = LineString([(1, 2), (2, 2), (4, 4), (3, 4)])
        self._assertCutResult(polygon, [line], (polygon, ))

    # test with line ending in polygon, thus no change
    def test_line_ends_in_polygon_once_from_outside(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(9, 5), (11, 5)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_ends_in_polygon_twice_from_outside(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(9, 5), (11, 5), (9, 4)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_ends_in_polygon_once_from_inside(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 8), (8, 8), (8, 4)]])
        line = LineString([(6, 6), (9, 6)])
        self._assertCutResult(polygon, [line], (polygon, ))

    def test_line_ends_in_polygon_twice_from_inside(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 8), (8, 8), (8, 4)]])
        line = LineString([(2, 2), (5, 5), (9, 6)])
        self._assertCutResult(polygon, [line], (polygon, ))

    # test with line cutting a ring only once, thus no change
    def test_line_cuts_ring_once(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(1, 1), (1, 9), (9, 9), (9, 1)]])
        line = LineString([(5, -1), (5, 2)])
        self._assertCutResult(polygon, [line], (polygon, ))

    # test cuts of one polygon with no holes
    def test_cut_no_holes_through_cut(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(5, -1), (5, 11)])
        result = (
            Polygon([(0, 0), (5, 0), (5, 10), (0, 10)]),
            Polygon([(5, 0), (10, 0), (10, 10), (5, 10)]),
        )
        self._assertCutResult(polygon, [line], result)

    def test_cut_no_holes_touching_cut(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(5, 0), (5, 10)])
        result = (
            Polygon([(0, 0), (5, 0), (5, 10), (0, 10)]),
            Polygon([(5, 0), (10, 0), (10, 10), (5, 10)]),
        )
        self._assertCutResult(polygon, [line], result)

    def test_cut_no_holes_double_cut(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = LineString([(5, 0), (5, 10), (6, 0)])
        result = (
            Polygon([(0, 0), (5, 0), (5, 10), (0, 10)]),
            Polygon([(5, 0), (5, 10), (6, 0)]),
            Polygon([(6, 0), (10, 0), (10, 10), (5, 10)]),
        )
        self._assertCutResult(polygon, [line], result)

    # test cuts of one polygon with one hole
    def test_cut_one_hole_cut_corner_throughu(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 8), (8, 8), (8, 4)]])
        line = LineString([(9, -1), (9, 2), (11, 2)])
        result = (
            Polygon([(0, 0), (9, 0), (9, 2), (10, 2), (10, 10), (0, 10)], [[(4, 4), (4, 8), (8, 8), (8, 4)]]),
            Polygon([(9, 0), (10, 0), (10, 2), (9, 2)]),
        )
        self._assertCutResult(polygon, [line], result)

    # test cuts of one polygon ring
    def test_cut_one_hole_cut_ring_through(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 6), (6, 6), (6, 4)]])
        line = LineString([(5, -1), (5, 11)])
        result = (
            Polygon([(0, 0), (5, 0), (5, 4), (4, 4), (4, 6), (5, 6), (5, 10), (0, 10)]),
            Polygon([(10, 0), (5, 0), (5, 4), (6, 4), (6, 6), (5, 6), (5, 10), (10, 10)]),
        )
        self._assertCutResult(polygon, [line], result)

    def test_cut_one_hole_cut_ring_touch(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 6), (6, 6), (6, 4)]])
        line = LineString([(5, 0), (5, 4), (4, 0)])
        result = (
            Polygon([(0, 0), (4, 0), (5, 4), (5, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 6), (6, 6), (6, 4)]]),
            Polygon([(5, 0), (5, 4), (4, 0)]),
        )
        self._assertCutResult(polygon, [line], result)

    def test_cut_one_hole_cut_ring_overlap(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 6), (6, 6), (6, 4)]])
        line = LineString([(5, 4), (5, 0), (4, 0), (5, 4)])
        result = (
            Polygon([(0, 0), (4, 0), (5, 4), (5, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (4, 6), (6, 6), (6, 4)]]),
            Polygon([(5, 0), (5, 4), (4, 0)]),
        )
        self._assertCutResult(polygon, [line], result)

    # more complex cut edge cases
    def test_cut_c_in_a_c(self):
        polygons = (
            Polygon([(0, 0), (0, 10), (10, 10), (10, 9), (1, 9), (1, 1), (10, 1), (10, 0)]),
            Polygon([(2, 2), (2, 8), (10, 8), (10, 7), (3, 7), (3, 3), (10, 3), (10, 2)]),
        )
        line = LineString([(8, -1), (8, 11)])
        result = (
            Polygon([(0, 0), (0, 10), (8, 10), (8, 9), (1, 9), (1, 1), (8, 1), (8, 0)]),
            Polygon([(2, 2), (2, 8), (8, 8), (8, 7), (3, 7), (3, 3), (8, 3), (8, 2)]),
            Polygon([(8, 0), (8, 1), (10, 1), (10, 0)]),
            Polygon([(8, 2), (8, 3), (10, 3), (10, 2)]),
            Polygon([(8, 10), (8, 9), (10, 9), (10, 10)]),
            Polygon([(8, 8), (8, 7), (10, 7), (10, 8)]),
        )
        self._assertCutResult(MultiPolygon(polygons), [line], result)

    # make sure floating point errors don't hurt this process
    def test_cut_angle_floating_point_errors(self):
        polygon = Polygon([(0, 0), (0, 10), (10, 10+1/13), (10, 0)])
        line = LineString([(8/9, -1), (12/7, 12)])
        mask = Polygon([(8/9, -1), (12/7, 12), (11, 12), (11, -1)])
        result = (
            polygon.difference(mask),
            polygon.intersection(mask)
        )
        self._assertCutResult(polygon, [line], result)