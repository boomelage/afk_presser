# Auto Key Presser

A small cross-platform desktop utility that taps a single key for you on a
randomised, human-ish schedule. Pick a key, set how long to hold it and how long
to wait between presses, then start it with a button or a global hotkey — handy
for keeping a session "active" while you're away from the keyboard.

The pressing logic lives in a UI-free engine (`presser_engine.py`) that
validates input up front, never busy-spins the CPU, and is built so a single bad
keystroke can't crash the loop. A thin PyQt5 GUI (`auto_presser.py`) sits on top.

> **Heads-up:** keystrokes are sent to whatever window is focused. Many games and
> online services prohibit automated input — use this where it's allowed (offline
> apps, your own tooling, accessibility, testing). You are responsible for how you
> use it.

---

## Features

- **Any key.** Single characters (`a`, `7`, `/`) or named special keys —
  `space`, `enter`, `tab`, `esc`, arrows, `f1`–`f20`, and more.
- **Two ways to choose the key.** Click **Capture…** and press the key you want,
  or pick one from the **Special** dropdown.
- **Randomised timing.** Separate min/max windows for how long the key is *held*
  and the *interval* before the next press, so the cadence isn't perfectly
  uniform.
- **Configurable global hotkey toggle.** A global hotkey (default
  `Ctrl+Shift+Alt`) starts/stops pressing even when the window isn't focused, so
  you can switch to your target window first. Click **Set hotkey…** and press
  the combination you want — it's remembered between runs.
- **Accident-resistant inputs.** The key and timing fields are read-only to
  typing (timing still adjusts via the spinner arrows and scroll wheel), so a
  stray keystroke — including the presser's own — can't silently reconfigure it.
- **One-click reset.** The **Default** button restores the timing fields.
- **CPU-friendly and crash-safe.** The worker thread *waits* instead of spinning,
  releases a held key on stop/shutdown, and reports errors instead of dying.

---

## Requirements

- **Python 3.8+** (CI builds use 3.12)
- Dependencies (see [`requirements.txt`](requirements.txt)):
  - [`PyQt5`](https://pypi.org/project/PyQt5/) `>=5.15` — the GUI
  - [`pynput`](https://pypi.org/project/pynput/) `>=1.7` — key injection + global hotkey

---

## Quick start (run from source)

```bash
# 1. Clone
git clone https://github.com/boomelage/auto_presser.git
cd auto_presser

# 2. (Recommended) create a virtual environment
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS:  source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python src/auto_presser.py
```

---

## Usage

1. **Choose the key.**
   - Click **Capture…**, then press any key — it's recorded in the field, or
   - Pick a named key from the **Special** dropdown (`space`, `enter`, `up`, `f5`, …).
2. **Set the timing** (all in seconds):
   - **Hold min / max** — how long the key stays down each press.
   - **Interval min / max** — the gap before the next press.
   - Each press picks a random value within these windows. Use **Default** to
     restore the starting values.
3. **(Optional) Set your toggle hotkey.** Click **Set hotkey…** under *Toggle
   hotkey*, then press the key combination you want (e.g. `Ctrl+Shift+Alt`,
   `Ctrl+Alt+P`, or `F8`). Your choice is saved and restored next launch. Click
   **Cancel** to keep the current one.
4. **Switch to your target window** — keys go to whatever is focused.
5. **Start pressing** with the **Start** button, or press your **toggle hotkey**
   (default `Ctrl+Shift+Alt`) from anywhere. Press it again (or click **Stop**)
   to halt.

The status line shows the current state: `Idle`, `Pressing '<key>'`, or an error.

### Defaults

| Setting        | Min    | Max    |
| -------------- | ------ | ------ |
| Hold (s)       | `0.05` | `0.12` |
| Interval (s)   | `0.50` | `2.00` |

Timing fields accept `0.00`–`60.00`. Internally, hold is floored at `0.01s` and
ranges are normalised (negatives clamped, min/max swapped if reversed).

---

## Building a standalone binary

[`build.py`](build.py) wraps **PyInstaller** to produce a single-file executable
for the OS it runs on (PyInstaller can't cross-compile — build on each target OS,
or use the CI workflow below).

```bash
pip install pyinstaller
python build.py            # onefile, windowed (no console)
python build.py --console  # keep a console window (handy for debugging)
python build.py --clean    # wipe PyInstaller caches first
```

Output lands in `build/<os>/`, where `<os>` is `windows` or `macos`.

### Continuous builds

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs the build on a
Windows / macOS matrix on every push to `master` or `test` (and on manual
dispatch), uploading each binary as a workflow artifact.

---

## Platform notes

- **Windows** — works out of the box.
- **macOS** — grant the app (or your terminal/Python) **Accessibility** *and*
  **Input Monitoring** under *System Settings → Privacy & Security*, or key
  presses silently do nothing.

---

## Project structure

```
auto_presser/
├── src/
│   ├── auto_presser.py     # PyQt5 GUI (entry point)
│   └── presser_engine.py   # UI-free KeyPresser engine + key parsing
├── build.py                # PyInstaller build helper (per-OS)
├── requirements.txt        # runtime dependencies
├── .github/workflows/
│   └── build.yml           # CI: cross-platform binary builds
└── LICENSE                 # GPL-2.0
```

### How it fits together

- **`presser_engine.py`** — the core, deliberately free of any UI so it can be
  driven by a GUI, a CLI, or a test.
  - `parse_key(text)` / `available_special_keys()` — turn user text into
    something `pynput` can press; raise `InvalidKeyError` on bad input.
  - `KeyPresser` — runs the press loop on a daemon thread that blocks on an
    event when idle (no CPU spin), interrupts long waits promptly on stop, and
    always releases a held key. Configure it with `set_key()` / `set_timing()`,
    drive it with `start()` / `stop()` / `toggle()` / `shutdown()`, and observe
    it via the `on_state_change` / `on_error` callbacks.
- **`auto_presser.py`** — builds the window, wires widgets to the engine, and
  marshals the engine's background-thread callbacks back onto the GUI thread with
  Qt signals. It also registers the global hotkey via `pynput`.

---

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Nothing is typed when running | The wrong window is focused — switch to your target first. On macOS, grant Accessibility + Input Monitoring. |
| `'<x>' is not a single character or a known special key` | Use a single character, or one of the names in the **Special** dropdown (e.g. `space`, `enter`, `up`, `f5`). |
| Global hotkey doesn't work | Another app may have claimed the combination (try **Set hotkey…** to pick another), or the OS needs input-monitoring permission (see platform notes). |
| `ModuleNotFoundError: PyQt5` / `pynput` | Install dependencies: `pip install -r requirements.txt`. |

---

## License

Released under the **GNU General Public License v2.0**. See [`LICENSE`](LICENSE).
