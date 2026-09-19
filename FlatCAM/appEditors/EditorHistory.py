from dataclasses import dataclass
from threading import RLock

from shapely import wkb


@dataclass(frozen=True)
class _HistoryState:
	geometry: tuple
	size: int
	label: str


class GeometryEditorHistory:
	"""Bounded snapshot history for the Geometry Editor.

	The editor's RTree cannot be copied safely, therefore only the Shapely
	geometry is stored.  WKB keeps the snapshots independent from the mutable
	``DrawToolShape`` wrappers and is significantly smaller than WKT.
	"""

	def __init__(self, max_steps=30, max_bytes=128 * 1024 * 1024):
		self.max_steps = max(1, int(max_steps))
		self.max_bytes = max(1, int(max_bytes))
		self._states = []
		self._index = -1
		self._total_bytes = 0
		self._lock = RLock()

	@staticmethod
	def _encode_geometry(geometry):
		if geometry is None:
			return 'none', None
		if isinstance(geometry, list):
			return 'list', tuple(GeometryEditorHistory._encode_geometry(item) for item in geometry)
		if isinstance(geometry, tuple):
			return 'tuple', tuple(GeometryEditorHistory._encode_geometry(item) for item in geometry)
		return 'wkb', wkb.dumps(geometry)

	@staticmethod
	def _decode_geometry(encoded):
		kind, value = encoded
		if kind == 'none':
			return None
		if kind == 'list':
			return [GeometryEditorHistory._decode_geometry(item) for item in value]
		if kind == 'tuple':
			return tuple(GeometryEditorHistory._decode_geometry(item) for item in value)
		return wkb.loads(value)

	@staticmethod
	def _encoded_size(encoded):
		kind, value = encoded
		if kind == 'wkb':
			return len(value)
		if kind in {'list', 'tuple'}:
			return sum(GeometryEditorHistory._encoded_size(item) for item in value)
		return 0

	@classmethod
	def _make_state(cls, geometries, label=''):
		encoded = tuple(cls._encode_geometry(geometry) for geometry in geometries)
		return _HistoryState(
			geometry=encoded,
			size=sum(cls._encoded_size(item) for item in encoded),
			label=label
		)

	def clear(self):
		with self._lock:
			self._states = []
			self._index = -1
			self._total_bytes = 0

	def reset(self, geometries):
		with self._lock:
			self.clear()
			state = self._make_state(geometries, label='Initial state')
			self._states.append(state)
			self._index = 0
			self._total_bytes = state.size

	def record(self, geometries, label=''):
		with self._lock:
			state = self._make_state(geometries, label=label)
			if self._index >= 0 and state.geometry == self._states[self._index].geometry:
				return False

			# A new edit after Undo starts a new branch.
			if self._index < len(self._states) - 1:
				removed = self._states[self._index + 1:]
				self._total_bytes -= sum(item.size for item in removed)
				del self._states[self._index + 1:]

			self._states.append(state)
			self._index = len(self._states) - 1
			self._total_bytes += state.size
			self._trim()
			return True

	def _trim(self):
		# max_steps counts user actions, therefore one extra state is retained
		# for the state before the oldest available action.
		max_states = self.max_steps + 1
		while len(self._states) > max_states:
			removed = self._states.pop(0)
			self._total_bytes -= removed.size
			self._index -= 1

		# Always retain the current state and one state to which Undo can return.
		while self._total_bytes > self.max_bytes and len(self._states) > 2:
			removed = self._states.pop(0)
			self._total_bytes -= removed.size
			self._index -= 1

	def can_undo(self):
		with self._lock:
			return self._index > 0

	def can_redo(self):
		with self._lock:
			return 0 <= self._index < len(self._states) - 1

	def undo(self):
		with self._lock:
			if not self.can_undo():
				return None
			self._index -= 1
			return self.current()

	def redo(self):
		with self._lock:
			if not self.can_redo():
				return None
			self._index += 1
			return self.current()

	def current(self):
		with self._lock:
			if self._index < 0:
				return None
			return [self._decode_geometry(item) for item in self._states[self._index].geometry]

	@property
	def undo_label(self):
		with self._lock:
			if not self.can_undo():
				return ''
			return self._states[self._index].label

	@property
	def redo_label(self):
		with self._lock:
			if not self.can_redo():
				return ''
			return self._states[self._index + 1].label

	@property
	def state_count(self):
		with self._lock:
			return len(self._states)

	@property
	def total_bytes(self):
		with self._lock:
			return self._total_bytes
