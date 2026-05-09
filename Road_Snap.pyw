#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Road Snap  v1.0
Author : Marco Cot
Contact: marcocot1982@gmail.com

Snaps any GPX track to the road network using OSRM map-matching.
Works with Road Scout output, Video→GPX output, or any GPX file.

Two-pass workflow:
  Pass 1 — loads GPX and displays the raw track on the map
  Pass 2 — sends chunks to OSRM /match, collects snapped geometry
            + confidence score per chunk
  Review — side-by-side raw (dim red) vs snapped (amber) on the map;
           chunk list with colour-coded confidence bars;
           accept / reject per chunk; export merged GPX

OSRM local server (recommended for long tracks):
  docker pull osrm/osrm-backend
  # download a region extract from download.geofabrik.de, e.g. spain-latest.osm.pbf
  docker run -t -v $(pwd):/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/spain-latest.osm.pbf
  docker run -t -v $(pwd):/data osrm/osrm-backend osrm-partition /data/spain-latest.osrm
  docker run -t -v $(pwd):/data osrm/osrm-backend osrm-customize /data/spain-latest.osrm
  docker run -d -p 5000:5000 -v $(pwd):/data osrm/osrm-backend osrm-routed --algorithm mld /data/spain-latest.osrm
  → use  http://localhost:5000  as the server URL

