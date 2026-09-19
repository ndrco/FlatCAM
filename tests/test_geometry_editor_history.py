import unittest

from shapely.geometry import LineString, Point, Polygon

from appEditors.EditorHistory import GeometryEditorHistory


class GeometryEditorHistoryTest(unittest.TestCase):
	def test_history_undo_redo_round_trip(self):
		history = GeometryEditorHistory()
		initial = [LineString([(0, 0), (1, 0)])]
		edited = [LineString([(0, 0), (2, 0)]), Point(3, 4)]

		history.reset(initial)
		self.assertTrue(history.record(edited, label='Move'))
		self.assertTrue(history.can_undo())
		self.assertEqual(history.undo_label, 'Move')

		undone = history.undo()
		self.assertEqual(len(undone), 1)
		self.assertTrue(undone[0].equals(initial[0]))
		self.assertTrue(history.can_redo())

		redone = history.redo()
		self.assertEqual(len(redone), 2)
		self.assertTrue(redone[0].equals(edited[0]))
		self.assertTrue(redone[1].equals(edited[1]))

	def test_history_preserves_nested_geometry_and_ignores_duplicates(self):
		history = GeometryEditorHistory()
		geometry = [[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])]]

		history.reset(geometry)
		self.assertFalse(history.record(geometry, label='Duplicate'))
		self.assertEqual(history.state_count, 1)

		restored = history.current()
		self.assertIsInstance(restored[0], list)
		self.assertTrue(restored[0][0].equals(geometry[0][0]))

	def test_new_edit_after_undo_discards_redo_branch(self):
		history = GeometryEditorHistory()
		history.reset([Point(0, 0)])
		history.record([Point(1, 0)], label='First')
		history.record([Point(2, 0)], label='Second')

		history.undo()
		self.assertTrue(history.can_redo())
		history.record([Point(1, 1)], label='Branch')

		self.assertFalse(history.can_redo())
		self.assertTrue(history.current()[0].equals(Point(1, 1)))

	def test_history_is_bounded_by_action_count_and_memory(self):
		history = GeometryEditorHistory(max_steps=2, max_bytes=1)
		history.reset([Point(0, 0)])
		history.record([Point(1, 0)])
		history.record([Point(2, 0)])
		history.record([Point(3, 0)])

		# Even with a deliberately tiny memory budget the current state and one
		# usable Undo state are retained.
		self.assertEqual(history.state_count, 2)
		self.assertTrue(history.can_undo())
		self.assertTrue(history.undo()[0].equals(Point(2, 0)))


if __name__ == '__main__':
	unittest.main(verbosity=2)
