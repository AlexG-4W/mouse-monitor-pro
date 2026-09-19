# Mouse Monitor Pro v3

A high-performance hardware monitoring utility for mouse diagnostics, performance tracking, and hardware fault detection. This tool provides real-time overlays for polling rate, acceleration, and physical button health.


## Features

- Floating overlay: coordinates, cursor-speed-change index, cursor event rate, CPS,
  button-fault counters. Position follows the cursor or pins to the top of the monitor
  the cursor is on (left / centre / right).
- Skin, transparency, click-through and overlay position all apply live, without
  restarting the session.
- Session logging to CSV and movement heatmaps across the full virtual desktop.
- Scroll wheel telemetry with an encoder-wear detector, which reports that it cannot
  count rather than counting wrong on a high-resolution wheel.
- A window that survives being resized: content lives in a fixed-width column pinned
  to the left edge, and the window will not shrink below its content.
- Live graphs of cursor event rate and dV, drawn on a plain Tk canvas with no plotting
  dependency. They appear in the free space on the right **only when there is room for
  them** — below that width there are no graphs and no reserved empty area — and a line
  in the panel says so, because the window opens at its minimum size.
- A plain-text session summary written next to the CSV on stop: totals, peak rates,
  fault episodes, wheel health, pointer settings, and the report-period estimate with
  its full harmonic ladder and the conditions it was measured under. It opens with the
  app, CSV and summary format versions so a file attached to a bug report identifies
  its own build, and it **checks itself for contradictions** — a peak rate of zero
  next to thousands of events, a file reported as disabled that exists on disk — and
  prints them at the end rather than presenting impossible numbers as fact.
- Tray icon showing the live event rate; minimise to tray.
- English and Russian interface.

## 🚀 Key Features (v3.1 Update)


- **Live graphs.** Cursor event rate and `dV` over time, drawn next to the panel. They
  appear when the window is wide enough for the axis and its labels to be readable, and
  there are none at all below that width — no empty reserved space. A line in the panel
  tells you they exist, because the window opens at its minimum size.
  - A **gap in the line means there was no reading**, not a reading of zero. Nothing is
    drawn for time when no session was running, and the line is never interpolated
    across a gap.
  - The graphs and the panel lines are fed from the same place, so they cannot drift
    apart. The `dV` graph is labelled "relative index (no units)" and carries no
    coloured zones — there is no good or bad value to shade.
- **The version is visible in the program.** The window title now reads
  `Mouse Monitor Pro v3.1`, and the tray tooltip carries it too. Previously the version
  appeared only in the session summary — that is, only in a file, only after you had
  run and stopped a session.
- **A report-period estimate.** When you move the mouse fast enough for long enough,
  the panel reports the measured interval between device reports and names the standard
  step it lands on (125 / 250 / 500 / 1000 / 2000 Hz). When the conditions are not met
  it says so instead of guessing — see *Refused to guess* below.
- **A session summary** written next to the CSV when you stop: totals, peak rates,
  fault episodes, wheel health, pointer settings, and the report-period estimate with
  the conditions it was measured under. It checks itself for contradictions and prints
  them rather than presenting impossible numbers as fact.
- **Scroll wheel telemetry** with an encoder-wear indicator, which reports that it
  cannot count rather than counting wrong on a high-resolution wheel.
- **The window survives being resized.** Content sits in a fixed-width column pinned to
  the left edge; the window will not shrink below its content, and there is no longer a
  hard-coded height ceiling.
- **Russian interface** alongside English, switchable while running.



<img width="688" height="1381" alt="ui-narrow" src="https://github.com/user-attachments/assets/e2b60194-5eb6-4430-a887-3764a02f2883" />

<img width="1522" height="1381" alt="ui-main" src="https://github.com/user-attachments/assets/2e5f5c68-45e6-415e-b380-f439627719b0" />


# Mouse Monitor Pro 🖱️ (v2.0)

A high-performance Windows utility designed for gamers, developers, and hardware enthusiasts to analyze mouse sensor behavior and cursor precision in real-time.

## Key Features
- **📊 Session Analytics & Logging**: Record all mouse telemetry (coordinates, acceleration, polling rate, clicks) into CSV files for post-session analysis.
- **⚡ Click Frequency (CPS)**: Real-time Clicks Per Second display on the HUD overlay.
- **🔥 Cursor Heatmap**: Automatically generates a high-resolution movement heatmap (PNG) at the end of each session.
- **🎨 Advanced Overlay Styling**: 
  - **Transparency**: Adjustable alpha levels via slider.
  - **Click-through Mode**: HUD becomes non-interactive, allowing you to click on windows behind the overlay.
- **🧵 Thread-Safe & Low Latency**: Refactored queue-based architecture to ensure zero input lag and high stability even at 1000Hz+ polling rates.

![scr](https://github.com/user-attachments/assets/d7ccab12-0381-40c7-beaf-4eac62ae4977)

### Anti-cheat

Moved to the top of this file — see [Do not run it while playing a game with kernel
anti-cheat](#2-do-not-run-it-while-playing-a-game-with-kernel-anti-cheat). It belongs
before the download link, not in a notes section.

### Antivirus

The executable is unsigned and installs a global input hook, so SmartScreen and some
AV heuristics will flag it. UPX compression — itself a common heuristic trigger — is
explicitly disabled in the build spec.



## Technical Highlights
- **High-Precision Timing**: Uses `time.perf_counter()` for sub-millisecond accuracy in Hz and Acceleration calculation.
- **Hardware Detection**: Identifies mouse manufacturer and Windows sensitivity (DPI) settings.
- **Dynamic Tray Icon**: The current polling rate (Hz) is displayed directly on the system tray icon.
- **Visual Skins**: Multiple themes including Dark (Default), Cyberpunk, and Matrix.

## Installation & Usage
1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Run the application**:
   ```bash
   python mouse_info_app.py
   ```

Building the executable
pip install pyinstaller
pyinstaller MouseMonitorPro.spec
Produces dist\MouseMonitorPro.exe, a single file of roughly 21 MB when
built in a clean virtual environment. Building inside an environment that has
many unrelated packages installed produces a noticeably larger file — the same
spec gave 34 MB on the development machine — because PyInstaller collects what
it finds. The spec embeds
the DPI-awareness manifest, sets console=False, and disables UPX on purpose (UPX is a
common antivirus heuristic trigger and is not on most machines' PATH anyway).

## Requirements
- **OS**: Windows 10 / 11
- **Python**: 3.7 or higher

## License
This project is open-source. Feel free to contribute or modify for personal use.
