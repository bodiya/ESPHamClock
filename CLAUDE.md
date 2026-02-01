# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ESPHamClock is a kiosk-style application for amateur radio operators providing real-time space weather, radio propagation models, DX spots, and operating events. Originally developed for ESP8266, it runs on Linux/Unix systems (Raspberry Pi, FreeBSD, NetBSD, Linux, macOS) with X11, framebuffer, or web-only display modes.

**Author:** Elwood Charles Downey (WB0OEW)
**Website:** http://www.clearskyinstitute.com/ham/HamClock

## Build Commands

```bash
make help                     # Show all available targets
make hamclock-800x480         # Build X11 version (standard resolution)
make hamclock-1600x960        # Build X11 version (2x scaling)
make hamclock-web-800x480     # Build web-only version (no local display)
make hamclock-fb0-1600x960    # Build RPi framebuffer version
make clean clobber            # Clean all build artifacts
sudo make install             # Install to /usr/local/bin/hamclock
```

**Optional build flags:**
- `FB_DEPTH=16` - Use 16-bit framebuffer (default 32-bit)
- `WIFI_NEVER=1` - Disable WiFi credential fields in setup

## Architecture

### Core Files
- **`HamClock.h`** - Master header with all type definitions, externs, and ~110 NVRAM config parameters
- **`ESPHamClock.cpp`** - Main application loop (`setup()` and `loop()` functions)
- **`Makefile`** - Build system with platform-specific conditionals

### Display Modes (compile-time flags)
- `_USE_X11` - X11 windowed display
- `_USE_FB0` - Raspberry Pi framebuffer (/dev/fb0)
- `_WEB_ONLY` - HTTP/WebSocket server only, no local display

### Key Components
- **`earthmap.cpp`** - Map rendering with multiple projections (Mercator, Azimuthal, Robinson)
- **`earthsat.cpp`** - Satellite tracking and orbital mechanics (P13/SGP4)
- **`astro.cpp`** - Solar/lunar position calculations (derived from XEphem)
- **`dxcluster.cpp`** - DX Cluster network interface (Spider, AR, CC protocols)
- **`wifi.cpp`** - Network operations, NTP sync, backend data fetching
- **`webserver.cpp`** - RESTful HTTP + WebSocket server
- **`nvram.cpp`** - Persistent configuration storage
- **`setup.cpp`** - Configuration UI

### Libraries (built as part of project)
- **`ArduinoLib/`** - Arduino-to-POSIX compatibility layer
- **`wsServer/`** - WebSocket server (RFC 6455)
- **`zlib-hc/`** - Compression library

### Coordinate System
Uses screen boxes (`SBox`), coordinates (`SCoord`), and circles (`SCircle`) defined in `HamClock.h`. Base resolution is 800x480, scaled by compile-time resolution flags.

## Key Design Patterns

- **Single-threaded main loop** ported from Arduino/ESP8266 with pthread support for background operations
- **Pre-allocated structures** - minimal dynamic memory allocation in main loop
- **Embedded resources** - fonts and images pre-compiled into binary (Germano-*.cpp, moon_imgs.cpp)
- **Backend dependency** - relies on clearskyinstitute.com services for propagation/weather data
- **NVRAM configuration** - ~110 persistent settings via `NVName` enum and `nv_sizes[]` array

## Adding Configuration Options

1. Add enum entry to `NVName` in `HamClock.h`
2. Add size entry to `nv_sizes[]` in `nvram.cpp`
3. Add menu item in `setup.cpp`
4. Use `nvRead*()` / `nvWrite*()` functions

## Platform Detection

Platform-specific code uses these compile-time flags (set by Makefile):
- `_IS_LINUX`, `_IS_LINUX_RPI`, `_IS_LINUX_ARMBIAN`
- `_IS_FREEBSD`, `_IS_NETBSD`
- `_IS_APPLE`

## Backend Output Comparisons (Gold Files)

When HamClock reports endpoint errors, compare the generated backend output against
the gold reference files in `backend/gold/`:

- **Format:** Ensure line layout, field order, delimiters, and fixed-width spacing match the gold file.
- **Line count:** Compare the number of rows served vs. the gold file; use this to decide upstream refresh
  frequency (e.g., if gold has 150 rows, ensure your output keeps the same count).
- **Time spacing:** For time-series data, verify the time delta between consecutive rows (e.g., 1‑minute vs
  10‑minute cadence).
- **Value magnitude:** Confirm units and magnitudes match the gold file (e.g., MHz vs Hz). A 10 in gold
  should not become 10,000,000 in output.
