# 🗺️ GPX Dashcam Suite / GPX editor

A collection of five desktop tools that form a complete pipeline for turning raw dashcam footage into richly annotated, geocoded video overlays.

Built with Python + Tkinter. Dark cinematic UI throughout. Designed for Windows, tested on macOS.

---

## 🔄 Pipeline Overview

```
Dashcam video
     │
     ▼
[0] Landing menu
     │
     ▼
[1] Video → GPX          Extract GPS coordinates from on-screen OSD via OCR
     │
     ▼
[2] GPX Ironer           Fix OCR errors manually with a "human in the loop" map editor
     │
     ▼
[3] GPX Geocoder         Turns coordinates into local addresses (e.g. "43.75185 7.43785" ➜ "Boulevard d'Italie, Monaco"
                         Reverse-geocode each point (road + town) and store in local cache
     │
     ▼
[4] Cache Editor         Review and correct any geocoding errors in the SQLite cache
     │
     ▼
[5] Towns Video          Generate a location-annotation video (road / town / flag overlay)
                         ready to composite over the original dashcam footage
     │
     ▼
[6] Overlay Compositor   Finally places the overlay on the original video. 
                         Position, cropping and timing are adjustable
```

---

## 📦 Tools

### START · Landing menu  `GPX_Suite_Launcher.pyw`

Interactive menu where the user can choose the app to run, or follow the pipeline

<img width="1141" height="1007" alt="MENU" src="https://github.com/user-attachments/assets/d6d1b603-4f56-42de-8333-d401b03780b2" />

---

### 1 · Video → GPX  `video_to_gpx_v36_0_autosave_60s.pyw`

Reads a dashcam video file and extracts GPS coordinates that are burned into the video as on-screen text (OSD). Uses Tesseract OCR with multiple PSM modes and adaptive regex parsing to build a clean GPX track. Auto-saves a provisional file every 60 seconds.

**Key features**
- Configurable Region of Interest (ROI) on the video frame
- Two-pass OCR with fallback PSM modes
- Dynamic file naming with timestamps
- Live map preview of extracted points via StaticMap
- Auto-stop on end-of-file with partial-save
  
<img width="1390" height="934" alt="image" src="https://github.com/user-attachments/assets/2fcfda56-8443-4ef3-9d21-26b2f53652c3" />

---

### 2 · GPX Ironer  `GPX_ironer.pyw`

A "human-in-the-loop" GPX editor for fixing OCR artefacts and GPS noise. Displays the full track on an interactive map and lets you identify, inspect and delete *rogue points* — coordinates that are geographically impossible given the surrounding track.

**Key features**
- Interactive `tkintermapview` map with multi-segment colour coding
- Rogue point detection (configurable distance/speed thresholds)
- Click-to-select and bulk delete of bad points
- Drag and drop live track edition
- Full undo history
- Time gap manual edition (in case a gps signal loss is not reflected in time)
- Auto-save to a `_temp` file every 10 minutes
- Auto-save a backup of the original file in case rollback is needed
- Export cleaned GPX

<img width="1759" height="934" alt="image" src="https://github.com/user-attachments/assets/67130587-82bc-4901-928c-2659fa4d3559" />

---

### 3 · GPX Geocoder  `GPX_Geocoder.pyw`

Takes a clean GPX file and enriches each track point with a human-readable location tag (road name + town), stored as the GPX `<cmt>` field. Uses a three-source strategy with local SQLite caching to minimise API calls.

**Geocoding sources (priority order)**
| Priority | Source | Coverage |
|----------|--------|----------|
| 1 | Local SQLite cache | All countries |
| 2 | Photon (Komoot) | Global, France primary |
| 3 | BAN (French address API) | France only |
| 4 | Nominatim (OSM) | Global fallback |

**Key features**
- 4-decimal-degree cache key (≈ 11 m grid) — shared with Cache Editor
- Country-specific road normalisation (French RN/D routes, Italian SP/SS, etc.)
- France-specific logic: postcode-based province (départements) derivation
- Monaco, Andorra and San Marino boundary aware
- Pause / Stop & Save / Resume controls
- Live map with last 200 geocoded points
- `--input <file>` CLI flag for launching from Cache Editor

<img width="1757" height="934" alt="image" src="https://github.com/user-attachments/assets/bace24e4-ef82-4957-a4ca-4cdf9c4fa289" />

---

### 4 · Cache Editor  `Cache_Editor.pyw`

A full GUI editor for the SQLite geocode cache produced by GPX Geocoder. Lets you manually correct wrong place names, fix border ambiguities, or define custom zones (e.g. labelling an entire airport perimeter as *"Airport"*).

