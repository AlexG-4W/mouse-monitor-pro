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

## Building the Executable (EXE)
To create a standalone portable executable, use PyInstaller:
```bash
pyinstaller --noconsole --onefile --name "MouseMonitorPro" mouse_info_app.py
```

## Requirements
- **OS**: Windows 10 / 11
- **Python**: 3.7 or higher

## License
This project is open-source. Feel free to contribute or modify for personal use.
