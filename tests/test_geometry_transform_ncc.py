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
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

# Importing the tool package also loads app_Main, which parses command-line args.
with patch.object(sys, 'argv', [sys.argv[0]]):
    from appObjects.FlatCAMGeometry import GeometryObject
    from appTools.ToolCutOut import CutOut
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

    def test_rest_machining_keeps_single_difference_polygon_iterable(self):
        area = MultiPolygon([box(0, 0, 10, 10)])
        remaining = area.difference(box(0, 0, 5, 10))
        self.assertIsInstance(remaining, Polygon)

        normalized = self.ncc._as_multipolygon(remaining)

        self.assertIsInstance(normalized, MultiPolygon)
        self.assertEqual(len(normalized.geoms), 1)
        self.assert_same_area(normalized, remaining)

    def test_rest_machining_ignores_non_polygon_collection_parts(self):
        polygon = box(1, 1, 4, 4)
        mixed = GeometryCollection([polygon, LineString([(0, 0), (5, 5)])])

        normalized = self.ncc._as_multipolygon(mixed)

        self.assertEqual(len(normalized.geoms), 1)
        self.assert_same_area(normalized, polygon)

    def test_any_form_cutout_keeps_l_shape_and_internal_curved_slot(self):
        outer_coords = [
            (0, 0), (30, 0), (30, 10), (10, 10),
            (10, 30), (0, 30), (0, 0),
        ]
        outer = Polygon(outer_coords)
        slot = Point(20, 5).buffer(2, resolution=24)

        # Gerber follow geometry commonly stores each Edge-Cuts segment
        # separately, including the small segments used to approximate arcs.
        follow_geometry = [
            LineString([coords[index], coords[index + 1]])
            for coords in (outer_coords, list(slot.exterior.coords))
            for index in range(len(coords) - 1)
        ]

        paths = CutOut._gerber_cutout_paths(follow_geometry, offset=0.5)

        self.assertEqual(len(paths), 2)
        outer_cut = Polygon(next(path for path, internal in paths if not internal))
        slot_cut = Polygon(next(path for path, internal in paths if internal))
        self.assertGreater(outer_cut.area, outer.area)
        self.assertFalse(outer_cut.covers(Point(20, 20)))
        self.assertLess(slot_cut.area, slot.area)
        self.assertTrue(slot_cut.contains(Point(20, 5)))

        too_large_paths, adjusted = CutOut._gerber_cutout_paths(
            follow_geometry, offset=2.1, return_adjusted=True
        )
        self.assertEqual(len(too_large_paths), 2)
        self.assertEqual(adjusted, 1)
        fallback_slot = Polygon(next(path for path, internal in too_large_paths if internal))
        self.assertTrue(fallback_slot.contains(Point(20, 5)))
        self.assertLess(fallback_slot.area, slot_cut.area)

    def test_thin_gap_uses_the_same_physical_tool_without_second_toolchange(self):
        main_geometry = [LineString([(0, 0), (10, 0)])]
        gap_geometry = [LineString([(10, 0), (12, 0)])]
        tool = {
            'tooldia': 3.175,
            'data': {'cutz': -2.0, 'multidepth': True, 'depthperpass': 0.5},
            'solid_geometry': main_geometry
        }
        CutOut._set_thin_gap_operation(
            tool, gap_geometry, cutz=-0.4, multidepth=False, depthperpass=0.5
        )

        class RecordingJob:
            def __init__(self):
                self.calls = []

            def geometry_tool_gcode_gen(self, tool_number, tools, **kwargs):
                self.calls.append((tool_number, tools, kwargs))
                toolchange = 'T%d\n' % tool_number if kwargs['toolchange'] else ''
                return toolchange + 'Z%s\n' % tools[tool_number]['data']['cutz'], \
                    'START\n' if kwargs['is_first'] else ''

        job = RecordingJob()
        gcode, start_gcode, geometry = GeometryObject._generate_tool_cut_operations(
            job_obj=job, tooluid=1, tool=tool, tolerance=0.001,
            is_first_tool=True, is_last_tool=True
        )

        self.assertEqual(len(job.calls), 2)
        self.assertEqual([call[0] for call in job.calls], [1, 1])
        self.assertEqual([call[2]['toolchange'] for call in job.calls], [True, False])
        self.assertEqual([call[1][1]['data']['cutz'] for call in job.calls], [-2.0, -0.4])
        self.assertTrue(job.calls[0][2]['is_first'])
        self.assertTrue(job.calls[1][2]['is_last'])
        self.assertEqual(start_gcode, 'START\n')
        self.assertEqual(len(geometry), 2)
        self.assertEqual(gcode.count('T1'), 1)
        self.assertNotIn('9999', gcode)

    def test_legacy_thin_gap_tool_is_migrated_to_one_tool(self):
        obj = GeometryObject.__new__(GeometryObject)
        obj.tools = {
            1: {
                'tooldia': 3.175,
                'data': {'cutz': -2.0},
                'solid_geometry': [LineString([(0, 0), (10, 0)])]
            },
            9999: {
                'tooldia': 3.175,
                'data': {'cutz': -0.4, 'override_color': '#29a3a3fa'},
                'solid_geometry': [LineString([(10, 0), (12, 0)])]
            }
        }

        obj._migrate_legacy_thin_gap_tool()

        self.assertEqual(list(obj.tools), [1])
        operation = obj.tools[1]['extra_cut_operations'][0]
        self.assertEqual(operation['kind'], 'thin_gap')
        self.assertEqual(operation['data']['cutz'], -0.4)
        self.assertEqual(operation['plot_color'], '#29a3a3fa')

    @staticmethod
    def make_geometry_form_storage_object():
        class Entry:
            def __init__(self, value):
                self.value = value

            def get_value(self):
                return self.value

        class Item:
            def __init__(self, value):
                self.value = value

            def text(self):
                return str(self.value)

        class Combo:
            def __init__(self, value):
                self.value = value

            def currentText(self):
                return self.value

        class Table:
            @staticmethod
            def rowCount():
                return 1

            @staticmethod
            def currentRow():
                return 0

            @staticmethod
            def item(row, column):
                return Item(3.175 if column == 1 else 1)

            @staticmethod
            def cellWidget(row, column):
                return Combo({2: 'Path', 3: 'Rough', 4: 'C1'}[column])

        gap_operation = {
            'kind': 'thin_gap',
            'solid_geometry': [LineString([(10, 0), (12, 0)])],
            'data': {'cutz': -0.4},
            'plot_color': '#29a3a3fa'
        }
        obj = GeometryObject.__new__(GeometryObject)
        obj.tools = {
            1: {
                'tooldia': 3.175,
                'offset': 'Path',
                'offset_value': 0.0,
                'type': 'Rough',
                'tool_type': 'C1',
                'data': {'cutz': -2.0},
                'solid_geometry': [LineString([(0, 0), (10, 0)])],
                'extra_cut_operations': [gap_operation],
            }
        }
        obj.form_fields = {'cutz': Entry(-2.1)}
        obj.ui = SimpleNamespace(
            geo_tools_table=Table(),
            tool_offset_entry=Entry(0.0),
            grid3=SimpleNamespace(indexOf=lambda widget: -1),
        )
        obj.ui_disconnect = lambda: None
        obj.ui_connect = lambda: None
        obj.sender = lambda: None
        return obj

    def test_geometry_form_updates_preserve_thin_gap_operation(self):
        for update_method in ('gui_form_to_storage', 'on_apply_param_to_all_clicked'):
            with self.subTest(update_method=update_method):
                obj = self.make_geometry_form_storage_object()

                getattr(obj, update_method)()

                operation = obj.tools[1]['extra_cut_operations'][0]
                self.assertEqual(operation['kind'], 'thin_gap')
                self.assertEqual(operation['data']['cutz'], -0.4)
                self.assertEqual(obj.tools[1]['data']['cutz'], -2.1)

    def test_ncc_entry_ramp_data_is_migrated_to_geometry_tool(self):
        obj = GeometryObject.__new__(GeometryObject)
        obj.default_data = {
            'entry_ramp': False,
            'entry_ramp_start_z': -0.03,
            'entry_ramp_length': 0.7,
            'entry_ramp_overcut': 0.02,
            'entry_ramp_recovery_length': 0.5,
            'entry_ramp_feedrate': 150.0,
        }
        obj.tools = {
            1: {
                'data': {
                    'tools_ncc_ramp': True,
                    'tools_ncc_ramp_start_z': -0.02,
                    'tools_ncc_ramp_length': 0.8,
                    'tools_ncc_ramp_overcut': 0.03,
                    'tools_ncc_ramp_recovery_length': 0.4,
                    'tools_ncc_ramp_feedrate': 120.0,
                }
            }
        }

        obj._migrate_entry_ramp_data()

        data = obj.tools[1]['data']
        self.assertTrue(data['entry_ramp'])
        self.assertEqual(data['entry_ramp_start_z'], -0.02)
        self.assertEqual(data['entry_ramp_length'], 0.8)
        self.assertEqual(data['entry_ramp_overcut'], 0.03)
        self.assertEqual(data['entry_ramp_recovery_length'], 0.4)
        self.assertEqual(data['entry_ramp_feedrate'], 120.0)
        self.assertFalse(any(key.startswith('tools_ncc_ramp') for key in data))

    @staticmethod
    def make_cutz_object(tool_type, cutz=-0.8):
        class Entry:
            def __init__(self, value):
                self.value = value

            def get_value(self):
                return self.value

            def set_value(self, value):
                self.value = value

        class Item:
            def __init__(self, value):
                self.value = value

            def text(self):
                return str(self.value)

        class Combo:
            def currentText(self):
                return tool_type

        class Table:
            @staticmethod
            def currentRow():
                return 0

            @staticmethod
            def item(row, column):
                return Item(1.0 if column == 1 else 1)

            @staticmethod
            def cellWidget(row, column):
                return Combo() if column == 4 else None

        obj = GeometryObject.__new__(GeometryObject)
        obj.decimals = 4
        obj.old_cutz = -1.2
        obj.tools = {1: {'data': {'cutz': cutz}}}
        obj.ui = SimpleNamespace(
            geo_tools_table=Table(),
            tipdia_entry=Entry(0.1),
            tipangle_entry=Entry(30.0),
            cutz_entry=Entry(cutz),
        )
        return obj

    def test_c1_tool_keeps_manual_cutz_when_hidden_v_fields_are_loaded(self):
        obj = self.make_cutz_object('C1')

        obj.update_cutz()

        self.assertEqual(obj.ui.cutz_entry.get_value(), -0.8)
        self.assertEqual(obj.tools[1]['data']['cutz'], -0.8)

    def test_v_tool_still_calculates_cutz_from_tip_geometry(self):
        obj = self.make_cutz_object('V')

        obj.update_cutz()

        self.assertEqual(obj.ui.cutz_entry.get_value(), -1.6794)
        self.assertEqual(obj.tools[1]['data']['cutz'], -1.6794)


if __name__ == '__main__':
    unittest.main(verbosity=2)
