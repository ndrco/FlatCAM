"""Regression tests for Delete-key handling in Geometry parameter editors."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

with patch.object(sys, 'argv', [sys.argv[0]]):
	from PyQt5 import QtCore, QtGui, QtWidgets
	from appGUI.MainGUI import MainGUI
	from appObjects.FlatCAMGeometry import GeometryObject
	from app_Main import App


class DeleteKeyRegressionTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

	def test_text_and_numeric_editors_keep_the_delete_key(self):
		widgets = [
			QtWidgets.QLineEdit(),
			QtWidgets.QTextEdit(),
			QtWidgets.QPlainTextEdit(),
			QtWidgets.QSpinBox(),
			QtWidgets.QDoubleSpinBox(),
		]
		editable_combo = QtWidgets.QComboBox()
		editable_combo.setEditable(True)
		widgets.append(editable_combo)

		for widget in widgets:
			with self.subTest(widget=type(widget).__name__):
				self.assertTrue(MainGUI._widget_uses_delete_for_text_editing(widget))

		self.assertFalse(MainGUI._widget_uses_delete_for_text_editing(QtWidgets.QLabel()))
		non_editable_combo = QtWidgets.QComboBox()
		self.assertFalse(MainGUI._widget_uses_delete_for_text_editing(non_editable_combo))

	def test_geometry_delete_handler_accepts_keyboard_call_without_argument(self):
		obj = GeometryObject.__new__(GeometryObject)
		obj.ui_disconnect = Mock()
		obj.ui_connect = Mock()
		obj.builduiSig = SimpleNamespace(emit=Mock())
		obj.ui = SimpleNamespace(
			geo_tools_table=SimpleNamespace(selectedItems=Mock(return_value=[]))
		)
		obj.app = SimpleNamespace(inform=SimpleNamespace(emit=Mock()))

		obj.on_tool_delete()

		obj.ui_disconnect.assert_called_once_with()
		obj.ui_connect.assert_called_once_with()
		obj.builduiSig.emit.assert_called_once_with()

	def test_delete_in_numeric_editor_does_not_reach_app_shortcut(self):
		app = SimpleNamespace(
			collection=SimpleNamespace(
				get_active=Mock(return_value=None),
				get_selected=Mock(return_value=[]),
				get_names=Mock(return_value=[]),
			),
			call_source='app',
			on_delete_keypress=Mock(),
		)
		window = SimpleNamespace(
			app=app,
			_widget_uses_delete_for_text_editing=MainGUI._widget_uses_delete_for_text_editing,
		)
		event = QtGui.QKeyEvent(
			QtCore.QEvent.KeyPress, QtCore.Qt.Key_Delete, QtCore.Qt.NoModifier
		)
		spinner = QtWidgets.QDoubleSpinBox()

		with patch.object(QtWidgets.QApplication, 'focusWidget', return_value=spinner):
			MainGUI.keyPressEvent(window, event)

		app.on_delete_keypress.assert_not_called()

	def test_app_keyboard_delete_passes_non_button_signal_explicitly(self):
		active = SimpleNamespace(kind='geometry', on_tool_delete=Mock())
		app = App.__new__(App)
		app.ui = SimpleNamespace(
			notebook=SimpleNamespace(
				currentWidget=Mock(return_value=SimpleNamespace(objectName=Mock(return_value='properties_tab')))
			)
		)
		app.collection = SimpleNamespace(get_active=Mock(return_value=active))

		app.on_delete_keypress()

		active.on_tool_delete.assert_called_once_with(clicked_signal=False)


if __name__ == '__main__':
	unittest.main(verbosity=2)