**Key features**
- WAL-mode SQLite with separate read/write connections (no locking)
- Interactive map with configurable marker density
- Rectangle area selection (4-click) for bulk editing
- Visual (color coded) highlight of the selected part of track
- Manual start/end index range selection
- One-click re-geocode: deletes the stale `_geocoded.gpx` and relaunches GPX Geocoder
- Fullscreen by default

<img width="1763" height="934" alt="image" src="https://github.com/user-attachments/assets/fb757ee5-1622-48c1-99d1-7bea42d48f3e" />

---

### 5 · Towns Video  `Towns_video_dx.pyw`

Reads a geocoded GPX file and renders a black MP4 video that displays the road name, town name and optional country flag for every track point. The resulting video is intended to be composited (e.g. in DaVinci Resolve or FFmpeg) over the original dashcam footage as a location overlay track.

**Key features**
- Configurable resolution: 480p / 720p / 1080p
- Frame rates: 24 / 30 / 60 fps
- Country flag images from a local `flags/` folder (PNG, named by ISO 3166-1 alpha-2 code) to workaround Windows limitation
- Font size, colour and background customisable from UI
- Transparent background option available
- Capability to create both opaque and transparent background outputs at once
- Live map showing full track + current-point marker during render
- Render progress bar with ETA

<img width="1755" height="934" alt="image" src="https://github.com/user-attachments/assets/c6b1f942-9b38-4622-a75f-be661a80c570" />
---

### 6 · Overlay Compositor  `overlay_compositor.pyw`

Places the final overlay result over the original video

**Key features**
- Configurable size and cropping
- Configurable positioning
- Time offset editable

<img width="1900" height="1020" alt="overlayer" src="https://github.com/user-attachments/assets/4b0a1a5e-386e-441d-86f3-d5bee8e0bd9e" />
---

## 🛠️ Installation

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.9+ | [python.org](https://www.python.org) |
| Tesseract OCR | Required by **Video → GPX** only — [install guide](https://github.com/UB-Mannheim/tesseract/wiki) |
| FFmpeg | Required by **Towns Video** (used by MoviePy internally) — [ffmpeg.org](https://ffmpeg.org/download.html) |

### Python dependencies

```bash
pip install -r requirements.txt
```

### Running any tool

All five scripts are `.pyw` files (windowless Python). You can launch them by:

```bash
# Double-click in Explorer/Finder, or from terminal:
python video_to_gpx_v36_0_autosave_60s.pyw
python GPX_ironer.pyw
python GPX_Geocoder.pyw
python Cache_Editor.pyw
python Towns_video_dx.pyw
```

---

## 📁 Repository Structure

```
gpx-dashcam-suite/
├── GPX_Suite_Launcher.pyw                  # Step 0 – Menu - launcher
├── video_to_gpx_v36_0_autosave_60s.pyw     # Step 1 – OCR GPS extractor
├── GPX_ironer.pyw                          # Step 2 – GPX manual cleaner
├── GPX_Geocoder.pyw                        # Step 3 – Reverse geocoder
├── Cache_Editor.pyw                        # Step 4 – Cache database editor
├── Towns_video_dx.pyw                      # Step 5 – Location video generator
├── flags/                                  # Country flag PNGs (ISO 3166-1 alpha-2)
│   └── *.png
├── requirements.txt
├── .gitignore
└── README.md
```

> **Note:** The `geocode_cache.db` SQLite file is created at runtime next to `GPX_Geocoder.pyw` and is excluded from version control via `.gitignore`.

---

## 🏁 Flags Folder

`Towns_video_dx.pyw` looks for flag images in a `flags/` subfolder, named by ISO 3166-1 alpha-2 code (e.g. `FR.png`, `IT.png`, `ES.png`). If a flag PNG is not found, the tool falls back to a Unicode emoji flag. A free set of flag PNGs is available from [flagpedia.net](https://flagpedia.net/download) or [github.com/lipis/flag-icons](https://github.com/lipis/flag-icons).

---

## 📡 Geocoding APIs used

All API usage is read-only and subject to the respective terms of service. The local SQLite cache is designed to minimise repeat requests.

| API | URL | Rate limit respected |
|-----|-----|---------------------|
| Photon (Komoot) | https://photon.komoot.io | 1.3 s minimum delay |
| BAN (France) | https://api-adresse.data.gouv.fr | Public, no key required |
| Nominatim (OSM) | https://nominatim.openstreetmap.org | 1 s minimum delay |

---

## 👤 Author

**Marco Cot** · marcocot1982@gmail.com

---

## 📄 License

MIT License — see [LICENSE](LICENSE)
