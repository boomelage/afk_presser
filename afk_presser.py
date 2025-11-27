import atexit
import signal
import time

from numpy import random
from pynput import keyboard

keyboard_controller = keyboard.Controller()
running = False
_cleaned_up = False

key_to_press = str(input("Enter a key: "))


def cleanup(*_args):
    """Release the key and stop listeners no matter how we exit."""
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True

    try:
        keyboard_controller.release(key_to_press)
    except Exception:
        pass

    try:
        hotkeys.stop()
    except Exception:
        pass


def activate():
    """Enable key pressing when Ctrl+Alt+Shift+A is hit."""
    global running
    if not running:
        running = True
        print("Auto-pressing enabled.")


def pause():
    """Pause key pressing without stopping the listener."""
    global running
    if running:
        running = False
        print("Paused. Press Ctrl+Alt+Shift+A to resume.")


hotkeys = keyboard.GlobalHotKeys(
    {
        "<ctrl>+<alt>+<shift>+a": activate,
        "<esc>": pause,
    }
)

# Start listening for hotkeys in the background
hotkeys.start()

# Ensure cleanup happens on normal exit, Ctrl+C, or SIGTERM
atexit.register(cleanup)
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

print(f"Press Ctrl+Alt+Shift+A to start pressing '{key_to_press}' repeatedly. Press ESC to pause.")

try:
    while True:
        if running:
            keyboard_controller.press(key_to_press)
            time.sleep(random.uniform(0.1, 2))
            keyboard_controller.release(key_to_press)
            time.sleep(random.uniform(0.1, 5))
except KeyboardInterrupt:
    print("Keyboard interrupt received. Exiting...")
finally:
    cleanup()
