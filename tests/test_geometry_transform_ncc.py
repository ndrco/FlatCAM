"""Regression tests for the displayed Geometry and the NCC reference boundary.

Run with FlatCAM's Python dependencies and FlatCAM on PYTHONPATH:
    python tests/test_geometry_transform_ncc.py
"""

import sys
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

# Importing the tool package also loads app_Main, which parses command-line args.
with patch.object(sys, 'argv', [sys.argv[0]]):
    from appTools.ToolNCC import NonCopperClear
    from camlib import Geometry


def make_app():
    return SimpleNamespace(
        abort_flag=False,
        inform=SimpleNamespace(emit=lambda *args: None),
        proc_container=SimpleNamespace(update_view_text=lambda *args: None),
    )


def make_reference(multigeo=True, shared=False):
    # The raised left-hand end makes a mirrored boundary visibly different,
    # even though its overall bounding rectangle is unchanged.
    polygon = Polygon(
        [(0, 0), (100, 0), (100, 40), (30, 40), (30, 80), (0, 80)],
        holes=[[(5, 5), (10, 5), (10, 10), (5, 10)]],
    )
    obj = Geometry.__new__(Geometry)
    obj.kind = 'geometry'
    obj.multigeo = multigeo
    obj.app = make_app()
    obj.solid_geometry = [polygon]
    obj.tools = {1: {'solid_geometry': obj.solid_geometry if shared else deepcopy([polygon])}}
    return obj


class GeometryTransformNCCTest(unittest.TestCase):
    def setUp(self):
        self.ncc = NonCopperClear.__new__(NonCopperClear)
        self.ncc.app = make_app()
        self.copper = SimpleNamespace(kind='gerber', solid_geometry=[Point(15, 60).buffer(3)])

    def boundary(self, reference):
        geometry, kind = self.ncc.calculate_bounding_box(self.copper, 2, reference)
        self.assertEqual(kind, 'geometry')
        return unary_union(geometry)

    def assert_same_area(self, actual, expected):
        self.assertLess(actual.symmetric_difference(expected).area, 1e-8)

    def test_mirror_keeps_display_and_ncc_in_sync(self):
        for axis in ('X', 'Y'):
            for multigeo in (False, True):
                for shared in (False, True):
                    with self.subTest(axis=axis, multigeo=multigeo, shared=shared):
                        ref = make_reference(multigeo, shared)
                        original = unary_union(ref.solid_geometry)
                        xscale, yscale = (1, -1) if axis == 'X' else (-1, 1)
                        expected = affinity.scale(original, xscale, yscale, origin=(50, 40))
                        ref.mirror(axis, (50, 40))
                        self.assert_same_area(unary_union(ref.solid_geometry), expected)
                        self.assert_same_area(self.boundary(ref), expected)
                        if multigeo:
                            self.assert_same_area(unary_union(ref.tools[1]['solid_geometry']), expected)
                        ref.mirror(axis, (50, 40))
                        self.assert_same_area(self.boundary(ref), original)

    def test_rotation_and_skew_keep_object_geometry_in_sync(self):
        for method, args, expected_func in (
            ('rotate', (37, (50, 40)), lambda p: affinity.rotate(p, 37, origin=(50, 40))),
            ('skew', (12, -5, (50, 40)), lambda p: affinity.skew(p, 12, -5, origin=(50, 40))),
        ):
            with self.subTest(method=method):
                ref = make_reference()
                expected = expected_func(unary_union(ref.solid_geometry))
                getattr(ref, method)(*args)
                self.assert_same_area(unary_union(ref.solid_geometry), expected)
                self.assert_same_area(self.boundary(ref), expected)

    def test_saved_old_project_uses_displayed_tool_geometry(self):
        ref = make_reference()
        old = unary_union(ref.solid_geometry)
        displayed = affinity.scale(old, -1, 1, origin=(50, 40))
        # Emulate a project saved by 2026.09.1 after mirroring.
        ref.tools[1]['solid_geometry'] = [displayed]
        self.assert_same_area(self.boundary(ref), displayed)
        self.assert_same_area(unary_union(ref.solid_geometry), old)  # read-only lookup

    def test_reference_collects_all_tools_and_nested_geometry(self):
        ref = make_reference()
        first, second = box(5, 10, 20, 30), box(75, 45, 90, 70)
        ref.tools = {1: {'solid_geometry': [[first]]}, 2: {'solid_geometry': second}}
        self.assert_same_area(self.boundary(ref), unary_union([first, second]))

    def test_empty_tool_geometry_does_not_revive_stale_boundary(self):
        ref = make_reference()
        ref.tools = {1: {'solid_geometry': []}}
        self.assertTrue(self.boundary(ref).is_empty)

    def test_ncc_toolpaths_stay_in_mirrored_reference(self):
        ref = make_reference()
        expected = affinity.scale(unary_union(ref.solid_geometry), -1, 1, origin=(50, 40))
        ref.mirror('Y', (50, 40))
        copper = affinity.scale(unary_union(self.copper.solid_geometry), -1, 1, origin=(50, 40))
        area = self.ncc.get_ncc_empty_area(copper, self.boundary(ref))
        self.assert_same_area(area, expected.difference(copper))

        storage = Geometry.clear_polygon(
            self.ncc, area, tooldia=1.0, steps_per_circle=32, overlap=0.3, connect=False)
        paths = unary_union(list(storage.get_objects()))
        self.assertFalse(paths.is_empty)
        self.assertTrue(expected.covers(paths))
        self.assertFalse(paths.intersects(copper))
        self.assertTrue(paths.intersects(box(75, 50, 95, 75)))
        self.assertFalse(paths.intersects(box(5, 50, 25, 75)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