Public server fallback: http://router.project-osrm.org  (rate-limited, 100 coords max)
"""

import os, sys, math, time, threading, queue, json
from datetime import datetime, timezone
from pathlib import Path

import requests
import gpxpy, gpxpy.gpx
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageTk
import tkintermapview

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
VERSION        = "v1.0"
AUTHOR         = "Marco Cot"
CONTACT        = "marcocot1982@gmail.com"
SPLASH_SECONDS = 3

CHUNK_SIZE     = 80    # points per OSRM request
CHUNK_OVERLAP  = 10   # points shared between adjacent chunks (seam healing)
DEFAULT_RADIUS = 25   # metres snap radius per point
MAX_RADIUS     = 75   # metres — used for low-confidence stretches

CONF_HIGH   = 0.75    # confidence ≥ this → green
CONF_MEDIUM = 0.45    # confidence ≥ this → orange; below → red

OSRM_LOCAL  = "http://localhost:5000"
OSRM_PUBLIC = "http://router.project-osrm.org"

DRAG_THRESHOLD = 6    # px — press+release below this = click

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE
# ─────────────────────────────────────────────────────────────────────────────
C = {
    "bg":     "#141414",
    "panel":  "#1e1e1e",
    "panel2": "#252525",
    "border": "#333333",
    "accent": "#f5a623",
    "accent2":"#e8941a",
    "green":  "#4caf50",
    "red":    "#e53935",
    "orange": "#fb8c00",
    "blue":   "#2196F3",
    "text":   "#e8e8e8",
    "muted":  "#888888",
    "dim":    "#555555",
    "teal":   "#26a69a",
}

# ─────────────────────────────────────────────────────────────────────────────
# WINDOW ICON
# ─────────────────────────────────────────────────────────────────────────────
def _make_icon(size: int = 64) -> ImageTk.PhotoImage:
    S   = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    amber  = (245, 166, 35, 255)
    dark   = (20,  20,  20, 255)
    road_c = (80,  80,  80, 220)
    cr    = int(S * 0.37)
    cx    = S // 2
    cy_p  = int(S * 0.38)
    d.ellipse([cx-cr, cy_p-cr, cx+cr, cy_p+cr], fill=amber)
    tip = int(S * 0.93)
    d.polygon([(cx - int(cr*.55), cy_p + int(cr*.55)),
               (cx + int(cr*.55), cy_p + int(cr*.55)),
               (cx, tip)], fill=amber)
    ir = int(cr * 0.50)
    d.ellipse([cx-ir, cy_p-ir, cx+ir, cy_p+ir], fill=dark)
    # Road stripe inside inner circle
    rw = max(2, int(ir * 0.55))
    rh = max(1, int(ir * 0.14))
    gy = cy_p - int(ir * 0.48)
    for _ in range(3):
        d.rectangle([cx - rw//2, gy, cx + rw//2, gy + rh], fill=road_c)
        gy += rh * 3
    return ImageTk.PhotoImage(img)


def _apply_icon(win):
    try:
        img = _make_icon(64)
        win._icon_ref = img
        win.iconphoto(True, img)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def mk_btn(parent, text, bg, cmd, width=None, state="normal",
           font=("Consolas", 9, "bold")):
    kw = dict(text=text, bg=bg,
              fg="white" if bg not in (C["dim"], C["panel2"]) else C["muted"],
              activebackground=bg, activeforeground="white",
              disabledforeground=C["dim"],
              relief="flat", cursor="hand2", command=cmd,
              font=font, pady=5, padx=8, state=state)
    if width:
        kw["width"] = width
    return tk.Button(parent, **kw)


def sec_hdr(parent, text):
    f = tk.Frame(parent, bg=C["panel"])
    f.pack(fill="x", padx=10, pady=(12, 3))
    tk.Label(f, text=text, font=("Consolas", 8, "bold"),
             bg=C["panel"], fg=C["accent"]).pack(side="left")
    tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=10)


def dim_lbl(parent, text, bg=None):
    tk.Label(parent, text=text, font=("Consolas", 7), bg=bg or C["panel"],
             fg=C["dim"], justify="left", wraplength=245
             ).pack(padx=10, anchor="w", pady=(2, 0))


def conf_color(c: float) -> str:
    if c >= CONF_HIGH:   return C["green"]
    if c >= CONF_MEDIUM: return C["orange"]
    return C["red"]


# ─────────────────────────────────────────────────────────────────────────────
# GEO HELPERS
# ─────────────────────────────────────────────────────────────────────────────
_R = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon/2)**2)
    return _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def track_total_km(points) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += haversine_m(*points[i-1][:2], *points[i][:2])
    return total / 1000.0


def canvas_to_latlon(map_widget, cx, cy):
    try:
        return map_widget.convert_canvas_coords_to_decimal_coords(cx, cy)
    except Exception:
        pass
    try:
        import math as _m
        zoom   = map_widget.zoom
        ul     = map_widget.upper_left_tile_pos
        tile_x = ul[0] + cx / 256.0
        tile_y = ul[1] + cy / 256.0
        n      = 2 ** zoom
        lon    = tile_x / n * 360.0 - 180.0
        lat_r  = _m.atan(_m.sinh(_m.pi * (1 - 2 * tile_y / n)))
        return _m.degrees(lat_r), lon
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# GPX I/O
# ─────────────────────────────────────────────────────────────────────────────
def load_gpx(path: str) -> list:
    """Return list of (lat, lon, time_or_None)."""
    with open(path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
    pts = []
    for trk in gpx.tracks:
        for seg in trk.segments:
            for p in seg.points:
                pts.append((p.latitude, p.longitude,
                             p.time if p.time else None))
    return pts


def save_gpx(points, out_path: str, description: str = ""):
    gpx = gpxpy.gpx.GPX()
    gpx.description = description
    trk = gpxpy.gpx.GPXTrack(); gpx.tracks.append(trk)
    seg = gpxpy.gpx.GPXTrackSegment(); trk.segments.append(seg)
    for lat, lon, t in points:
        seg.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, time=t))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(gpx.to_xml())


# ─────────────────────────────────────────────────────────────────────────────
# CHUNKING
# ─────────────────────────────────────────────────────────────────────────────
def make_chunks(points: list) -> list:
    """
    Split points into overlapping chunks of CHUNK_SIZE with CHUNK_OVERLAP.
    Returns list of dicts:
        { "idx": int, "pts": [(lat,lon,t),...],
          "raw_start": int, "raw_end": int }   ← indices into original list
    """
    chunks = []
    n      = len(points)
    step   = CHUNK_SIZE - CHUNK_OVERLAP
    i      = 0
    cidx   = 0
    while i < n:
        end  = min(i + CHUNK_SIZE, n)
        chunks.append({
            "idx":       cidx,
            "pts":       points[i:end],
            "raw_start": i,
            "raw_end":   end - 1,
        })
        cidx += 1
        if end == n:
            break
        i += step
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# OSRM MAP-MATCH
# ─────────────────────────────────────────────────────────────────────────────
def osrm_match_chunk(chunk: dict, server: str,
                     radius: int = DEFAULT_RADIUS,
                     timeout: int = 30) -> dict:
    """
    Call OSRM /match for one chunk.
    Returns:
        { "ok": bool, "confidence": float,
          "snapped": [(lat,lon,t),...],   ← matched coords, same count as input
          "error": str }
    """
    pts = chunk["pts"]
    coords_str = ";".join(f"{lon:.7f},{lat:.7f}" for lat, lon, _ in pts)
    radii_str  = ";".join([str(radius)] * len(pts))

    params = {
        "geometries":  "geojson",
        "overview":    "full",
        "annotations": "true",
        "radiuses":    radii_str,
    }

    # Include timestamps if available (improves matching significantly)
    times = [t for _, _, t in pts]
    if all(t is not None for t in times):
        base_ts = int(times[0].timestamp())
        ts_list = [int(t.timestamp()) - base_ts for t in times]
        # OSRM needs strictly increasing timestamps
        fixed = [ts_list[0]]
        for i in range(1, len(ts_list)):
            fixed.append(max(fixed[-1] + 1, ts_list[i]))
        params["timestamps"] = ";".join(str(x) for x in fixed)

    url = f"{server.rstrip('/')}/match/v1/driving/{coords_str}"

    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ConnectionError:
        return {"ok": False, "confidence": 0.0, "snapped": [],
                "error": "Cannot connect to OSRM server. Is it running?"}
    except Exception as e:
        return {"ok": False, "confidence": 0.0, "snapped": [],
                "error": str(e)}

    code = data.get("code", "")
    if code != "Ok":
        msg = data.get("message", code)
        return {"ok": False, "confidence": 0.0, "snapped": [],
                "error": f"OSRM error: {msg}"}

    matchings = data.get("matchings", [])
    if not matchings:
        return {"ok": False, "confidence": 0.0, "snapped": [],
                "error": "No matchings returned"}

    # Overall confidence = mean across all matching segments
    conf = float(np.mean([m.get("confidence", 0.0) for m in matchings])) \
        if len(matchings) > 0 else 0.0

    # Extract snapped points from tracepoints
    # tracepoints has one entry per input point; None if point was unmatched
    tracepoints = data.get("tracepoints", [])
    snapped = []
    for i, tp in enumerate(tracepoints[:len(pts)]):
        orig_t = pts[i][2]
        if tp is None:
            # Unmatched — keep original coords
            snapped.append((pts[i][0], pts[i][1], orig_t))
        else:
            loc = tp.get("location", [])
            if len(loc) >= 2:
                snapped.append((loc[1], loc[0], orig_t))   # [lon,lat] → (lat,lon)
            else:
                snapped.append((pts[i][0], pts[i][1], orig_t))

    return {"ok": True, "confidence": conf, "snapped": snapped, "error": ""}


def stitch_chunks(chunks: list, results: list, raw_points: list) -> list:
    """
    Merge chunk results back into a single point list.
    For overlapping zones: use the snapped version of the later chunk
    (it had more context from the previous one).
    Where a chunk was rejected, use raw points instead.
    """
    n      = len(raw_points)
    output = [None] * n

    for chunk, result in zip(chunks, results):
        rs  = chunk["raw_start"]
        re  = chunk["raw_end"]
        pts = result["snapped"] if (result["ok"] and result["accepted"]) \
              else chunk["pts"]
        # Write this chunk's points; later chunks overwrite the overlap zone
        for j, pt in enumerate(pts):
            idx = rs + j
            if idx <= re and idx < n:
                output[idx] = pt

    # Fill any remaining Nones with raw (shouldn't happen but safety net)
    for i in range(n):
        if output[i] is None:
            output[i] = raw_points[i]

    return output


# lazy import numpy (only used inside osrm_match_chunk)
try:
    import numpy as np
except ImportError:
    class _np:
        @staticmethod
        def mean(lst): return sum(lst) / len(lst) if lst else 0.0
    np = _np()


# ─────────────────────────────────────────────────────────────────────────────
# MATCH WORKER  (runs in a thread)
# ─────────────────────────────────────────────────────────────────────────────
def match_worker(chunks, server, radius, ui_queue, stop_event):
    """Process all chunks sequentially, posting progress to ui_queue."""
    results = []
    total   = len(chunks)
    for i, chunk in enumerate(chunks):
        if stop_event.is_set():
            ui_queue.put(("match_aborted",))
            return

        ui_queue.put(("match_progress", i, total,
                      f"Matching chunk {i+1}/{total}…"))

        res = osrm_match_chunk(chunk, server, radius)
        res["accepted"] = res["ok"]   # default: accept if matched OK
        results.append(res)

        conf = res["confidence"]
        status = "✅" if res["ok"] else "❌"
        ui_queue.put(("chunk_result", i, res["ok"], conf,
                      res.get("error", ""),
                      chunk["raw_start"], chunk["raw_end"]))

    ui_queue.put(("match_done", results))


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APPLICATION
# ─────────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title(f"Road Snap  {VERSION}")
root.configure(bg=C["bg"])
_apply_icon(root)
try:    root.state("zoomed")
except: root.geometry("1440x860")
root.resizable(True, True)

sty = ttk.Style(root); sty.theme_use("clam")
sty.configure(".",          background=C["bg"],    foreground=C["text"])
sty.configure("TLabel",     background=C["bg"],    foreground=C["text"],
                             font=("Consolas", 9))
sty.configure("TFrame",     background=C["bg"])
sty.configure("TScrollbar", background=C["panel2"],
                             troughcolor=C["border"], arrowcolor=C["muted"])
sty.configure("Horizontal.TProgressbar",
               background=C["accent"], troughcolor=C["panel2"],
               bordercolor=C["border"],
               lightcolor=C["accent"], darkcolor=C["accent2"])
sty.configure("Treeview",
               background=C["panel2"], foreground=C["text"],
               fieldbackground=C["panel2"], font=("Consolas", 8),
               rowheight=22, borderwidth=0)
sty.configure("Treeview.Heading",
               background=C["panel"], foreground=C["accent"],
               font=("Consolas", 8, "bold"), relief="flat")
sty.map("Treeview",
        background=[("selected", C["accent"])],
        foreground=[("selected", "black")])

# ── application state ─────────────────────────────────────────────────────────
app_state = {
    "gpx_path":    None,
    "raw_points":  [],       # [(lat, lon, t), ...]
    "chunks":      [],
    "results":     [],       # one per chunk, after matching
    "phase":       "idle",   # idle | loaded | matching | review | done
}

ui_q          = queue.Queue()
stop_ev       = threading.Event()
map_objects   = []          # all path/marker objects on the map
_current_zoom = [12]
_press_xy     = [0, 0]

# ── tk variables ──────────────────────────────────────────────────────────────
server_var    = tk.StringVar(value=OSRM_LOCAL)
radius_var    = tk.StringVar(value=str(DEFAULT_RADIUS))
auto_accept_var = tk.DoubleVar(value=CONF_HIGH)
show_raw_var  = tk.BooleanVar(value=True)
show_snap_var = tk.BooleanVar(value=True)

# ─────────────────────────────────────────────────────────────────────────────
# SPLASH
# ─────────────────────────────────────────────────────────────────────────────
def show_splash():
    sp = tk.Toplevel(root); sp.overrideredirect(True)
    sp.configure(bg=C["bg"])
    sw, sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w, h   = 640, 310
    sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x")
    body = tk.Frame(sp, bg=C["bg"]); body.pack(expand=True, fill="both", padx=40)
    tk.Label(body, text="ROAD SNAP",
             font=("Consolas", 26, "bold"),
             bg=C["bg"], fg=C["accent"]).pack(pady=(22, 3))
    tk.Label(body, text="OSRM Map-Matching for GPX Tracks",
             font=("Consolas", 10), bg=C["bg"], fg=C["text"]).pack()
    tk.Label(body, text=f"{VERSION}  ·  by {AUTHOR}  ·  {datetime.now().year}",
             font=("Consolas", 8), bg=C["bg"], fg=C["muted"]).pack()
    tk.Label(body, text="snap any GPX track to the road network — review & export",
             font=("Consolas", 8, "italic"), bg=C["bg"], fg=C["dim"]
             ).pack(pady=(4, 16))
    pbv = tk.DoubleVar()
    pb  = ttk.Progressbar(body, variable=pbv, maximum=100, length=560); pb.pack()
    pct = tk.Label(body, text="0%", font=("Consolas", 8),
                   bg=C["bg"], fg=C["dim"]); pct.pack(pady=4)
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")
    steps = max(15, SPLASH_SECONDS * 25)
    ivl   = max(1, int(SPLASH_SECONDS * 1000 / steps))
    def _step(i=0):
        if not sp.winfo_exists(): return
        pbv.set(i / steps * 100); pct.config(text=f"{int(i / steps * 100)}%")
        if i < steps:
            root.after(ivl, _step, i + 1)
        else:
            sp.destroy(); root.deiconify()
            try: root.state("zoomed")
            except: pass
    root.withdraw(); root.after(ivl, _step)


show_splash()


# ─────────────────────────────────────────────────────────────────────────────
# TOP CHROME
# ─────────────────────────────────────────────────────────────────────────────
tk.Frame(root, bg=C["accent"], height=3).pack(fill="x")
tb = tk.Frame(root, bg=C["bg"]); tb.pack(fill="x", padx=16, pady=5)
tk.Label(tb, text="ROAD SNAP",
         font=("Consolas", 13, "bold"),
         bg=C["bg"], fg=C["accent"]).pack(side="left")
tk.Label(tb, text="OSRM map-matching for GPX tracks",
         font=("Consolas", 9), bg=C["bg"], fg=C["muted"]
         ).pack(side="left", padx=(14, 0))
tk.Label(tb, text=f"{VERSION}  ·  {AUTHOR}  ·  2025–{datetime.now().year}",
         font=("Consolas", 8), bg=C["bg"], fg=C["dim"]).pack(side="right")
tk.Frame(root, bg=C["border"], height=1).pack(fill="x")


# ─────────────────────────────────────────────────────────────────────────────
# BODY
# ─────────────────────────────────────────────────────────────────────────────
body_frame = tk.Frame(root, bg=C["bg"])
body_frame.pack(fill="both", expand=True)


# ═══════════════════════════════════════════════════════════════════════════════
# LEFT SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
left = tk.Frame(body_frame, bg=C["panel"], width=275)
left.pack(side="left", fill="y", padx=(10, 0), pady=10)
left.pack_propagate(False)

# ── GPX FILE ──────────────────────────────────────────────────────────────────
sec_hdr(left, "GPX FILE")
ff = tk.Frame(left, bg=C["panel"]); ff.pack(fill="x", padx=10, pady=6)

gpx_lbl = tk.Label(left, text="No file loaded",
                    font=("Consolas", 7, "italic"),
                    bg=C["panel"], fg=C["muted"],
                    wraplength=255, anchor="w")

def load_gpx_file():
    p = filedialog.askopenfilename(
        title="Select GPX file",
        filetypes=[("GPX files", "*.gpx")])
    if not p:
        return
    try:
        pts = load_gpx(p)
    except Exception as e:
        messagebox.showerror("Load error", f"Failed to parse GPX:\n{e}")
        return
    if len(pts) < 2:
        messagebox.showwarning("Empty track", "No trackpoints found.")
        return

    app_state["gpx_path"]   = p
    app_state["raw_points"] = pts
    app_state["chunks"]     = make_chunks(pts)
    app_state["results"]    = []
    app_state["phase"]      = "loaded"

    n_chunks = len(app_state["chunks"])
    km       = track_total_km([(la, lo) for la, lo, _ in pts])
    gpx_lbl.config(text=Path(p).name)
    info_lbl.config(
        text=f"{len(pts):,} points  ·  {km:.2f} km  ·  {n_chunks} chunks")
    set_status(f"Loaded: {Path(p).name}  —  {len(pts):,} pts  "
               f"{km:.2f} km  {n_chunks} chunks")

    # Enable match button, reset review
    match_btn.config(state="normal", bg=C["green"])
    export_btn.config(state="disabled", bg=C["dim"], fg=C["muted"])
    chunk_tree.delete(*chunk_tree.get_children())
    progress_var.set(0)

    draw_raw_track()
    _set_phase_ui("loaded")

mk_btn(ff, "📂  Open GPX", C["blue"], load_gpx_file).pack(fill="x", pady=2)
gpx_lbl.pack(padx=10, anchor="w")

info_lbl = tk.Label(left, text="", font=("Consolas", 7),
                     bg=C["panel"], fg=C["muted"])
info_lbl.pack(padx=10, anchor="w", pady=(2, 0))

# ── OSRM SERVER ────────────────────────────────────────────────────────────────
sec_hdr(left, "OSRM SERVER")
sf = tk.Frame(left, bg=C["panel"]); sf.pack(fill="x", padx=10, pady=4)

# Quick-select buttons
sb2 = tk.Frame(sf, bg=C["panel"]); sb2.pack(fill="x", pady=(0, 4))
mk_btn(sb2, "Local :5000", C["dim"],
        lambda: server_var.set(OSRM_LOCAL),
        font=("Consolas", 8)).pack(side="left", padx=(0, 4))
mk_btn(sb2, "Public", C["dim"],
        lambda: server_var.set(OSRM_PUBLIC),
        font=("Consolas", 8)).pack(side="left")

r = tk.Frame(sf, bg=C["panel"]); r.pack(fill="x")
tk.Label(r, text="URL:", font=("Consolas", 8), bg=C["panel"],
          fg=C["muted"], width=5, anchor="w").pack(side="left")
tk.Entry(r, textvariable=server_var, width=22,
          bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
          relief="flat", highlightthickness=1,
          highlightcolor=C["accent"], highlightbackground=C["border"],
          font=("Consolas", 8)).pack(side="left", padx=(4, 0))

def test_server():
    url = server_var.get().rstrip("/")
    set_status(f"Testing {url}…")
    root.update_idletasks()
    try:
        r2 = requests.get(url + "/route/v1/driving/0,0;0,0",
                         timeout=5)
        # OSRM returns 200 even for dummy coords; just check it responds
        set_status(f"✅  Server OK — {url}")
        messagebox.showinfo("Server test",
                             f"OSRM server is reachable:\n{url}")
    except Exception as e:
        set_status(f"❌  Server unreachable: {e}")
        messagebox.showerror("Server test",
                              f"Cannot reach server:\n{url}\n\n{e}")

mk_btn(sf, "Test Connection", C["dim"], test_server,
        font=("Consolas", 8)).pack(fill="x", pady=(6, 0))

dim_lbl(left,
        "Local OSRM needs Docker.\n"
        "See file header for setup commands.")

# ── MATCHING OPTIONS ───────────────────────────────────────────────────────────
sec_hdr(left, "MATCHING OPTIONS")
mof = tk.Frame(left, bg=C["panel"]); mof.pack(fill="x", padx=10, pady=4)

r2 = tk.Frame(mof, bg=C["panel"]); r2.pack(fill="x", pady=2)
tk.Label(r2, text="Snap radius (m):", font=("Consolas", 8), bg=C["panel"],
          fg=C["muted"], width=16, anchor="w").pack(side="left")
tk.Entry(r2, textvariable=radius_var, width=6,
          bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
          relief="flat", highlightthickness=1,
          highlightcolor=C["accent"], highlightbackground=C["border"],
          font=("Consolas", 9)).pack(side="left", padx=(4, 0))

r3 = tk.Frame(mof, bg=C["panel"]); r3.pack(fill="x", pady=2)
tk.Label(r3, text="Auto-accept conf≥:", font=("Consolas", 8), bg=C["panel"],
          fg=C["muted"], width=16, anchor="w").pack(side="left")
tk.Entry(r3, textvariable=auto_accept_var, width=6,
          bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
          relief="flat", highlightthickness=1,
          highlightcolor=C["accent"], highlightbackground=C["border"],
          font=("Consolas", 9)).pack(side="left", padx=(4, 0))

dim_lbl(left, f"Chunk size: {CHUNK_SIZE} pts  ·  Overlap: {CHUNK_OVERLAP} pts")

# ── RUN MATCHING ───────────────────────────────────────────────────────────────
sec_hdr(left, "RUN")
rf = tk.Frame(left, bg=C["panel"]); rf.pack(fill="x", padx=10, pady=6)

match_btn = mk_btn(rf, "🛣  Match to Roads", C["green"],
                    lambda: start_matching(), state="disabled")
match_btn.pack(fill="x", pady=2)

stop_btn = mk_btn(rf, "⏹  Stop", C["red"],
                   lambda: stop_matching(), state="disabled")
stop_btn.pack(fill="x", pady=2)

# ── MAP DISPLAY ────────────────────────────────────────────────────────────────
sec_hdr(left, "MAP DISPLAY")
df = tk.Frame(left, bg=C["panel"]); df.pack(fill="x", padx=10, pady=4)

_ckw = dict(bg=C["panel"], fg=C["text"],
            activebackground=C["panel"], activeforeground=C["accent"],
            selectcolor=C["accent2"], font=("Consolas", 8),
            anchor="w", relief="flat")
tk.Checkbutton(df, text="Show raw track  (dim red)",
               variable=show_raw_var,
               command=lambda: redraw_map(), **_ckw).pack(fill="x", pady=1)
tk.Checkbutton(df, text="Show snapped track  (amber)",
               variable=show_snap_var,
               command=lambda: redraw_map(), **_ckw).pack(fill="x", pady=1)

# ── REVIEW ACTIONS ─────────────────────────────────────────────────────────────
sec_hdr(left, "REVIEW")
rev = tk.Frame(left, bg=C["panel"]); rev.pack(fill="x", padx=10, pady=6)

mk_btn(rev, "✅  Accept All High-Conf", C["teal"],
        lambda: auto_accept_all(), font=("Consolas", 8, "bold")
        ).pack(fill="x", pady=2)
mk_btn(rev, "✅  Accept All", C["dim"],
        lambda: set_all_accepted(True), font=("Consolas", 8)
        ).pack(fill="x", pady=2)
mk_btn(rev, "❌  Reject All", C["dim"],
        lambda: set_all_accepted(False), font=("Consolas", 8)
        ).pack(fill="x", pady=2)

export_btn = mk_btn(rev, "💾  Export Merged GPX", C["green"],
                     lambda: export_gpx(), state="disabled")
export_btn.pack(fill="x", pady=(8, 2))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN AREA  (chunk list + map)
# ═══════════════════════════════════════════════════════════════════════════════
main = tk.Frame(body_frame, bg=C["bg"])
main.pack(side="left", fill="both", expand=True, padx=8, pady=10)

main.grid_columnconfigure(0, weight=0)   # chunk list — fixed
main.grid_columnconfigure(1, weight=1)   # map — expands
main.grid_rowconfigure(0, weight=1)

# ── Chunk list (centre column) ────────────────────────────────────────────────
chunk_col = tk.Frame(main, bg=C["bg"], width=310)
chunk_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
chunk_col.pack_propagate(False)

ch2 = tk.Frame(chunk_col, bg=C["bg"]); ch2.pack(fill="x", pady=(0, 4))
tk.Label(ch2, text="CHUNKS",
         font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]
         ).pack(side="left")
tk.Label(ch2, text="click to highlight  ·  space/↵ to toggle accept",
         font=("Consolas", 7), bg=C["bg"], fg=C["dim"]
         ).pack(side="left", padx=(8, 0))

tree_border = tk.Frame(chunk_col, bg=C["accent"], padx=1, pady=1)
tree_border.pack(fill="both", expand=True)
tree_inner  = tk.Frame(tree_border, bg=C["panel2"])
tree_inner.pack(fill="both", expand=True)

cols = ("chunk", "pts", "conf", "status", "decision")
chunk_tree = ttk.Treeview(tree_inner, columns=cols, show="headings",
                           selectmode="browse")
chunk_tree.heading("chunk",    text="CHUNK")
chunk_tree.heading("pts",      text="PTS")
chunk_tree.heading("conf",     text="CONF")
chunk_tree.heading("status",   text="MATCH")
chunk_tree.heading("decision", text="USE")
chunk_tree.column("chunk",    width=52,  anchor="center")
chunk_tree.column("pts",      width=45,  anchor="center")
chunk_tree.column("conf",     width=55,  anchor="center")
chunk_tree.column("status",   width=52,  anchor="center")
chunk_tree.column("decision", width=82,  anchor="center")

chunk_tree.tag_configure("high",     foreground=C["green"])
chunk_tree.tag_configure("medium",   foreground=C["orange"])
chunk_tree.tag_configure("low",      foreground=C["red"])
chunk_tree.tag_configure("failed",   foreground=C["dim"])
chunk_tree.tag_configure("rejected", foreground=C["dim"])

tsb = ttk.Scrollbar(tree_inner, orient="vertical",
                     command=chunk_tree.yview)
chunk_tree.configure(yscrollcommand=tsb.set)
chunk_tree.pack(side="left", fill="both", expand=True)
tsb.pack(side="right", fill="y")

# chunk summary label
chunk_summary = tk.Label(chunk_col, text="",
                          font=("Consolas", 7), bg=C["bg"], fg=C["muted"])
chunk_summary.pack(anchor="w", pady=(4, 0))

# ── Map (right column) ────────────────────────────────────────────────────────
map_col = tk.Frame(main, bg=C["bg"])
map_col.grid(row=0, column=1, sticky="nsew")
map_col.pack_propagate(False)

mh = tk.Frame(map_col, bg=C["bg"]); mh.pack(fill="x", pady=(0, 4))
tk.Label(mh, text="TRACK MAP  —  raw (red)  ·  snapped (amber)  ·  selected (teal)",
         font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

zf = tk.Frame(mh, bg=C["bg"]); zf.pack(side="right")

def zoom_in():
    _current_zoom[0] = min(_current_zoom[0] + 1, 19)
    map_widget.set_zoom(_current_zoom[0])

def zoom_out():
    _current_zoom[0] = max(_current_zoom[0] - 1, 2)
    map_widget.set_zoom(_current_zoom[0])

mk_btn(zf, "⊙  Fit Track", C["dim"], lambda: fit_track(),
        font=("Consolas", 8)).pack(side="right", padx=(8, 0))
mk_btn(zf, "＋", C["panel2"], zoom_in,
        font=("Consolas", 11, "bold")).pack(side="right", padx=2)
mk_btn(zf, "－", C["panel2"], zoom_out,
        font=("Consolas", 11, "bold")).pack(side="right", padx=2)

map_border = tk.Frame(map_col, bg=C["accent"], padx=2, pady=2)
map_border.pack(fill="both", expand=True)
map_widget = tkintermapview.TkinterMapView(map_border, corner_radius=0)
map_widget.pack(fill="both", expand=True)
map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
map_widget.set_position(40.0, -3.7); map_widget.set_zoom(4)


# ─────────────────────────────────────────────────────────────────────────────
# STATUS BAR
# ─────────────────────────────────────────────────────────────────────────────
sb = tk.Frame(root, bg=C["panel"], height=28)
sb.pack(fill="x", side="bottom")
tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")

status_lbl = tk.Label(
    sb,
    text="Ready.  Open a GPX file, configure the OSRM server, then click Match.",
    font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
status_lbl.pack(side="left", padx=10, pady=3)

progress_var = tk.DoubleVar()
progress_bar = ttk.Progressbar(sb, variable=progress_var, maximum=100, length=240)
progress_bar.pack(side="left", padx=8, pady=3)

chunk_lbl = tk.Label(sb, text="", font=("Consolas", 8, "bold"),
                      bg=C["panel"], fg=C["accent"])
chunk_lbl.pack(side="left", padx=4)


def set_status(msg):
    status_lbl.config(text=msg)


# ─────────────────────────────────────────────────────────────────────────────
# MAP DRAWING
# ─────────────────────────────────────────────────────────────────────────────
# We keep a dict of drawn objects so we can selectively delete/redraw
_raw_path_obj     = [None]
_snap_paths       = {}    # chunk_idx → path object
_highlight_path   = [None]
_selected_chunk   = [None]


def _clear_map_objects():
    for obj in map_objects:
        try: obj.delete()
        except Exception: pass
    map_objects.clear()
    _raw_path_obj[0] = None
    _snap_paths.clear()
    if _highlight_path[0]:
        try: _highlight_path[0].delete()
        except Exception: pass
        _highlight_path[0] = None


def draw_raw_track():
    """Draw the raw GPX track on the map (dim red)."""
    _clear_map_objects()
    pts = app_state["raw_points"]
    if len(pts) < 2:
        return
    coords = [(la, lo) for la, lo, _ in pts]
    try:
        obj = map_widget.set_path(coords, color="#9e2a2a", width=2)
        _raw_path_obj[0] = obj
        map_objects.append(obj)
    except Exception:
        pass
    fit_track()


def fit_track():
    pts = app_state["raw_points"]
    if not pts:
        return
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    mid  = ((min(lats)+max(lats))/2, (min(lons)+max(lons))/2)
    span = max(max(lats)-min(lats), max(lons)-min(lons))
    z    = (7 if span > 5 else 9 if span > 2 else 10 if span > 1
            else 12 if span > 0.3 else 13 if span > 0.1 else 14)
    _current_zoom[0] = z
    try:
        map_widget.set_position(*mid)
        map_widget.set_zoom(z)
    except Exception:
        pass


def redraw_map():
    """Redraw raw + snapped layers according to checkboxes."""
    # Raw track
    if _raw_path_obj[0]:
        try: _raw_path_obj[0].delete()
        except Exception: pass
        _raw_path_obj[0] = None

    if show_raw_var.get() and len(app_state["raw_points"]) >= 2:
        coords = [(la, lo) for la, lo, _ in app_state["raw_points"]]
        try:
            obj = map_widget.set_path(coords, color="#9e2a2a", width=2)
            _raw_path_obj[0] = obj
        except Exception:
            pass

    # Snapped paths per chunk
    for idx, obj in list(_snap_paths.items()):
        try: obj.delete()
        except Exception: pass
    _snap_paths.clear()

    if show_snap_var.get():
        for i, (chunk, res) in enumerate(
                zip(app_state["chunks"], app_state["results"])):
            if not res.get("ok") or not res.get("snapped"):
                continue
            coords = [(la, lo) for la, lo, _ in res["snapped"]]
            if len(coords) < 2:
                continue
            color = C["accent"] if res.get("accepted") else C["dim"]
            try:
                obj = map_widget.set_path(coords, color=color, width=3)
                _snap_paths[i] = obj
            except Exception:
                pass


def highlight_chunk(chunk_idx: int):
    """Draw a teal highlight over one chunk (raw coords)."""
    if _highlight_path[0]:
        try: _highlight_path[0].delete()
        except Exception: pass
        _highlight_path[0] = None

    if chunk_idx is None or chunk_idx >= len(app_state["chunks"]):
        return

    chunk = app_state["chunks"][chunk_idx]
    coords = [(la, lo) for la, lo, _ in chunk["pts"]]
    if len(coords) < 2:
        return
    try:
        obj = map_widget.set_path(coords, color=C["teal"], width=5)
        _highlight_path[0] = obj
    except Exception:
        pass

    # Centre map on this chunk
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    mid  = ((min(lats)+max(lats))/2, (min(lons)+max(lons))/2)
    try:
        map_widget.set_position(*mid)
        map_widget.set_zoom(min(_current_zoom[0] + 2, 17))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# CHUNK TREE INTERACTION
# ─────────────────────────────────────────────────────────────────────────────
def _tree_row_tag(chunk_idx: int) -> str:
    results = app_state["results"]
    if chunk_idx >= len(results):
        return "failed"
    res = results[chunk_idx]
    if not res.get("ok"):
        return "failed"
    if not res.get("accepted"):
        return "rejected"
    conf = res.get("confidence", 0.0)
    if conf >= CONF_HIGH:   return "high"
    if conf >= CONF_MEDIUM: return "medium"
    return "low"


def _refresh_tree_row(chunk_idx: int):
    """Update a single row in the tree after accept/reject toggle."""
    results = app_state["results"]
    if chunk_idx >= len(results):
        return
    chunk  = app_state["chunks"][chunk_idx]
    res    = results[chunk_idx]
    conf   = res.get("confidence", 0.0)
    ok     = res.get("ok", False)
    acc    = res.get("accepted", False)
    n_pts  = len(chunk["pts"])
    conf_s = f"{conf:.2f}" if ok else "—"
    match  = "✅" if ok else "❌"
    use    = "✓ snapped" if (ok and acc) else ("✗ raw" if ok else "raw")
    tag    = _tree_row_tag(chunk_idx)

    iid = f"c{chunk_idx}"
    if chunk_tree.exists(iid):
        chunk_tree.item(iid,
                        values=(f"#{chunk_idx+1}", n_pts, conf_s, match, use),
                        tags=(tag,))
    _update_chunk_summary()


def _update_chunk_summary():
    results = app_state["results"]
    if not results:
        chunk_summary.config(text="")
        return
    total   = len(results)
    matched = sum(1 for r in results if r.get("ok"))
    accepted= sum(1 for r in results if r.get("ok") and r.get("accepted"))
    chunk_summary.config(
        text=f"{matched}/{total} matched  ·  {accepted} accepted  ·  "
             f"{total-accepted} using raw")


def _on_chunk_select(event=None):
    sel = chunk_tree.selection()
    if not sel:
        return
    iid = sel[0]
    try:
        idx = int(iid[1:])   # strip leading "c"
    except ValueError:
        return
    _selected_chunk[0] = idx
    highlight_chunk(idx)
    set_status(f"Chunk #{idx+1}  —  "
               f"rows {app_state['chunks'][idx]['raw_start']}–"
               f"{app_state['chunks'][idx]['raw_end']}")


def _on_chunk_toggle(event=None):
    """Space or Enter in the tree toggles accept/reject for selected chunk."""
    sel = chunk_tree.selection()
    if not sel:
        return
    iid = sel[0]
    try:
        idx = int(iid[1:])
    except ValueError:
        return
    results = app_state["results"]
    if idx >= len(results):
        return
    res = results[idx]
    if not res.get("ok"):
        set_status("Cannot toggle — chunk failed to match.")
        return
    res["accepted"] = not res.get("accepted", True)
    _refresh_tree_row(idx)
    _redraw_snap_chunk(idx)


chunk_tree.bind("<<TreeviewSelect>>", _on_chunk_select)
chunk_tree.bind("<space>",  _on_chunk_toggle)
chunk_tree.bind("<Return>", _on_chunk_toggle)


def _redraw_snap_chunk(chunk_idx: int):
    """Redraw just one snapped path after accept/reject change."""
    if chunk_idx in _snap_paths:
        try: _snap_paths[chunk_idx].delete()
        except Exception: pass
        del _snap_paths[chunk_idx]

    if not show_snap_var.get():
        return
    results = app_state["results"]
    if chunk_idx >= len(results):
        return
    res = results[chunk_idx]
    if not res.get("ok") or not res.get("snapped"):
        return
    coords = [(la, lo) for la, lo, _ in res["snapped"]]
    if len(coords) < 2:
        return
    color = C["accent"] if res.get("accepted") else "#666600"
    try:
        obj = map_widget.set_path(coords, color=color, width=3)
        _snap_paths[chunk_idx] = obj
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# BULK REVIEW ACTIONS
# ─────────────────────────────────────────────────────────────────────────────
def auto_accept_all():
    thresh = float(auto_accept_var.get())
    for i, res in enumerate(app_state["results"]):
        if res.get("ok"):
            res["accepted"] = res.get("confidence", 0.0) >= thresh
        _refresh_tree_row(i)
    redraw_map()
    _update_chunk_summary()


def set_all_accepted(flag: bool):
    for i, res in enumerate(app_state["results"]):
        if res.get("ok"):
            res["accepted"] = flag
        _refresh_tree_row(i)
    redraw_map()
    _update_chunk_summary()


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────
def export_gpx():
    if not app_state["results"]:
        messagebox.showwarning("Nothing to export", "Run matching first.")
        return

    raw    = app_state["raw_points"]
    chunks = app_state["chunks"]
    res    = app_state["results"]
    merged = stitch_chunks(chunks, res, raw)

    n_acc  = sum(1 for r in res if r.get("ok") and r.get("accepted"))
    n_tot  = len(res)

    src      = app_state["gpx_path"] or "track"
    stem     = Path(src).stem
    def_name = stem + "_snapped.gpx"
    out_path = filedialog.asksaveasfilename(
        defaultextension=".gpx",
        initialfile=def_name,
        filetypes=[("GPX files", "*.gpx")])
    if not out_path:
        return

    try:
        save_gpx(merged, out_path,
                 description=(f"Road Snap {VERSION} · "
                               f"{n_acc}/{n_tot} chunks snapped"))
        km = track_total_km([(p[0], p[1]) for p in merged])
        set_status(f"Saved: {Path(out_path).name}  —  "
                   f"{len(merged):,} pts  {km:.2f} km")
        messagebox.showinfo("Exported",
                             f"Merged GPX saved!\n\n"
                             f"  Points   : {len(merged):,}\n"
                             f"  Distance : {km:.2f} km\n"
                             f"  Snapped  : {n_acc}/{n_tot} chunks\n\n"
                             f"→ {Path(out_path).name}")
    except Exception as e:
        messagebox.showerror("Export error", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# MATCHING CONTROL
# ─────────────────────────────────────────────────────────────────────────────
def _set_phase_ui(phase: str):
    app_state["phase"] = phase
    if phase == "idle":
        match_btn.config(state="disabled", bg=C["dim"], fg=C["muted"])
        stop_btn.config( state="disabled", bg=C["dim"], fg=C["muted"])
        export_btn.config(state="disabled", bg=C["dim"], fg=C["muted"])
    elif phase == "loaded":
        match_btn.config(state="normal",   bg=C["green"], fg="white")
        stop_btn.config( state="disabled", bg=C["dim"],   fg=C["muted"])
        export_btn.config(state="disabled", bg=C["dim"],  fg=C["muted"])
    elif phase == "matching":
        match_btn.config(state="disabled", bg=C["dim"],   fg=C["muted"])
        stop_btn.config( state="normal",   bg=C["red"],   fg="white")
        export_btn.config(state="disabled", bg=C["dim"],  fg=C["muted"])
    elif phase in ("review", "done"):
        match_btn.config(state="normal",   bg=C["blue"],  fg="white")
        stop_btn.config( state="disabled", bg=C["dim"],   fg=C["muted"])
        export_btn.config(state="normal",  bg=C["green"], fg="white")


def start_matching():
    if app_state["phase"] == "matching":
        return
    if not app_state["chunks"]:
        messagebox.showwarning("No data", "Load a GPX file first.")
        return

    try:
        radius = int(radius_var.get())
    except ValueError:
        radius = DEFAULT_RADIUS

    server = server_var.get().strip()
    if not server:
        messagebox.showwarning("No server", "Enter an OSRM server URL.")
        return

    # Reset results and tree
    app_state["results"] = []
    chunk_tree.delete(*chunk_tree.get_children())
    progress_var.set(0)
    chunk_lbl.config(text="")

    # Pre-populate tree rows as pending
    for i, chunk in enumerate(app_state["chunks"]):
        chunk_tree.insert("", "end", iid=f"c{i}",
                          values=(f"#{i+1}", len(chunk["pts"]),
                                  "…", "…", "pending"),
                          tags=("failed",))

    stop_ev.clear()
    _set_phase_ui("matching")
    set_status("Starting OSRM matching…")

    # Clear snapped paths from any previous run
    for obj in _snap_paths.values():
        try: obj.delete()
        except Exception: pass
    _snap_paths.clear()

    t = threading.Thread(
        target=match_worker,
        args=(app_state["chunks"], server, radius, ui_q, stop_ev),
        daemon=True)
    t.start()
    root.after(100, pump_ui_queue)


def stop_matching():
    stop_ev.set()
    set_status("Stopping…")


# ─────────────────────────────────────────────────────────────────────────────
# UI QUEUE PUMP
# ─────────────────────────────────────────────────────────────────────────────
def pump_ui_queue():
    try:
        while True:
            msg = ui_q.get_nowait()
            cmd = msg[0]

            if cmd == "match_progress":
                _, i, total, text = msg
                pct = int(100 * i / max(total, 1))
                progress_var.set(pct)
                chunk_lbl.config(text=f"{i}/{total}")
                set_status(text)

            elif cmd == "chunk_result":
                _, cidx, ok, conf, err, raw_start, raw_end = msg
                n_pts = len(app_state["chunks"][cidx]["pts"])

                # Build result entry and append
                conf_s = f"{conf:.2f}" if ok else "—"
                match  = "✅" if ok else "❌"
                thresh = float(auto_accept_var.get())
                accepted = ok and conf >= thresh
                res_entry = {
                    "ok":         ok,
                    "confidence": conf,
                    "accepted":   accepted,
                    "snapped":    [],    # filled in match_done
                    "error":      err,
                }
                # Pad results list if needed
                while len(app_state["results"]) <= cidx:
                    app_state["results"].append({})
                app_state["results"][cidx] = res_entry

                use   = "✓ snapped" if (ok and accepted) else ("✗ raw" if ok else "raw")
                tag   = _tree_row_tag(cidx)
                iid   = f"c{cidx}"
                if chunk_tree.exists(iid):
                    chunk_tree.item(iid,
                                    values=(f"#{cidx+1}", n_pts,
                                            conf_s, match, use),
                                    tags=(tag,))
                chunk_tree.see(iid)

                if err:
                    set_status(f"Chunk #{cidx+1}: {err}")

            elif cmd == "match_done":
                _, full_results = msg
                # full_results is the complete list from the worker
                # — merge snapped coords in
                for i, res in enumerate(full_results):
                    if i < len(app_state["results"]):
                        app_state["results"][i].update(res)
                    else:
                        app_state["results"].append(res)

                progress_var.set(100)
                n_ok  = sum(1 for r in app_state["results"] if r.get("ok"))
                n_tot = len(app_state["results"])
                set_status(
                    f"Matching complete — {n_ok}/{n_tot} chunks matched  ·  "
                    "review below then export")
                chunk_lbl.config(text=f"{n_ok}/{n_tot} OK")
                _set_phase_ui("review")
                _update_chunk_summary()
                redraw_map()
                export_btn.config(state="normal",
                                   bg=C["green"], fg="white")

            elif cmd == "match_aborted":
                n_done = len(app_state["results"])
                set_status(f"Stopped — {n_done} chunks processed")
                _set_phase_ui("review")
                _update_chunk_summary()
                redraw_map()
                if app_state["results"]:
                    export_btn.config(state="normal",
                                       bg=C["orange"], fg="white")

    except queue.Empty:
        pass

    if app_state["phase"] == "matching":
        root.after(100, pump_ui_queue)


# ─────────────────────────────────────────────────────────────────────────────
# CLOSE HANDLER
# ─────────────────────────────────────────────────────────────────────────────
def on_close():
    if app_state["phase"] == "matching":
        if not messagebox.askyesno("Quit", "Matching in progress. Quit?"):
            return
        stop_ev.set()
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root.mainloop()
