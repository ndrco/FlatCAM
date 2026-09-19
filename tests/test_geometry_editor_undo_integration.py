import unittest
from types import SimpleNamespace

from PyQt5 import QtCore
from shapely.geometry import LineString

from appEditors.AppGeoEditor import AppGeoEditor, DrawToolShape, FCPolygon
from appEditors.EditorHistory import GeometryEditorHistory


class _Action:
	def __init__(self):
		self.enabled = False

	def setEnabled(self, enabled):
		self.enabled = enabled


class _ToolShape:
	def clear(self, update=True):
		pass

	def redraw(self):
		pass


class GeometryEditorUndoIntegrationTest(unittest.TestCase):
	def make_editor(self):
		editor = AppGeoEditor.__new__(AppGeoEditor)
		QtCore.QObject.__init__(editor)

		ui = SimpleNamespace(
			geo_undo_btn=_Action(),
			geo_undo_menuitem=_Action(),
			geo_redo_btn=_Action(),
			geo_redo_menuitem=_Action(),
		)
		editor.app = SimpleNamespace(
			ui=ui,
			inform=SimpleNamespace(emit=lambda *args: None),
		)
		editor.history = GeometryEditorHistory()
		editor.history_active = True
		editor.history_restoring = False
		editor.history_changed.connect(editor._update_history_actions)
		editor.storage = editor.make_storage()
		editor.utility = []
		editor.selected = []
		editor.active_tool = None
		editor.in_action = False
		editor.snap_x = 0
		editor.snap_y = 0
		editor.tool_shape = _ToolShape()

		editor.delete_utility_geometry = lambda: None
		editor.select_tool = lambda name: setattr(editor, 'selected_tool', name)
		editor.build_ui = lambda: None
		editor.replot = lambda: None
		editor.draw_utility_geometry = lambda geo: None
		return editor

	def test_completed_action_restores_storage_and_action_state(self):
		editor = self.make_editor()
		first = LineString([(0, 0), (1, 0)])
		second = LineString([(10, 0), (11, 0)])
		editor.storage.insert(DrawToolShape(first))
		editor.history.reset(editor._history_geometries())

		editor.storage.insert(DrawToolShape(second))
		self.assertTrue(editor.history_checkpoint('Add line'))
		self.assertTrue(editor.app.ui.geo_undo_btn.enabled)

		editor.undo_history()
		objects = list(editor.storage.get_objects())
		self.assertEqual(len(objects), 1)
		self.assertTrue(objects[0].geo.equals(first))
		self.assertEqual(editor.selected_tool, 'select')
		self.assertTrue(editor.app.ui.geo_redo_btn.enabled)

		editor.redo_history()
		objects = list(editor.storage.get_objects())
		self.assertEqual(len(objects), 2)
		self.assertTrue(any(shape.geo.equals(second) for shape in objects))

	def test_unfinished_polygon_undo_redo_changes_one_point(self):
		editor = self.make_editor()
		editor.history.reset([])
		tool = FCPolygon.__new__(FCPolygon)
		tool.draw_app = editor
		tool.complete = False
		tool.points = [(0, 0), (1, 0)]
		tool.redo_points = []
		editor.active_tool = tool
		editor.in_action = True

		editor.undo_history()
		self.assertEqual(tool.points, [(0, 0)])
		self.assertEqual(tool.redo_points, [(1, 0)])
		self.assertTrue(editor.app.ui.geo_redo_btn.enabled)

		editor.redo_history()
		self.assertEqual(tool.points, [(0, 0), (1, 0)])
		self.assertEqual(tool.redo_points, [])


if __name__ == '__main__':
	unittest.main(verbosity=2)
