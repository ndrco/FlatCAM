"""Regression tests for the tangential NCC entry ramp."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from shapely.geometry import LineString

with patch.object(sys, 'argv', [sys.argv[0]]):
    from camlib import CNCjob


class GCodePreprocessor:
    def z_feedrate_code(self, p):
        return 'G01 F%.1f' % p.z_feedrate

    def feedrate_code(self, p):
        return 'G01 F%.1f' % p.feedrate

    def down_code(self, p):
        return 'G01 Z%.4f' % p.z_cut

    def linear_code(self, p):
        return 'G01 X%.4f Y%.4f' % (p.x, p.y)

    def lift_code(self, p):
        return 'G00 Z%.4f' % p.z_move


class UnsupportedPreprocessor(GCodePreprocessor):
    def linear_code(self, p):
        return 'PA %.4f,%.4f' % (p.x, p.y)


def make_job(preprocessor=None):
    messages = []
    job = CNCjob.__new__(CNCjob)
    job.app = SimpleNamespace(
        defaults={
            'cncjob_coords_type': 'G90',
            'cncjob_coords_decimals': 4,
        },
        abort_flag=False,
        inform=SimpleNamespace(emit=messages.append),
    )
    job.decimals = 4
    job.pp_geometry = preprocessor or GCodePreprocessor()
    job.z_cut = -0.08
    job.z_move = 2.0
    job.z_feedrate = 100.0
    job.feedrate = 250.0
    job.feedrate_rapid = 1000.0
    job.segx = 0.0
    job.segy = 0.0
    job.coordinates_type = 'G90'
    job.entry_ramp_enabled = True
    job.entry_ramp_start_z = -0.03
    job.entry_ramp_length = 0.7
    job.entry_ramp_overcut = 0.02
    job.entry_ramp_recovery_length = 0.5
    job.entry_ramp_feedrate = 150.0
    job._entry_ramp_warned = False
    job._last_entry_ramp_distance = 0.0
    return job, messages


class NccEntryRampTest(unittest.TestCase):
    def test_ramp_overcuts_recovers_returns_and_repeats_start(self):
        job, _messages = make_job()

        gcode = job.linear2gcode(
            LineString([(10.0, 20.0), (12.0, 20.0)]),
            dia=1.0,
            cont=True,
            up=False,
        )

        expected_sequence = [
            'G01 Z-0.0300',
            'G01 F150.0',
            'G01 X10.7000 Y20.0000 Z-0.1000',
            'G01 F250.0',
            'G01 X11.2000 Y20.0000 Z-0.0800',
            'G01 X10.7000 Y20.0000 Z-0.0800',
            'G01 X10.0000 Y20.0000 Z-0.0800',
            'G01 X12.0000 Y20.0000',
        ]
        cursor = 0
        for command in expected_sequence:
            position = gcode.find(command, cursor)
            self.assertGreaterEqual(position, 0, command)
            cursor = position + len(command)
        self.assertAlmostEqual(job._last_entry_ramp_distance, 2.4)

    def test_short_path_scales_both_ramp_phases(self):
        profile, deepest_distance, actual_length = CNCjob._entry_ramp_profile(
            LineString([(0.0, 0.0), (0.6, 0.0)]),
            ramp_length=0.7,
            recovery_length=0.5,
            start_z=-0.03,
            deep_z=-0.10,
            cut_z=-0.08,
        )

        self.assertAlmostEqual(actual_length, 0.6)
        self.assertAlmostEqual(deepest_distance, 0.35)
        self.assertAlmostEqual(profile[1][1], 0.35)
        self.assertAlmostEqual(profile[1][3], -0.10)
        self.assertAlmostEqual(profile[-1][1], 0.6)
        self.assertAlmostEqual(profile[-1][3], -0.08)

    def test_unsupported_preprocessor_falls_back_to_vertical_plunge(self):
        job, messages = make_job(UnsupportedPreprocessor())

        gcode = job.linear2gcode(
            LineString([(0.0, 0.0), (2.0, 0.0)]),
            dia=1.0,
            cont=True,
            up=False,
        )

        self.assertIn('G01 Z-0.0800', gcode)
        self.assertNotIn('Z-0.1000', gcode)
        self.assertFalse(job.entry_ramp_enabled)
        self.assertEqual(len(messages), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
