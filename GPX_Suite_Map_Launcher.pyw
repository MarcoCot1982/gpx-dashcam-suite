#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Dashcam Suite — Map Launcher  v2.1
Retro road-trip map · TCI aesthetic · real OSM/CARTO background
Author : Marco Cot  ·  marcocot1982@gmail.com

Changes v2.1:
- Real map background (CARTO Light tiles, Bordighera area) with vintage filter
- Road Snap detour now branches directly from GPX Ironer
- Winding / twisted roads with more control points
- All labels in English
- Legend moved to bottom-right corner
"""

import os, sys, subprocess, threading, base64, tempfile, math, io
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION    = "v2.1"
AUTHOR     = "Marco Cot"
CONTACT    = "marcocot1982@gmail.com"
SPLASH_SEC = 4   # extra second for tile download

MAP_W  = 1440
MAP_H  = 660
STOP_R = 28

# Map tile settings  — CARTO Light (vintage look, OSM data)
TILE_ZOOM   = 11
CENTER_LAT  = 43.775
CENTER_LON  = 7.55   # Bordighera / Western Liguria
TILE_URL    = "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
TILE_CACHE  = os.path.join(SCRIPT_DIR, "map_bg_cache.png")
TILE_ATTR   = "\u00a9 OpenStreetMap contributors  \u00a9 CARTO"

# ── TCI 1980s palette (overlay elements only) ─────────────────────────────────
M = {
    "paper":   "#f0e8ce",
    "paper2":  "#e6d8b0",
    "contour": "#ccc090",
    "rd_brd":  "#1e120a",
    "rd_main": "#c0391a",
    "rd_sec":  "#c8a012",
    "txt_dk":  "#160c00",
    "txt_md":  "#483010",
    "txt_lt":  "#8a7040",
    "badge_dk":"#1e120a",
    "select":  "#ffe060",
    "shadow":  "#887a6a",
    "card_bg": "#fdf5e0",
}

A = {
    "blue":   "#2196F3",
    "orange": "#fb8c00",
    "amber":  "#f5a623",
    "teal":   "#26a69a",
    "purple": "#9c27b0",
    "green":  "#4caf50",
}

C = {
    "bg":     "#141414",
    "panel":  "#1e1e1e",
    "accent": "#f5a623",
    "text":   "#e8e8e8",
    "muted":  "#888888",
    "dim":    "#555555",
    "border": "#333333",
}

# ── Stop definitions ──────────────────────────────────────────────────────────
# (sid, name, filename, accent, cx, cy, step_badge, description)
STOPS = [
    # ── Starting points: all blue, badges 1a/1b/1c ───────────────────────────
    ("vg",
     "Video \u2192 GPX",
     "video_to_gpx_v36_0_autosave_60s.pyw",
     A["blue"], 100, 130, "1a",
     "OCR-based GPS extractor\nFor dashcam footage WITH on-screen GPS\nOutputs a raw .gpx track file"),

    ("scout",
     "Road Scout",
     "Road_Scout.pyw",
     A["blue"], 100, 370, "1b",
     "Visual odometry GPS estimator\nFor footage WITHOUT on-screen coordinates\nDense optical flow \u00b7 GPS-less track"),

    ("gpxin",
     "GPX File  \u25b6",
     None,
     A["blue"], 100, 578, "1c",
     "Direct GPX input\nAlready have a track file?\nSkip extraction and start here."),

    # ── Main pipeline: orange ─────────────────────────────────────────────────
    ("ir",
     "GPX Ironer",
     "GPX_ironer.pyw",
     A["orange"], 390, 370, "2",
     "Track cleaner & editor\nRemove rogue points \u00b7 bridge gaps\nDrag & reposition \u00b7 undo \u00b7 auto-backup"),

    # ── Optional detours: green ───────────────────────────────────────────────
    ("snap",
     "Road Snap",
     "Road_Snap.pyw",
     A["teal"], 530, 572, "2b",
     "OSRM map-matching \u2014 optional detour\nSnaps track to actual road network\nChunked segments with overlap"),

    # ── Main pipeline cont.: orange ───────────────────────────────────────────
    ("gc",
     "GPX Geocoder",
     "GPX_Geocoder.pyw",
     A["orange"], 760, 370, "3",
     "Reverse geocoder with SQLite cache\nPhoton + BAN (France) + Nominatim\nNaming: road, town, province, country"),

    # ── Optional detour: green ────────────────────────────────────────────────
    ("ce",
     "Cache Editor",
     "Cache_Editor.pyw",
     A["teal"], 800, 118, "3b",
     "Cache manager \u2014 optional loop\nInspect, edit or delete geocode entries\nArea-select on map \u00b7 re-geocode segments"),

    # ── Main pipeline cont.: orange ───────────────────────────────────────────
    ("tv",
     "Towns Video",
     "Towns_video_dx.pyw",
     A["orange"], 995, 370, "4",
     "Location annotation video renderer\nOverlays road / town / country\nOpaque MP4 \u00b7 transparent WebM \u00b7 flag PNGs"),

    ("oc",
     "Overlay Comp.",
     "Overlay_Compositor.pyw",
     A["orange"], 1210, 370, "5",
     "Overlay compositor\nComposites annotation strip onto footage\nClick-drag crop selector \u00b7 ffmpeg backend"),
]

FINAL_POS = (1370, 370)

# ──────────────────────────────────────────────────────────────────────────────
# MAP BACKGROUND  (CARTO Light tiles → vintage filter → PNG cache)
# ──────────────────────────────────────────────────────────────────────────────

def _lat_lon_to_tile(lat, lon, zoom):
    n   = 2 ** zoom
    x   = int((lon + 180.0) / 360.0 * n)
    lr  = math.radians(lat)
    y   = int((1.0 - math.asinh(math.tan(lr)) / math.pi) / 2.0 * n)
    return x, y

def _tile_pixel_offset(lat, lon, zoom, tile_x, tile_y):
    """Pixel offset of (lat, lon) within tile (tile_x, tile_y)."""
    n  = 2 ** zoom
    px = (lon + 180.0) / 360.0 * n * 256 - tile_x * 256
    lr = math.radians(lat)
    py = (1.0 - math.asinh(math.tan(lr)) / math.pi) / 2.0 * n * 256 - tile_y * 256
    return px, py

def _vintage(img):
    """Soft sepia / aged-paper effect for map tiles."""
    try:
        from PIL import ImageEnhance, Image as PILImage
        img = ImageEnhance.Color(img).enhance(0.45)        # desaturate
        img = ImageEnhance.Brightness(img).enhance(0.92)   # slightly darken
        img = ImageEnhance.Contrast(img).enhance(0.90)     # soften contrast
        warm = PILImage.new("RGB", img.size, (245, 232, 200))
        img  = PILImage.blend(img, warm, alpha=0.22)       # warm tint
    except Exception:
        pass
    return img

def fetch_map_background(status_cb=None):
    """
    Download CARTO Light tiles centred on Bordighera, stitch, apply vintage
    filter, save cache.  Returns a PIL Image or None on failure.
    """
    # 1 — return cached version if available
    if os.path.exists(TILE_CACHE):
        try:
            from PIL import Image
            return Image.open(TILE_CACHE).convert("RGB")
        except Exception:
            pass

    # 2 — download tiles
    try:
        import requests
        from PIL import Image

        cx, cy   = _lat_lon_to_tile(CENTER_LAT, CENTER_LON, TILE_ZOOM)
        cols     = math.ceil(MAP_W / 256) + 2   # extra column either side
        rows     = math.ceil(MAP_H / 256) + 2
        sx       = cx - cols // 2
        sy       = cy - rows // 2
        stitched = Image.new("RGB", (cols * 256, rows * 256), (240, 232, 210))

        session  = requests.Session()
        session.headers["User-Agent"] = f"GPXDashcamSuite/{VERSION} ({CONTACT})"
        total    = cols * rows
        done     = 0

        for row in range(rows):
            for col in range(cols):
                tx, ty = sx + col, sy + row
                url    = TILE_URL.format(z=TILE_ZOOM, x=tx, y=ty)
                try:
                    r = session.get(url, timeout=8)
                    if r.status_code == 200:
                        tile = Image.open(io.BytesIO(r.content)).convert("RGB")
                        stitched.paste(tile, (col * 256, row * 256))
                except Exception:
                    pass
                done += 1
                if status_cb:
                    status_cb(done, total)

        # crop to MAP_W × MAP_H centred on CENTER_LAT/LON
        off_x, off_y = _tile_pixel_offset(CENTER_LAT, CENTER_LON,
                                          TILE_ZOOM, sx, sy)
        left = int(off_x) - MAP_W // 2
        top  = int(off_y) - MAP_H // 2
        # clamp
        left = max(0, min(left, stitched.width  - MAP_W))
        top  = max(0, min(top,  stitched.height - MAP_H))
        img  = stitched.crop((left, top, left + MAP_W, top + MAP_H))
        img  = _vintage(img)
        img.save(TILE_CACHE, "PNG")
        return img

    except Exception as e:
        print(f"[Map Launcher] tile download failed: {e}")
        return None

# ──────────────────────────────────────────────────────────────────────────────
# ICO (GPS pin, base64)
# ──────────────────────────────────────────────────────────────────────────────
_ICO_B64 = (
    "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"
)

def _apply_icon(win):
    try:
        data = base64.b64decode(_ICO_B64)
        with tempfile.NamedTemporaryFile(suffix=".ico", delete=False) as tf:
            tf.write(data); path = tf.name
        win.iconbitmap(path)
        win.after(2000, lambda: _try_remove(path))
    except Exception:
        pass

def _try_remove(p):
    try: os.remove(p)
    except: pass

# ──────────────────────────────────────────────────────────────────────────────
# LAUNCH
# ──────────────────────────────────────────────────────────────────────────────
_status_ref = [None]

def launch_app(filename):
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        messagebox.showerror("File not found",
            f"Cannot find:\n{path}\n\nEnsure all suite files are in the same folder.")
        return
    def _run():
        try:
            py = sys.executable or "pythonw"
            if sys.platform.startswith("win") and py.lower().endswith(".exe"):
                pywin = py[:-4] + "w.exe"
                if os.path.exists(pywin): py = pywin
            subprocess.Popen([py, path], cwd=SCRIPT_DIR)
        except Exception as e:
            root.after(0, lambda: messagebox.showerror("Launch error", str(e)))
    if _status_ref[0]:
        _status_ref[0].config(text=f"Launched  \u00b7  {os.path.splitext(filename)[0]}")
    threading.Thread(target=_run, daemon=True).start()

# ──────────────────────────────────────────────────────────────────────────────
# ROAD DRAWING  (TCI-style: dark border + coloured fill)
# ──────────────────────────────────────────────────────────────────────────────
def _road(canvas, pts, bw, fw, bc, fc, dashed=False, tags=()):
    flat = [c for p in pts for c in p]
    dk   = {"dash": (14, 6)} if dashed else {}
    canvas.create_line(flat, fill=bc, width=bw, smooth=True,
                       capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=tags, **dk)
    canvas.create_line(flat, fill=fc, width=fw, smooth=True,
                       capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=tags, **dk)

def road_main(canvas, pts, tags=()):
    _road(canvas, pts, 11, 7, M["rd_brd"], M["rd_main"], tags=tags)

def road_sec(canvas, pts, dashed=False, tags=()):
    _road(canvas, pts, 9, 6, M["rd_brd"], M["rd_sec"], dashed=dashed, tags=tags)

def junction_dot(canvas, x, y, r=8):
    canvas.create_oval(x-r-2, y-r-2, x+r+2, y+r+2, fill=M["rd_brd"], outline="")
    canvas.create_oval(x-r,   y-r,   x+r,   y+r,   fill=M["paper"],  outline="")

def flow_arrow(canvas, x, y, angle_deg, color="#ffffff", size=10):
    a   = math.radians(angle_deg)
    tip = (x + size*math.cos(a),          y + size*math.sin(a))
    lft = (x + size*.5*math.cos(a+2.25),  y + size*.5*math.sin(a+2.25))
    rgt = (x + size*.5*math.cos(a-2.25),  y + size*.5*math.sin(a-2.25))
    canvas.create_polygon(*tip, *lft, *rgt, fill=color, outline="")

# ──────────────────────────────────────────────────────────────────────────────
# CARTOGRAPHIC OVERLAYS  (cartouche, legend, compass, attribution)
# ──────────────────────────────────────────────────────────────────────────────
def _cartouche(canvas):
    """Title box — top-right corner."""
    W = MAP_W
    x0, y0, x1, y1 = W-232, 14, W-14, 86
    # soft drop shadow
    canvas.create_rectangle(x0+4, y0+4, x1+4, y1+4,
                             fill="#9a8a7a", outline="")
    canvas.create_rectangle(x0, y0, x1, y1,
                             fill=M["paper"], outline=M["rd_brd"], width=2)
    canvas.create_rectangle(x0, y0, x1, y0+6,
                             fill=M["rd_main"], outline="")
    mx = (x0+x1)//2
    canvas.create_text(mx, y0+22, text="GPX DASHCAM SUITE",
                       font=("Times", 13, "bold"), fill=M["txt_dk"])
    canvas.create_text(mx, y0+41, text="PIPELINE MAP",
                       font=("Times", 10, "italic"), fill=M["txt_md"])
    canvas.create_text(mx, y0+60, text=f"Marco Cot  \u00b7  2024\u2013{datetime.now().year}",
                       font=("Times", 8), fill=M["txt_lt"])


def _legend(canvas):
    """Legend box — bottom-right corner."""
    H  = MAP_H
    W  = MAP_W
    LW = 196
    LH = 165
    x0 = W - LW - 14
    y0 = H - LH - 24

    canvas.create_rectangle(x0+4, y0+4, x0+LW+4, y0+LH+4,
                             fill="#9a8a7a", outline="")
    canvas.create_rectangle(x0, y0, x0+LW, y0+LH,
                             fill=M["paper"], outline=M["rd_brd"], width=2)
    canvas.create_rectangle(x0, y0, x0+LW, y0+6,
                             fill=M["rd_main"], outline="")
    canvas.create_text(x0+LW//2, y0+20, text="LEGEND",
                       font=("Times", 11, "bold"), fill=M["txt_dk"])

    rows = [
        (M["rd_main"], False, "Main pipeline"),
        (M["rd_sec"],  False, "Optional detour"),
    ]
    for i, (fc, dash, label) in enumerate(rows):
        y = y0 + 42 + i*22
        dk = {"dash": (9, 4)} if dash else {}
        canvas.create_line(x0+10, y, x0+55, y,
                           fill=M["rd_brd"], width=6, capstyle=tk.ROUND, **dk)
        canvas.create_line(x0+10, y, x0+55, y,
                           fill=fc, width=4, capstyle=tk.ROUND, **dk)
        canvas.create_text(x0+62, y, text=label, font=("Times", 8),
                           fill=M["txt_md"], anchor="w")

    # Alternative start: blue circle (matches the 3 start stops)
    y = y0 + 86
    canvas.create_oval(x0+25, y-12, x0+52, y+12,
                       fill=A["blue"], outline=M["rd_brd"], width=2)
    canvas.create_text(x0+62, y, text="Alternative start",
                       font=("Times", 8), fill=M["txt_md"], anchor="w")

    y = y0+112
    canvas.create_oval(x0+28, y-12, x0+52, y+12,
                       fill=A["orange"], outline=M["rd_brd"], width=2)
    canvas.create_text(x0+62, y, text="Suite application",
                       font=("Times", 8), fill=M["txt_md"], anchor="w")

    y = y0+140
    canvas.create_line(x0+38, y+10, x0+38, y-10,
                       fill=M["rd_brd"], width=2)
    canvas.create_polygon(x0+38, y-10, x0+56, y-3, x0+38, y+4,
                           fill=M["rd_main"], outline=M["rd_brd"], width=1)
    canvas.create_text(x0+62, y, text="Final video",
                       font=("Times", 8), fill=M["txt_md"], anchor="w")


def _compass(canvas):
    """Compass rose — upper-left corner."""
    x, y = 58, 62
    size = 34
    canvas.create_oval(x-size-8, y-size-8, x+size+8, y+size+8,
                       fill=M["paper2"] if True else "", outline=M["txt_md"], width=1)
    canvas.create_line(x, y-size, x, y+size, fill=M["txt_dk"], width=1)
    canvas.create_line(x-size, y, x+size, y, fill=M["txt_dk"], width=1)
    for a in [45, 135, 225, 315]:
        ar = math.radians(a)
        dx, dy = size*.6*math.cos(ar), size*.6*math.sin(ar)
        canvas.create_line(x, y, x+dx, y+dy, fill=M["contour"], width=1)
    canvas.create_polygon(x, y-size, x-5, y-size+14, x+5, y-size+14,
                           fill=M["txt_dk"], outline="")
    canvas.create_polygon(x, y+size, x-5, y+size-14, x+5, y+size-14,
                           fill=M["paper"], outline=M["txt_dk"], width=1)
    canvas.create_text(x, y-size-11, text="N",
                       font=("Times", 9, "bold"), fill=M["txt_dk"])


def _attribution(canvas):
    """OSM / CARTO attribution — required by tile providers."""
    canvas.create_text(MAP_W - 16, MAP_H - 6,
                       text=TILE_ATTR,
                       font=("Helvetica", 7), fill=M["txt_lt"],
                       anchor="se")


def _road_numbers(canvas):
    """TCI-style road number ovals on the map."""
    for x, y, label, color in [
        (540,  374, "A8",  M["rd_main"]),
        (875,  374, "A10", M["rd_main"]),
        (1100, 374, "E74", M["rd_main"]),
        (450,  496, "RN7", M["rd_sec"]),
        (766,  246, "SS1", M["rd_sec"]),
    ]:
        canvas.create_oval(x-20, y-11, x+20, y+11,
                           fill=M["paper"], outline=color, width=2)
        canvas.create_text(x, y, text=label,
                           font=("Helvetica", 7, "bold"), fill=color)

# ──────────────────────────────────────────────────────────────────────────────
# ROAD NETWORK  (all roads as winding polylines, road-trip style)
# ──────────────────────────────────────────────────────────────────────────────
def draw_roads(canvas):

    # ── Optional detours drawn first (main roads overlap at junctions) ────────

    # Road Snap detour: from IRONER (390,370) → curves south → Snap (530,572)
    road_sec(canvas, [
        (390, 370), (380, 415), (395, 460), (420, 505), (478, 548), (530, 572)
    ])
    # Road Snap return: (530,572) → curves north-east back to Geocoder (760,370)
    road_sec(canvas, [
        (530, 572), (572, 556), (618, 530), (660, 498), (702, 456),
        (728, 418), (746, 392), (760, 370)
    ])

    # Cache Editor loop: from Geocoder (760,370) winds up to CE (800,118)
    road_sec(canvas, [
        (760, 370), (748, 306), (736, 242), (748, 185), (768, 148), (800, 118)
    ])
    # CE return loop: (800,118) → swings right and back down to Geocoder
    road_sec(canvas, [
        (800, 118), (852, 140), (886, 185), (892, 238),
        (874, 296), (846, 345), (820, 366), (760, 370)
    ])

    # ── Three start branches ──────────────────────────────────────────────────

    # Video→GPX (100,130) → winds down-right to Ironer (390,370)
    road_main(canvas, [
        (100, 130), (145, 165), (188, 208), (228, 252),
        (278, 296), (326, 334), (362, 357), (390, 370)
    ])
    # Road Scout (100,370) → S-curves horizontally to Ironer
    road_main(canvas, [
        (100, 370), (148, 352), (196, 370), (244, 350),
        (292, 368), (340, 355), (390, 370)
    ])
    # GPX File (100,578) → winds up-right to Ironer
    road_main(canvas, [
        (100, 578), (148, 556), (196, 526), (248, 500),
        (298, 470), (340, 428), (370, 400), (390, 370)
    ])

    # ── Main pipeline trunk ────────────────────────────────────────────────────

    # Ironer → Geocoder  (winding, the Road Snap fork shares this segment)
    road_main(canvas, [
        (390, 370), (438, 352), (484, 370), (532, 350),
        (582, 372), (632, 352), (686, 368), (726, 360), (760, 370)
    ])
    # Geocoder → Towns Video
    road_main(canvas, [
        (760, 370), (808, 352), (854, 374), (902, 354),
        (948, 368), (995, 370)
    ])
    # Towns Video → Overlay Compositor
    road_main(canvas, [
        (995, 370), (1042, 354), (1090, 375), (1140, 356),
        (1176, 366), (1210, 370)
    ])
    # Overlay → Final product marker
    road_main(canvas, [
        (1210, 370), (1252, 360), (1298, 370), (1340, 368), (1370, 370)
    ])

    # ── Flow arrows on main trunk ──────────────────────────────────────────────
    for ax, ay, ang in [
        (280, 296, 38),     # VG branch descending
        (196, 500, -38),    # GPX file ascending
        (196, 360, 3),      # Scout horizontal
        (510, 360, 0),      # Ironer→Geocoder
        (656, 360, 1),      # Ironer→Geocoder cont.
        (878, 362, 2),      # Geocoder→TV
        (1092, 372, 2),     # TV→OC
        (1300, 368, 1),     # OC→Final
    ]:
        flow_arrow(canvas, ax, ay, ang, color=M["paper"])

    # Flow arrows on detours
    for ax, ay, ang in [
        (430, 480, 100),    # Snap going south
        (700, 455, -60),    # Snap return
        (748, 246, -82),    # CE going north
        (862, 196, 105),    # CE return
    ]:
        flow_arrow(canvas, ax, ay, ang, color=M["rd_sec"])

    # ── Road number signs ─────────────────────────────────────────────────────
    _road_numbers(canvas)

    # ── Detour labels ──────────────────────────────────────────────────────────
    for x, y, txt in [
        (438, 530, "optional"),
        (812, 255, "optional"),
    ]:
        canvas.create_text(x+1, y+1, text=txt,
                           font=("Times", 8, "italic"), fill=M["paper"])
        canvas.create_text(x,   y,   text=txt,
                           font=("Times", 8, "italic"), fill=M["txt_lt"])

# ──────────────────────────────────────────────────────────────────────────────
# STOP CIRCLES
# ──────────────────────────────────────────────────────────────────────────────
_stop_circles = {}
_selected     = [None]
OVERLAY_TAG   = "info_overlay"
_ov_btns      = []

def draw_stops(canvas, on_click):
    for stop in STOPS:
        sid, name, filename, accent, cx, cy, badge, desc = stop
        tag = f"stop_{sid}"

        # Drop shadow
        canvas.create_oval(cx-STOP_R+3, cy-STOP_R+3,
                            cx+STOP_R+3, cy+STOP_R+3,
                            fill="#7a6a5a", outline="", tags=tag)
        # Dark outer ring
        canvas.create_oval(cx-STOP_R,   cy-STOP_R,
                            cx+STOP_R,   cy+STOP_R,
                            fill=M["rd_brd"], outline="", tags=tag)
        # Coloured face
        cid = canvas.create_oval(cx-STOP_R+3, cy-STOP_R+3,
                                  cx+STOP_R-3, cy+STOP_R-3,
                                  fill=accent, outline="",
                                  tags=(tag, "stop_all"))
        _stop_circles[sid] = (cid, accent)

        # Shine highlight
        canvas.create_oval(cx-STOP_R+7, cy-STOP_R+7,
                            cx-STOP_R+16, cy-STOP_R+16,
                            fill="white", outline="", tags=tag)

        # Step badge (bottom-right sub-circle)
        if badge:
            bx, by = cx + STOP_R - 8, cy + STOP_R - 8
            canvas.create_oval(bx-10, by-10, bx+10, by+10,
                                fill=M["badge_dk"], outline="white", width=1,
                                tags=tag)
            canvas.create_text(bx, by, text=badge,
                                font=("Helvetica", 7, "bold"), fill="white",
                                tags=tag)

        # Name label with white outline for readability on any background
        label_y = cy + STOP_R + 18
        if cy > MAP_H - 90:
            label_y = cy - STOP_R - 18
        for dx, dy in [(-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)]:
            canvas.create_text(cx+dx, label_y+dy, text=name,
                                font=("Times", 10, "bold"),
                                fill="white", tags=tag)
        canvas.create_text(cx, label_y, text=name,
                            font=("Times", 10, "bold"),
                            fill=M["txt_dk"], tags=tag)

        canvas.tag_bind(tag, "<Button-1>", lambda e, s=stop: on_click(s, canvas))
        canvas.tag_bind(tag, "<Enter>",    lambda e, s=stop: _enter(canvas, s))
        canvas.tag_bind(tag, "<Leave>",    lambda e, s=stop: _leave(canvas, s))


def _enter(canvas, stop):
    canvas.config(cursor="hand2")
    cid, _ = _stop_circles.get(stop[0], (None, None))
    if cid: canvas.itemconfig(cid, outline=M["select"], width=4)

def _leave(canvas, stop):
    canvas.config(cursor="")
    cid, _ = _stop_circles.get(stop[0], (None, None))
    if cid: canvas.itemconfig(cid, outline="", width=0)

# ──────────────────────────────────────────────────────────────────────────────
# FINAL PRODUCT MARKER  (flag post)
# ──────────────────────────────────────────────────────────────────────────────
def draw_final(canvas):
    x, y = FINAL_POS
    # pole
    canvas.create_line(x, y+32, x, y-32,
                       fill=M["rd_brd"], width=3, capstyle=tk.ROUND)
    # flag body
    canvas.create_polygon(x, y-32, x+46, y-18, x, y-4,
                           fill=M["rd_main"], outline=M["rd_brd"], width=1)
    # label
    lbl_y = y + 50
    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
        canvas.create_text(x+dx, lbl_y+dy, text="FINAL\nVIDEO",
                           font=("Times", 10, "bold"),
                           fill="white", justify="center")
    canvas.create_text(x, lbl_y, text="FINAL\nVIDEO",
                       font=("Times", 10, "bold"),
                       fill=M["txt_dk"], justify="center")

# ──────────────────────────────────────────────────────────────────────────────
# INFO OVERLAY CARD
# ──────────────────────────────────────────────────────────────────────────────
def show_overlay(canvas, stop):
    global _ov_btns
    hide_overlay(canvas)
    _ov_btns = []

    sid, name, filename, accent, cx, cy, badge, desc = stop
    _selected[0] = sid
    cid, _ = _stop_circles.get(sid, (None, None))
    if cid: canvas.itemconfig(cid, outline=M["select"], width=4)

    OW, OH = 304, 224

    ox = cx + STOP_R + 16
    if ox + OW > MAP_W - 8: ox = cx - STOP_R - 16 - OW
    oy = cy - OH // 2
    if oy < 8:              oy = 8
    if oy + OH > MAP_H - 8: oy = MAP_H - OH - 8

    # shadow
    canvas.create_rectangle(ox+5, oy+5, ox+OW+5, oy+OH+5,
                             fill="#7a6a5a", outline="", tags=OVERLAY_TAG)
    # card
    canvas.create_rectangle(ox, oy, ox+OW, oy+OH,
                             fill=M["paper"], outline=M["rd_brd"], width=2,
                             tags=OVERLAY_TAG)
    # accent top bar
    canvas.create_rectangle(ox, oy, ox+OW, oy+7,
                             fill=accent, outline="", tags=OVERLAY_TAG)
    # dashed inner frame
    canvas.create_rectangle(ox+5, oy+11, ox+OW-5, oy+OH-5,
                             fill="", outline=accent, width=1, dash=(4, 5),
                             tags=OVERLAY_TAG)

    # step badge
    if badge:
        canvas.create_rectangle(ox+10, oy+14, ox+65, oy+31,
                                 fill=accent, outline="", tags=OVERLAY_TAG)
        canvas.create_text(ox+37, oy+22, text=f"STEP  {badge}",
                           font=("Helvetica", 7, "bold"), fill="black",
                           tags=OVERLAY_TAG)

    # app name
    canvas.create_text(ox+OW//2, oy+48, text=name,
                       font=("Times", 14, "bold"), fill=M["txt_dk"],
                       tags=OVERLAY_TAG)

    # separator
    canvas.create_line(ox+16, oy+64, ox+OW-16, oy+64,
                       fill=M["contour"], width=1, tags=OVERLAY_TAG)

    # description
    canvas.create_text(ox+14, oy+73, text=desc,
                       font=("Times", 9), fill=M["txt_md"],
                       anchor="nw", width=OW-28, justify="left",
                       tags=OVERLAY_TAG)

    # file availability + launch button
    if filename:
        fpath  = os.path.join(SCRIPT_DIR, filename)
        avail  = os.path.exists(fpath)
        av_col = "#1a5e20" if avail else "#8b0000"
        av_txt = ("\u2714  " + filename) if avail else ("\u26a0  " + filename + "  — not found")
        canvas.create_text(ox+14, oy+OH-60, text=av_txt,
                           font=("Courier", 7), fill=av_col,
                           anchor="nw", width=OW-28, tags=OVERLAY_TAG)
        btn = tk.Button(canvas,
                        text=("\u25b6  Launch" if avail else "File not found"),
                        font=("Helvetica", 9, "bold"),
                        bg=(accent if avail else "#888888"), fg="black",
                        activebackground=M["rd_main"], activeforeground="white",
                        relief="flat", padx=14, pady=5,
                        cursor=("hand2" if avail else "arrow"),
                        state=("normal" if avail else "disabled"),
                        command=(lambda f=filename: launch_app(f)) if avail else (lambda: None))
        _ov_btns.append(btn)
        canvas.create_window(ox+OW-10, oy+OH-10, anchor="se",
                              window=btn, tags=OVERLAY_TAG)
    else:
        canvas.create_text(ox+OW//2, oy+OH-28,
                           text="Start with any .gpx file — no extraction needed.",
                           font=("Times", 8, "italic"), fill=M["txt_lt"],
                           tags=OVERLAY_TAG)

    # ×  close button
    close_btn = tk.Button(canvas, text="\u00d7",
                           font=("Helvetica", 11, "bold"),
                           bg=M["paper"], fg=M["rd_brd"],
                           activebackground=M["rd_main"], activeforeground="white",
                           relief="flat", padx=4, pady=0, cursor="hand2",
                           command=lambda: hide_overlay(canvas))
    _ov_btns.append(close_btn)
    canvas.create_window(ox+OW-1, oy+1, anchor="ne",
                          window=close_btn, tags=OVERLAY_TAG)


def hide_overlay(canvas):
    global _ov_btns
    canvas.delete(OVERLAY_TAG)
    _ov_btns = []
    sid = _selected[0]
    if sid:
        cid, _ = _stop_circles.get(sid, (None, None))
        if cid: canvas.itemconfig(cid, outline="", width=0)
    _selected[0] = None


def on_stop_click(stop, canvas):
    show_overlay(canvas, stop)

# ──────────────────────────────────────────────────────────────────────────────
# SPLASH  (shows tile download progress)
# ──────────────────────────────────────────────────────────────────────────────
_bg_image_ref  = [None]   # PIL Image
_bg_photo_ref  = [None]   # tk.PhotoImage
_bg_item_ref   = [None]   # canvas item id
_map_ready     = [False]
_tile_progress = [0, 1]   # done, total

def show_splash(root, canvas):
    sp = tk.Toplevel(root); sp.overrideredirect(True); sp.configure(bg=C["bg"])
    sw, sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w, h = 660, 330
    sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x")
    body = tk.Frame(sp, bg=C["bg"]); body.pack(expand=True, fill="both", padx=48)
    tk.Label(body, text="GPX DASHCAM SUITE",
             font=("Consolas", 22, "bold"), bg=C["bg"], fg=C["accent"]).pack(pady=(26, 4))
    tk.Label(body, text=f"{VERSION}  \u00b7  by {AUTHOR}  \u00b7  {datetime.now().year}",
             font=("Consolas", 9), bg=C["bg"], fg=C["muted"]).pack()
    pbv  = tk.DoubleVar()
    pbar = ttk.Progressbar(body, variable=pbv, maximum=100, length=560)
    pbar.pack(pady=(18, 4))
    msg  = tk.Label(body, text="Loading map\u2026",
                    font=("Consolas", 8), bg=C["bg"], fg=C["dim"]); msg.pack()
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")

    # ── fetch tiles in a thread, update progress bar via after() ──────────────
    def _progress_cb(done, total):
        _tile_progress[0], _tile_progress[1] = done, total

    def _fetch():
        img = fetch_map_background(status_cb=_progress_cb)
        _bg_image_ref[0] = img
        _map_ready[0]    = True

    threading.Thread(target=_fetch, daemon=True).start()

    POLL_MS  = 80
    ANIM_MAX = max(1, int(SPLASH_SEC * 1000 / POLL_MS))
    anim     = [0]

    def _poll():
        done, total = _tile_progress
        if _map_ready[0]:
            pct = 100
        elif total > 0:
            pct = max(5, int(done / total * 90))
        else:
            pct = min(40, anim[0])

        pbv.set(pct)
        anim[0] = min(anim[0] + 2, 40)

        if done < total and not _map_ready[0]:
            msg.config(text=f"Downloading map tiles\u2026  ({done}/{total})")
        elif _map_ready[0] and _bg_image_ref[0] is not None:
            msg.config(text="Map loaded.")
        elif _map_ready[0]:
            msg.config(text="Map offline — using paper background.")

        if not _map_ready[0]:
            root.after(POLL_MS, _poll)
        else:
            pbv.set(100)
            root.after(400, _finish)

    def _finish():
        try:   sp.destroy()
        except: pass
        _apply_background(canvas)
        root.deiconify()
        # Open at a comfortable fixed size, centred on screen
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        rw = min(MAP_W + 20,  sw - 60)
        rh = min(MAP_H + 80,  sh - 60)
        x  = (sw - rw) // 2
        y  = (sh - rh) // 2
        root.geometry(f"{rw}x{rh}+{x}+{y}")

    root.withdraw()
    root.after(POLL_MS, _poll)


def _paper_background(canvas):
    """Draw the hand-drawn TCI paper background (fallback when offline)."""
    W, H = MAP_W, MAP_H
    canvas.create_rectangle(0, 0, W, H, fill=M["paper"], outline="")
    for x1, y1, x2, y2, fill in [
        (-80,-80,340,300, "#ddd0a8"), (1120,510,W+80,H+80, "#ddd0a8"),
        (560,-50, 820,180, "#e6d8b0"), (900,-50,1060,130, "#e6d8b0"),
    ]:
        canvas.create_oval(x1, y1, x2, y2, fill=fill, outline="")
    for x1, y1, x2, y2 in [
        (195,40,370,165), (830,55,980,190), (1075,480,1230,595),
        (260,475,385,600), (640,460,730,580),
    ]:
        canvas.create_oval(x1, y1, x2, y2, fill="#bfd498", outline="")
    canvas.create_oval(-90, 440, 85, H+60, fill="#a8c8e0", outline="")
    for yi in range(35, H, 52):
        pts = []
        for xi in range(0, W+30, 22):
            pts.extend([xi, yi + math.sin(xi*.013 + yi*.009)*4.5])
        if len(pts) >= 4:
            canvas.create_line(pts, fill=M["contour"], width=1)
    for xi in range(0, W, 130):
        canvas.create_line(xi, 0, xi, H, fill=M["contour"], width=1, dash=(2,12))
    for yi in range(0, H, 130):
        canvas.create_line(0, yi, W, yi, fill=M["contour"], width=1, dash=(2,12))


def _apply_background(canvas):
    """Place PIL image (or paper fallback) as the bottom canvas layer."""
    img = _bg_image_ref[0]
    if img is not None:
        try:
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(img)
            _bg_photo_ref[0] = photo
            cid = canvas.create_image(0, 0, anchor="nw", image=photo)
            _bg_item_ref[0] = cid
            canvas.lower(cid)
            return
        except Exception as e:
            print(f"[Map Launcher] bg render failed: {e}")
    # fallback
    _paper_background(canvas)

# ──────────────────────────────────────────────────────────────────────────────
# MAIN WINDOW
# ──────────────────────────────────────────────────────────────────────────────
root = tk.Tk()
_apply_icon(root)
root.title(f"GPX Dashcam Suite  {VERSION}  \u2014  Road Map")
root.configure(bg=C["bg"])
root.minsize(1080, 560)
root.resizable(True, True)

sty = ttk.Style(root); sty.theme_use("clam")
sty.configure(".",      background=C["bg"], foreground=C["text"])
sty.configure("TLabel", background=C["bg"], foreground=C["text"],
               font=("Consolas", 9))
sty.configure("TFrame", background=C["bg"])
sty.configure("Horizontal.TProgressbar",
               background=C["accent"], troughcolor=C["panel"],
               bordercolor=C["border"], lightcolor=C["accent"],
               darkcolor="#d49010")
sty.configure("TScrollbar", background=C["panel"], troughcolor=C["bg"],
               arrowcolor=C["muted"])

# ── Top chrome ────────────────────────────────────────────────────────────────
tk.Frame(root, bg=C["accent"], height=3).pack(fill="x")
tb = tk.Frame(root, bg=C["bg"]); tb.pack(fill="x", padx=20, pady=6)
tk.Label(tb, text="GPX DASHCAM SUITE  \u2014  ROAD MAP",
         font=("Consolas", 13, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
tk.Label(tb, text=f"{VERSION}  \u00b7  {AUTHOR}  \u00b7  {datetime.now().year}",
         font=("Consolas", 8), bg=C["bg"], fg=C["dim"]).pack(side="right")
tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

# ── Status bar ────────────────────────────────────────────────────────────────
sb = tk.Frame(root, bg=C["panel"], height=26); sb.pack(fill="x", side="bottom")
tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")
status_lbl = tk.Label(sb, text="Click a stop to see details and launch the app.",
                       font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
status_lbl.pack(side="left", padx=12, pady=3)
_status_ref[0] = status_lbl
tk.Label(sb, text=f"Suite dir:  {SCRIPT_DIR}",
         font=("Consolas", 7), bg=C["panel"], fg=C["dim"]).pack(side="right", padx=12, pady=3)

# ── Canvas (scrollable) ───────────────────────────────────────────────────────
cv_frame = tk.Frame(root, bg=C["bg"]); cv_frame.pack(fill="both", expand=True)
h_sb = ttk.Scrollbar(cv_frame, orient="horizontal")
v_sb = ttk.Scrollbar(cv_frame, orient="vertical")
h_sb.pack(side="bottom", fill="x")
v_sb.pack(side="right",  fill="y")

canvas = tk.Canvas(cv_frame,
                    width=MAP_W, height=MAP_H,
                    bg=M["paper"], highlightthickness=0,
                    scrollregion=(0, 0, MAP_W, MAP_H),
                    xscrollcommand=h_sb.set,
                    yscrollcommand=v_sb.set)
canvas.pack(side="left", fill="both", expand=True)
h_sb.config(command=canvas.xview)
v_sb.config(command=canvas.yview)

def _wy(e): canvas.yview_scroll(int(-1*(e.delta/120)) if e.delta else (-1 if e.num==4 else 1), "units")
def _wx(e): canvas.xview_scroll(int(-1*(e.delta/120)) if e.delta else (-1 if e.num==4 else 1), "units")
root.bind("<MouseWheel>",       _wy, add="+")
root.bind("<Button-4>",         _wy, add="+")
root.bind("<Button-5>",         _wy, add="+")
root.bind("<Shift-MouseWheel>", _wx, add="+")

def _bg_click(event):
    tags = canvas.gettags("current")
    for t in tags:
        if t == OVERLAY_TAG or t.startswith("stop_"): return
    hide_overlay(canvas)
canvas.bind("<Button-1>", _bg_click)

# ── Draw static elements (roads, stops, overlays) ────────────────────────────
# Background will be injected by splash; draw roads/stops now so z-order is set
draw_roads(canvas)
draw_stops(canvas, on_stop_click)
draw_final(canvas)
_cartouche(canvas)
_legend(canvas)
_compass(canvas)
_attribution(canvas)

# ── Refresh map background button ────────────────────────────────────────────
def _refresh_map():
    if os.path.exists(TILE_CACHE):
        try: os.remove(TILE_CACHE)
        except: pass
    status_lbl.config(text="Re-downloading map\u2026 please wait.")
    def _refetch():
        img = fetch_map_background()
        _bg_image_ref[0] = img
        root.after(0, lambda: _apply_background(canvas))
        root.after(0, lambda: status_lbl.config(text="Map refreshed."))
    threading.Thread(target=_refetch, daemon=True).start()

refresh_btn = tk.Button(sb, text="\u21bb  Refresh Map",
                         font=("Consolas", 7), bg=C["panel"], fg=C["muted"],
                         activebackground=C["panel"], activeforeground=C["accent"],
                         relief="flat", cursor="hand2",
                         command=_refresh_map)
refresh_btn.pack(side="right", padx=(0, 4), pady=3)

# ── Launch splash (downloads tiles, then shows window) ───────────────────────
show_splash(root, canvas)
root.protocol("WM_DELETE_WINDOW", root.destroy)

if __name__ == "__main__":
    root.mainloop()
