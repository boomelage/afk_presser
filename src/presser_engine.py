"""Core engine for the AFK key presser.

Kept deliberately free of any UI so it can be driven by a GUI, a CLI, or a
test. It validates the requested key up front, runs the press loop on a
background thread that *waits* instead of busy-spinning, and never lets a bad
keystroke take down the whole program.
"""

from __future__ import annotations

import random
import threading
from typing import Callable, Optional, Union

from pynput import keyboard

# Friendly names -> the attribute name of the matching pynput special key, so
# users can pick keys that have no printable character (space, enter, arrows,
# function keys, ...). Resolved through getattr below because not every key
# exists on every platform -- e.g. macOS has no Insert key, so
# ``keyboard.Key.insert`` is undefined there and must be skipped rather than
# crash the whole module on import.
_SPECIAL_KEY_NAMES: dict[str, str] = {
    "space": "space",
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "esc": "esc",
    "escape": "esc",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "pageup": "page_up",
    "page_up": "page_up",
    "pagedown": "page_down",
    "page_down": "page_down",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "caps_lock": "caps_lock",
    "capslock": "caps_lock",
}
# Function keys f1..f20 map to identically named attributes.
for _i in range(1, 21):
    _SPECIAL_KEY_NAMES[f"f{_i}"] = f"f{_i}"

# Resolve to actual keys, dropping any this platform/pynput build doesn't expose.
_SPECIAL_KEYS: dict[str, keyboard.Key] = {}
for _friendly, _attr in _SPECIAL_KEY_NAMES.items():
    _key = getattr(keyboard.Key, _attr, None)
    if _key is not None:
        _SPECIAL_KEYS[_friendly] = _key

KeySpec = Union[str, keyboard.Key]


class InvalidKeyError(ValueError):
    """Raised when the requested key cannot be understood."""


def parse_key(text: Optional[str]) -> KeySpec:
    """Turn user text into something pynput can actually press.

    A single character is pressed literally; multi-character input is matched
    case-insensitively against the named special keys. Anything else raises
    ``InvalidKeyError`` with a message safe to show the user.
    """
    if text is None:
        raise InvalidKeyError("No key provided.")
    stripped = text.strip()
    if stripped == "":
        raise InvalidKeyError("No key provided.")
    if len(stripped) == 1:
        return stripped
    lowered = stripped.lower()
    if lowered in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[lowered]
    raise InvalidKeyError(
        f"'{text}' is not a single character or a known special key "
        "(e.g. space, enter, tab, up, f5)."
    )


def available_special_keys() -> list[str]:
    """Canonical, de-duplicated list of named keys for a UI to offer."""
    canonical = {
        "space", "enter", "tab", "esc", "backspace", "delete", "insert",
        "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
        "caps_lock",
    }
    canonical.update(k for k in _SPECIAL_KEYS if k.startswith("f") and k[1:].isdigit())
    # Only offer keys that actually resolved on this platform (macOS, for
    # instance, has no Insert key).
    canonical &= _SPECIAL_KEYS.keys()
    return sorted(canonical, key=lambda s: (s[0] != "f" or not s[1:].isdigit(), s))


def _clamp_range(low: float, high: float, *, floor: float = 0.0) -> tuple[float, float]:
    """Normalise a (min, max) pair: non-negative and low <= high."""
    low = max(floor, float(low))
    high = max(floor, float(high))
    if low > high:
        low, high = high, low
    return low, high


class KeyPresser:
    """Repeatedly presses a single key with randomised, human-ish timing.

    The loop lives on a daemon thread. ``start()``/``stop()`` toggle pressing
    without ever spinning the CPU: when idle the thread blocks on an event.
    """

    def __init__(
        self,
        *,
        on_state_change: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._controller = keyboard.Controller()
        self._key: KeySpec = "a"
        self._key_label = "a"

        # Timing windows (seconds). Hold = how long the key stays down each
        # press; interval = the gap before the next press.
        self._hold_min, self._hold_max = 0.05, 0.12
        self._gap_min, self._gap_max = 0.5, 2.0
        self._lock = threading.Lock()

        self._active = threading.Event()      # set => currently pressing
        self._shutdown = threading.Event()    # set => tear the thread down
        self._key_is_down = False

        self._on_state_change = on_state_change
        self._on_error = on_error

        self._thread = threading.Thread(target=self._run, name="presser", daemon=True)
        self._thread.start()

    # -- configuration -----------------------------------------------------
    def set_key(self, text: str) -> None:
        """Validate and store the key. Raises InvalidKeyError if unusable."""
        key = parse_key(text)
        with self._lock:
            self._key = key
            self._key_label = text.strip()

    def set_timing(
        self,
        hold_min: float,
        hold_max: float,
        gap_min: float,
        gap_max: float,
    ) -> None:
        """Update the randomised hold/interval windows (seconds)."""
        h_min, h_max = _clamp_range(hold_min, hold_max, floor=0.01)
        g_min, g_max = _clamp_range(gap_min, gap_max, floor=0.0)
        with self._lock:
            self._hold_min, self._hold_max = h_min, h_max
            self._gap_min, self._gap_max = g_min, g_max

    @property
    def is_running(self) -> bool:
        return self._active.is_set()

    # -- control -----------------------------------------------------------
    def start(self) -> None:
        if not self._active.is_set():
            self._active.set()
            self._emit_state("running")

    def stop(self) -> None:
        if self._active.is_set():
            self._active.clear()
            self._release_key()
            self._emit_state("idle")

    def toggle(self) -> None:
        self.stop() if self._active.is_set() else self.start()

    def shutdown(self) -> None:
        """Stop pressing, release the key, and end the worker thread."""
        self._active.clear()
        self._shutdown.set()
        self._active.set()  # wake the thread so it can observe shutdown
        self._release_key()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # -- internals ---------------------------------------------------------
    def _run(self) -> None:
        try:
            while not self._shutdown.is_set():
                # Block (no CPU spin) until we're told to press or shut down.
                self._active.wait()
                if self._shutdown.is_set():
                    break
                with self._lock:
                    key = self._key
                    hold = random.uniform(self._hold_min, self._hold_max)
                    gap = random.uniform(self._gap_min, self._gap_max)
                try:
                    self._controller.press(key)
                    self._key_is_down = True
                    self._interruptible_sleep(hold)
                    self._controller.release(key)
                    self._key_is_down = False
                    self._interruptible_sleep(gap)
                except Exception as exc:  # never let one bad press kill the loop
                    self._key_is_down = False
                    self._active.clear()
                    self._emit_error(f"Could not press key: {exc}")
                    self._emit_state("idle")
        finally:
            self._release_key()

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep, but wake immediately if asked to stop or shut down."""
        # Waiting on the shutdown event lets us bail out of a long gap fast.
        self._shutdown.wait(timeout=seconds)

    def _release_key(self) -> None:
        if self._key_is_down:
            try:
                with self._lock:
                    self._controller.release(self._key)
            except Exception:
                pass
            self._key_is_down = False

    def _emit_state(self, state: str) -> None:
        if self._on_state_change is not None:
            self._on_state_change(state)

    def _emit_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)
