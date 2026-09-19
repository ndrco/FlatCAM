"""Regression tests for orderly FlatCAM shutdown."""

import sys
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

with patch.object(sys, 'argv', [sys.argv[0]]):
	from app_Main import App, ArgsThread
	from PyQt5 import QtWidgets


class CleanShutdownTest(unittest.TestCase):
	def test_listener_close_is_safe_before_listener_exists(self):
		listener = ArgsThread()
		listener.close_listener()

		self.assertTrue(listener.thread_exit)

	def test_listener_close_wakes_blocking_accept(self):
		listener = ArgsThread()
		with tempfile.TemporaryDirectory() as temp_dir:
			listener.address = (os.path.join(temp_dir, 'flatcam-test-ipc'), 'AF_UNIX')
			errors = []

			def run_listener():
				try:
					listener.my_loop(listener.address)
				except BaseException as err:
					errors.append(err)

			worker = threading.Thread(target=run_listener)
			worker.start()

			for _ in range(100):
				if listener.listener is not None:
					break
				time.sleep(0.01)

			listener.close_listener()
			worker.join(1)

			self.assertFalse(worker.is_alive())
			self.assertEqual(errors, [])

	def test_quit_stops_existing_pool_without_recreating_it(self):
		qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
		app = App.__new__(App)
		app._shutdown_in_progress = False
		app.call_source = 'app'
		app.is_legacy = True
		app.mm = app.mp = app.mr = app.mdc = app.kp = object()
		app.plotcanvas = SimpleNamespace(graph_event_disconnect=Mock())
		app.preferencesUiManager = SimpleNamespace(save_defaults=Mock())
		app.log = SimpleNamespace(debug=Mock())
		app.cmd_line_headless = True
		app.new_launch = SimpleNamespace(close_listener=Mock())
		app.listen_th = SimpleNamespace(quit=Mock(), wait=Mock(return_value=True))
		app.workers = SimpleNamespace(shutdown=Mock())
		app.pool = SimpleNamespace(terminate=Mock(), join=Mock())

		with patch.object(App, 'clear_pool') as clear_pool, \
				patch('app_Main.os._exit') as process_exit:
			app.quit_application()

		self.assertTrue(app._shutdown_in_progress)
		app.new_launch.close_listener.assert_called_once_with()
		app.listen_th.quit.assert_called_once_with()
		app.listen_th.wait.assert_called_once_with(3000)
		app.workers.shutdown.assert_called_once_with()
		app.pool.terminate.assert_called_once_with()
		app.pool.join.assert_called_once_with()
		clear_pool.assert_not_called()
		process_exit.assert_called_once_with(0)

		# Re-entrant close events must not tear resources down twice.
		app.quit_application()
		app.pool.terminate.assert_called_once_with()
		self.assertIsNotNone(qt_app)


if __name__ == '__main__':
	unittest.main(verbosity=2)
