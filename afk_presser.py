import atexit
import signal
import time

from numpy import random
from pynput import keyboard

keyboard_controller = keyboard.Controller()
running = False
exit_armed = False
should_exit = False
_cleaned_up = False

key_to_press = str(input("Enter a key: "))


def cleanup(*_args):
    """Release the key and stop listeners no matter how we exit."""
    global _cleaned_up, should_exit
    if _cleaned_up:
        return
    _cleaned_up = True
    should_exit = True

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
    global running, exit_armed
    if not running:
        running = True
        exit_armed = False
        print("Auto-pressing enabled.")


def handle_escape():
    """Pause on ESC and arm Shift+ESC exit."""
    global running, exit_armed
    if running:
        running = False
        exit_armed = True
        print("Paused. Press Ctrl+Alt+Shift+A to resume or Shift+ESC to exit.")
        return

def handle_shift_escape():
    """Exit only after ESC armed the shutdown."""
    global exit_armed, should_exit
    if exit_armed:
        print("Shift+ESC pressed. Exiting...")
        should_exit = True
        cleanup()
    else:
        print("Press ESC once before using Shift+ESC to exit.")


hotkeys = keyboard.GlobalHotKeys(
    {
        "<ctrl>+<alt>+<shift>+a": activate,
        "<esc>": handle_escape,
        "<shift>+<esc>": handle_shift_escape,
    }
)

# Start listening for hotkeys in the background
hotkeys.start()

# Ensure cleanup happens on normal exit, Ctrl+C, or SIGTERM
atexit.register(cleanup)
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

print(
    f"Press Ctrl+Alt+Shift+A to start pressing '{key_to_press}' repeatedly. "
    "Press ESC once to pause and Shift+ESC (after pausing) to exit."
)

try:
    while not should_exit:
        if running:
            keyboard_controller.press(key_to_press)
            time.sleep(random.uniform(0.1, 2))
            keyboard_controller.release(key_to_press)
            time.sleep(random.uniform(0.1, 5))
except KeyboardInterrupt:
    print("Keyboard interrupt received. Exiting...")
finally:
    cleanup()
