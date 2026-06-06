#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Road Scout  v1.2
Author : Marco Cot
Contact: marcocot1982@gmail.com

Visual Odometry GPX Estimator.
Estimates a GPS track from any forward-facing onboard video.
No embedded GPS needed — only a known start position and camera height.

New in v1.2:
  • Map picker: Nominatim search bar — type town/address, press Enter to pan
  • Map picker: live rotating heading arrow centred on start point;
    mouse movement tilts the needle in real time, click to lock heading.
    No second-point click needed.

New in v1.1:
  • "Pick on Map" dialog with two-click start + aim workflow.
"""

import os, sys, math, time, threading, queue
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import cv2
import numpy as np
import gpxpy, gpxpy.gpx
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageTk
import tkintermapview

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
VERSION        = "v1.3"
AUTHOR         = "Marco Cot"
CONTACT        = "marcocot1982@gmail.com"
SPLASH_SECONDS = 4

ROAD_DEPTH_MIN_M  = 2.0
ROAD_DEPTH_MAX_M  = 28.0
STOP_FLOW_THRESH  = 0.35
BORDER_STRIP_FRAC = 0.09
FLOW_ARROW_SCALE  = 3
FLOW_STEP_PX      = 32
DRAG_THRESHOLD    = 6
HDG_SMOOTH_WIN    = 30   # steps — ~1.2s at 5fps; averages out EIS oscillation

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA  = f"RoadScout/{VERSION} contact:{CONTACT}"

# Arrow geometry (canvas pixels)
ARROW_LENGTH   = 90    # shaft length
ARROW_HEAD     = 22    # arrowhead length
ARROW_WIDTH    = 3     # shaft width
ARROW_HEAD_W   = 14    # arrowhead half-width
CIRCLE_R       = 10    # centre dot radius

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
}

COMPASS_DIRS = {
      0: "N",   22.5: "NNE",  45: "NE",  67.5: "ENE",
     90: "E",  112.5: "ESE", 135: "SE", 157.5: "SSE",
    180: "S",  202.5: "SSW", 225: "SW", 247.5: "WSW",
    270: "W",  292.5: "WNW", 315: "NW", 337.5: "NNW",
}

def compass_label(deg: float) -> str:
    nearest = min(COMPASS_DIRS, key=lambda k: abs((deg - k + 180) % 360 - 180))
    return COMPASS_DIRS[nearest]


# ─────────────────────────────────────────────────────────────────────────────
# WINDOW ICON
# ─────────────────────────────────────────────────────────────────────────────
def _make_icon(size: int = 64) -> ImageTk.PhotoImage:
    S   = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    amber = (245, 166, 35, 255)
    dark  = (20,  20,  20, 255)
    white = (232, 232, 232, 200)
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
    dw, dh = max(2, int(ir*0.26)), max(1, int(ir*0.13))
    gy = cy_p - int(ir * 0.52)
    for _ in range(3):
        d.rectangle([cx - dw//2, gy, cx + dw//2, gy + dh], fill=white)
        gy += dh * 3
    return ImageTk.PhotoImage(img)


def _apply_icon(win: tk.Tk):
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


def labeled_entry(parent, label, var, width=9):
    r = tk.Frame(parent, bg=C["panel"])
    r.pack(fill="x", pady=2)
    tk.Label(r, text=label, font=("Consolas", 8), bg=C["panel"],
             fg=C["muted"], width=14, anchor="w").pack(side="left")
    e = tk.Entry(r, textvariable=var, width=width,
                 bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
                 relief="flat", highlightthickness=1,
                 highlightcolor=C["accent"], highlightbackground=C["border"],
                 font=("Consolas", 9))
    e.pack(side="left", padx=(4, 0))
    return e


def dim_lbl(parent, text):
    tk.Label(parent, text=text, font=("Consolas", 7), bg=C["panel"],
             fg=C["dim"], justify="left", wraplength=245
             ).pack(padx=10, anchor="w", pady=(2, 0))


# ─────────────────────────────────────────────────────────────────────────────
# GEO MATH
# ─────────────────────────────────────────────────────────────────────────────
_R = 6_371_000.0


def move_point(lat, lon, heading_deg, dist_m):
    if dist_m == 0:
        return lat, lon
    hr    = math.radians(heading_deg)
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    d_r   = dist_m / _R
    nlat  = math.asin(math.sin(lat_r) * math.cos(d_r)
                      + math.cos(lat_r) * math.sin(d_r) * math.cos(hr))
    nlon  = lon_r + math.atan2(
        math.sin(hr) * math.sin(d_r) * math.cos(lat_r),
        math.cos(d_r) - math.sin(lat_r) * math.sin(nlat))
    return math.degrees(nlat), math.degrees(nlon)


def canvas_to_latlon(map_widget, cx, cy):
    """Convert canvas pixel coords → (lat, lon)."""
    try:
        return map_widget.convert_canvas_coords_to_decimal_coords(cx, cy)
    except Exception:
        pass
    try:
        zoom   = map_widget.zoom
        ul     = map_widget.upper_left_tile_pos
        tile_x = ul[0] + cx / 256.0
        tile_y = ul[1] + cy / 256.0
        n      = 2 ** zoom
        lon    = tile_x / n * 360.0 - 180.0
        lat_r  = math.atan(math.sinh(math.pi * (1 - 2 * tile_y / n)))
        return math.degrees(lat_r), lon
    except Exception:
        return None, None


def latlon_to_canvas(map_widget, lat, lon):
    """
    Convert (lat, lon) → pixel coords on map_widget.canvas.
    Returns (x, y) as floats, or None on failure.
    Tries the public API first, falls back to tile maths.
    """
    # Method 1: public API (tkintermapview ≥ 0.2)
    try:
        result = map_widget.convert_decimal_coords_to_canvas_coords(lat, lon)
        if result is not None and len(result) == 2:
            return float(result[0]), float(result[1])
    except Exception:
        pass

    # Method 2: tile maths using upper_left_tile_pos
    try:
        zoom = map_widget.zoom
        ul   = map_widget.upper_left_tile_pos
        if ul is None:
            return None
        n      = 2.0 ** zoom
        tile_x = (lon + 180.0) / 360.0 * n
        lat_r  = math.radians(lat)
        tile_y = (1 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2 * n
        cx = (tile_x - ul[0]) * 256.0
        cy = (tile_y - ul[1]) * 256.0
        # Sanity: must be within 2× the visible canvas
        cw = map_widget.canvas.winfo_width()  or 800
        ch = map_widget.canvas.winfo_height() or 600
        if -cw < cx < 2*cw and -ch < cy < 2*ch:
            return cx, cy
    except Exception:
        pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NOMINATIM GEOCODING
# ─────────────────────────────────────────────────────────────────────────────
def nominatim_search(query: str, timeout: int = 6):
    """
    Search Nominatim for query string.
    Returns list of {"display_name", "lat", "lon"} dicts, or [].
    """
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 6},
            headers={"User-Agent": NOMINATIM_UA},
            timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return [{"display_name": r.get("display_name", ""),
                 "lat": float(r["lat"]),
                 "lon": float(r["lon"])}
                for r in data if "lat" in r and "lon" in r]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# CAMERA MODEL
# ─────────────────────────────────────────────────────────────────────────────
def build_camera_matrix(w, h, hfov_deg):
    fx = (w / 2.0) / math.tan(math.radians(hfov_deg / 2.0))
    fy = fx
    return np.array([[fx,  0, w / 2.0],
                     [ 0, fy, h / 2.0],
                     [ 0,  0,     1.0]], dtype=np.float64)


# ─────────────────────────────────────────────────────────────────────────────
# OPTICAL FLOW ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _road_row_range(cam, frame_h, cam_h_m):
    fy     = cam[1, 1];  cy = cam[1, 2]
    v_near = int(fy * cam_h_m / ROAD_DEPTH_MIN_M + cy)
    v_far  = int(fy * cam_h_m / ROAD_DEPTH_MAX_M + cy)
    return min(v_near, int(frame_h * 0.94)), max(v_far, int(frame_h * 0.42))


def estimate_forward_displacement_sparse(gray1, gray2, cam, cam_h_m):
    """
    Estimate forward displacement in metres using SPARSE Lucas-Kanade
    features restricted to the 5–10 m depth band.

    This is robust to EIS (Electronic Image Stabilisation) because sparse
    features at road edges retain real motion even when EIS zeros the
    background.  Returns (displacement_m, n_features_used).

    Calibration note: the road-plane geometry gives the right SHAPE of
    the speed profile but typically over-estimates by ~1.8x on dashcam
    footage with EIS.  Apply speed_cal multiplier after this function.
    """
    h_px, w_px = gray1.shape[:2]
    fy  = cam[1, 1]
    cy  = cam[1, 2]

    # Depth band 5–10 m → pixel row range
    v_lo = int(fy * cam_h_m / 10.0 + cy)
    v_hi = int(fy * cam_h_m /  5.0 + cy)
    v_lo = max(v_lo, int(h_px * 0.30))
    v_hi = min(v_hi, int(h_px * 0.94))
    if v_lo >= v_hi:
        return 0.0, 0

    mask = np.zeros((h_px, w_px), dtype=np.uint8)
    mask[v_lo:v_hi, int(w_px * 0.15):int(w_px * 0.85)] = 255

    feat = dict(maxCorners=300, qualityLevel=0.005, minDistance=10, blockSize=5)
    pts1 = cv2.goodFeaturesToTrack(gray1, mask=mask, **feat)
    if pts1 is None or len(pts1) < 4:
        return 0.0, 0

    lk   = dict(winSize=(21, 21), maxLevel=4,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.005))
    pts2, st, _ = cv2.calcOpticalFlowPyrLK(gray1, gray2, pts1, None, **lk)
    if pts2 is None:
        return 0.0, 0

    ok = st.ravel() == 1
    if ok.sum() < 4:
        return 0.0, 0

    p1, p2 = pts1[ok], pts2[ok]
    deltas = []
    for i in range(len(p1)):
        v  = float(p1[i, 0, 1])
        dv = v - cy
        if dv < 10:
            continue
        vy = float(p2[i, 0, 1] - p1[i, 0, 1])
        if vy < 0.2:
            continue
        D  = fy * cam_h_m / dv
        if not 5.0 <= D <= 10.0:
            continue
        dm = vy * fy * cam_h_m / (dv ** 2)
        if 0.0 < dm < D:
            deltas.append(dm)

    if not deltas:
        return 0.0, 0
    return float(np.median(deltas)), len(deltas)


def estimate_forward_displacement(flow, cam, cam_h_m):
    """Legacy dense-flow estimator — kept for border-activity fallback only."""
    h_px, w_px = flow.shape[:2]
    fy = cam[1, 1];  cy = cam[1, 2]
    v_near, v_far = _road_row_range(cam, h_px, cam_h_m)
    col_lo, col_hi = int(w_px * 0.18), int(w_px * 0.82)
    estimates = []
    for v in range(v_far, v_near, 4):
        dv = v - cy
        if dv < 2: continue
        row_vy   = flow[v, col_lo:col_hi, 1]
        fwd_mask = row_vy > STOP_FLOW_THRESH
        if fwd_mask.sum() < 5: continue
        median_vy = float(np.median(row_vy[fwd_mask]))
        D_est     = fy * cam_h_m / dv
        delta_m   = median_vy * fy * cam_h_m / (dv ** 2)
        if 0.0 < delta_m < D_est:
            estimates.append(delta_m)
    return float(np.median(estimates)) if len(estimates) >= 6 else 0.0


def estimate_border_activity(flow, h, w):
    bw   = max(1, int(w * BORDER_STRIP_FRAC))
    r_lo = int(h * 0.38);  r_hi = int(h * 0.82)
    left  = np.abs(flow[r_lo:r_hi, :bw,     0])
    right = np.abs(flow[r_lo:r_hi, w - bw:, 0])
    return float((np.median(left) + np.median(right)) / 2.0)


def estimate_heading_delta_fx(flow: np.ndarray,
                               sensitivity: float) -> float:
    """
    Estimate heading change (degrees/step) from horizontal optical flow
    in the centre-right road zone (45–75% height, 45–65% width).

    Empirical calibration on reference dashcam footage (2016-12-19):
      CAL_BASE = -1.027  (corrected from -1.4729 after measuring 1.43x over-turn)
      Total turn error: ~3%  |  RMSE: ~31°

    sensitivity=0 → locked heading.
    sensitivity=1.0 → calibrated (recommended starting point).
    Tune up for more responsive turns, down to reduce noise.
    """
    if sensitivity == 0.0:
        return 0.0

    h_px, w_px = flow.shape[:2]
    row_lo = int(h_px * 0.45)
    row_hi = int(h_px * 0.75)
    col_lo = int(w_px * 0.45)
    col_hi = int(w_px * 0.65)

    fx = float(np.mean(flow[row_lo:row_hi, col_lo:col_hi, 0]))
    CAL_BASE = -1.027
    return fx * CAL_BASE * sensitivity


# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC OVERLAY
# ─────────────────────────────────────────────────────────────────────────────
def draw_overlay(frame_bgr, flow, cam, cam_h_m, heading, speed_kmh, dist_km):
    vis    = frame_bgr.copy()
    fh, fw = vis.shape[:2]
    v_near, v_far = _road_row_range(cam, fh, cam_h_m)
    col_lo, col_hi = int(fw * 0.18), int(fw * 0.82)
    bw   = max(1, int(fw * BORDER_STRIP_FRAC))
    r_lo = int(fh * 0.38);  r_hi = int(fh * 0.82)

    cv2.rectangle(vis, (col_lo, v_far), (col_hi, min(v_near, fh - 2)), (245, 166, 35), 1)
    cv2.putText(vis, "road plane", (col_lo + 4, v_far + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.36, (245, 166, 35), 1)
    cv2.rectangle(vis, (0, r_lo),        (bw,     r_hi), (38, 166, 154), 1)
    cv2.rectangle(vis, (fw - bw, r_lo),  (fw - 1, r_hi), (38, 166, 154), 1)
    cv2.putText(vis, "L", (2, r_lo + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (38, 166, 154), 1)
    cv2.putText(vis, "R", (fw - bw + 2, r_lo + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (38, 166, 154), 1)
    # Heading zone — centre-right strip (magenta)
    hc_lo = int(fw * 0.45); hc_hi = int(fw * 0.65)
    hr_lo = int(fh * 0.45); hr_hi = int(fh * 0.75)
    cv2.rectangle(vis, (hc_lo, hr_lo), (hc_hi, hr_hi), (180, 0, 180), 1)
    cv2.putText(vis, "hdg", (hc_lo + 3, hr_lo + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 0, 180), 1)

    step = FLOW_STEP_PX
    for vy in range(0, fh, step):
        for vx in range(0, fw, step):
            dx  = float(flow[vy, vx, 0]) * FLOW_ARROW_SCALE
            dy  = float(flow[vy, vx, 1]) * FLOW_ARROW_SCALE
            if math.hypot(dx, dy) < 0.7: continue
            cv2.arrowedLine(vis, (vx, vy),
                            (int(vx + dx), int(vy + dy)),
                            (76, 175, 80), 1, tipLength=0.35)

    hud = f"{speed_kmh:5.1f} km/h   hdg {heading:6.1f}\xb0   {dist_km:.3f} km"
    cv2.rectangle(vis, (0, fh - 22), (fw, fh), (20, 20, 20), -1)
    cv2.putText(vis, hud, (8, fh - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (232, 232, 232), 1)
    return vis


# ─────────────────────────────────────────────────────────────────────────────
# GPX WRITER
# ─────────────────────────────────────────────────────────────────────────────
def write_gpx(track_pts, out_path, start_lat, start_lon, cam_h, hfov):
    gpx = gpxpy.gpx.GPX()
    gpx.name = Path(out_path).stem
    gpx.description = (f"Road Scout VO track · start ({start_lat:.6f},{start_lon:.6f}) "
                       f"· cam height {cam_h}m · FOV {hfov}°")
    trk = gpxpy.gpx.GPXTrack(); gpx.tracks.append(trk)
    seg = gpxpy.gpx.GPXTrackSegment(); trk.segments.append(seg)
    for lat, lon, t in track_pts:
        seg.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, time=t))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(gpx.to_xml())


# ─────────────────────────────────────────────────────────────────────────────
# PROCESSING ENGINE  (worker thread)
# ─────────────────────────────────────────────────────────────────────────────
def process_video(video_path, start_lat, start_lon, initial_heading,
                  cam_h_m, hfov_deg, sample_fps, smoothing,
                  speed_cal, hdg_sensitivity,
                  start_time, output_gpx,
                  ui_queue, stop_event, pause_event):

    def log(msg, tag=""):
        ui_queue.put(("log", msg, tag))

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log(f"❌  Cannot open: {video_path}", "err")
        ui_queue.put(("done_err",)); return

    vid_fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_f    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w_full     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_full     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_s = total_f / max(vid_fps, 1)

    log(f"📹  {Path(video_path).name}  —  {w_full}×{h_full}  {vid_fps:.1f}fps  {duration_s:.0f}s")

    frame_step = max(1, int(round(vid_fps / sample_fps)))
    dt_step    = frame_step / vid_fps
    actual_fps = vid_fps / frame_step

    # Window for heading: HDG_SMOOTH_WIN steps at sample_fps ≈ 1.2s at 5fps
    log(f"📐  Camera {cam_h_m}m · FOV {hfov_deg}° · every {frame_step} frames "
        f"({actual_fps:.1f} fps) · hdg smooth {HDG_SMOOTH_WIN} steps "
        f"({HDG_SMOOTH_WIN*dt_step:.1f}s) · sens {hdg_sensitivity:.1f}")

    SCALE    = 0.5
    w_ds, h_ds = max(1, int(w_full * SCALE)), max(1, int(h_full * SCALE))
    cam_ds   = build_camera_matrix(w_ds, h_ds, hfov_deg)
    DISP_W   = min(w_full, 640)
    DISP_H   = max(1, int(h_full * DISP_W / w_full))
    cam_disp = build_camera_matrix(DISP_W, DISP_H, hfov_deg)

    lat, lon      = start_lat, start_lon
    heading       = initial_heading
    track_pts     = [(lat, lon, start_time)]
    total_dist    = 0.0
    prev_gray_ds  = None
    spd_buf       = []
    fx_buf        = []   # rolling buffer of raw heading deltas for smoothing
    wall_start    = time.time()
    frame_idx     = 0
    eis_warned    = False

    log("▶  Processing…", "info")
    ui_queue.put(("track_point", lat, lon, True))

    while True:
        ret, frame_bgr = cap.read()
        if not ret: break

        if frame_idx % frame_step != 0:
            frame_idx += 1
            continue

        while not pause_event.is_set():
            if stop_event.is_set(): break
            time.sleep(0.08)
        if stop_event.is_set():
            log("⏹  Stopped — writing partial track…", "err")
            break

        frame_ds = cv2.resize(frame_bgr, (w_ds, h_ds), interpolation=cv2.INTER_AREA)
        gray_ds  = cv2.cvtColor(frame_ds, cv2.COLOR_BGR2GRAY)

        elapsed_s  = frame_idx / vid_fps
        point_time = start_time + timedelta(seconds=elapsed_s)
        speed_ms   = 0.0
        dist_step  = 0.0

        if prev_gray_ds is not None:
            # ── Dense Farneback for border-activity fallback only ─────────────
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray_ds, gray_ds, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0)

            # ── Speed: sparse LK in the 5–10 m depth band ────────────────────
            disp_m, n_feats = estimate_forward_displacement_sparse(
                prev_gray_ds, gray_ds, cam_ds, cam_h_m)

            if disp_m == 0.0:
                bact = estimate_border_activity(flow, h_ds, w_ds)
                if bact > STOP_FLOW_THRESH * 3 and not eis_warned:
                    log("⚠  EIS detected — heading from video is approximate. "
                        "Use Road Snap after for best results.", "err")
                    eis_warned = True
                if bact > STOP_FLOW_THRESH:
                    disp_m = bact * 8.0 / cam_ds[0, 0]

            disp_m *= speed_cal
            spd_buf.append(disp_m)
            if len(spd_buf) > max(1, smoothing): spd_buf.pop(0)
            dist_step = float(np.median(spd_buf))
            speed_ms  = dist_step / max(dt_step, 1e-6)

            # ── Heading: centre-right flow_x with long smoothing window ──────
            # Empirically best method for EIS cameras.
            # smooth_win=30 steps at 5fps ≈ 1.2s — long enough to average out
            # EIS high-frequency oscillation, short enough to track real turns.
            if hdg_sensitivity > 0.0:
                raw_delta = estimate_heading_delta_fx(flow, hdg_sensitivity)
                fx_buf.append(raw_delta)
                if len(fx_buf) > HDG_SMOOTH_WIN:
                    fx_buf.pop(0)
                smooth_delta = float(np.mean(fx_buf))

                # Mean-reversion decay: on straight sections the EIS residual
                # slowly drifts the heading. A 2% pull toward initial_heading
                # per step corrects this without fighting real turns.
                # After 50 zero-input steps (~10s at 5fps) heading is 63% back.
                DECAY = 0.98
                heading = (heading * DECAY
                           + initial_heading * (1.0 - DECAY)
                           + smooth_delta) % 360.0

            if dist_step > 0:
                lat, lon = move_point(lat, lon, heading, dist_step)
                total_dist += dist_step

            track_pts.append((lat, lon, point_time))

            frame_disp = cv2.resize(frame_bgr, (DISP_W, DISP_H), interpolation=cv2.INTER_AREA)
            flow_disp  = cv2.resize(flow,      (DISP_W, DISP_H), interpolation=cv2.INTER_AREA)
            vis = draw_overlay(frame_disp, flow_disp, cam_disp,
                               cam_h_m, heading, speed_ms * 3.6, total_dist / 1000.0)
        else:
            vis = cv2.resize(frame_bgr, (DISP_W, DISP_H), interpolation=cv2.INTER_AREA)

        prev_gray_ds = gray_ds

        pct     = int(100 * frame_idx / max(1, total_f))
        elapsed = time.time() - wall_start
        eta_s   = max(0, elapsed / pct * 100 - elapsed) if pct > 0 else 0
        eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_s))

        pil = Image.fromarray(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
        ui_queue.put(("frame",       pil))
        ui_queue.put(("track_point", lat, lon, False))
        ui_queue.put(("progress",    pct, eta_str,
                      speed_ms * 3.6, heading, lat, lon, total_dist, len(track_pts)))
        frame_idx += 1

    cap.release()

    if len(track_pts) > 1:
        try:
            write_gpx(track_pts, output_gpx, start_lat, start_lon, cam_h_m, hfov_deg)
            log(f"✅  {len(track_pts):,} points · {total_dist/1000:.3f} km  →  {output_gpx}", "ok")
            ui_queue.put(("done", output_gpx, len(track_pts), total_dist))
        except Exception as e:
            log(f"❌  Save failed: {e}", "err")
            ui_queue.put(("done_err",))
    else:
        log("⚠  Not enough points to write a GPX file.", "err")
        ui_queue.put(("done_err",))


# ─────────────────────────────────────────────────────────────────────────────
# GUI — root window
# ─────────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title(f"Road Scout  {VERSION}")
root.configure(bg=C["bg"])
_apply_icon(root)
try:    root.state("zoomed")
except: root.geometry("1440x860")
root.resizable(True, True)

sty = ttk.Style(root); sty.theme_use("clam")
sty.configure(".",          background=C["bg"],    foreground=C["text"])
sty.configure("TLabel",     background=C["bg"],    foreground=C["text"], font=("Consolas", 9))
sty.configure("TFrame",     background=C["bg"])
sty.configure("TScrollbar", background=C["panel2"], troughcolor=C["border"], arrowcolor=C["muted"])
sty.configure("Horizontal.TProgressbar",
               background=C["accent"], troughcolor=C["panel2"],
               bordercolor=C["border"], lightcolor=C["accent"], darkcolor=C["accent2"])

# ── application state ─────────────────────────────────────────────────────────
ui_q          = queue.Queue()
stop_ev       = threading.Event()
pause_ev      = threading.Event(); pause_ev.set()
proc_state    = {"running": False, "thread": None}
pause_btn_ref = [None]
map_path_obj  = [None]
map_marker    = [None]
map_coords    = []
_current_zoom = [14]
_video_w      = [480]

# ── tk variables ──────────────────────────────────────────────────────────────
video_path_var = tk.StringVar(value="")
lat_var        = tk.StringVar(value="")
lon_var        = tk.StringVar(value="")
heading_var    = tk.StringVar(value="0")
cam_height_var = tk.StringVar(value="1.20")
hfov_var       = tk.StringVar(value="90")
sample_fps_var = tk.StringVar(value="5")
smoothing_var  = tk.StringVar(value="5")
speed_cal_var     = tk.StringVar(value="1.80")   # speed calibration multiplier
hdg_sensitivity_var = tk.StringVar(value="1.0")    # 0=locked, >0=heading from video
start_time_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
dest_var       = tk.IntVar(value=2)
autocenter_var = tk.BooleanVar(value=True)


# ─────────────────────────────────────────────────────────────────────────────
# MAP PICKER DIALOG  (v1.2 — search bar + live rotating heading arrow)
# ─────────────────────────────────────────────────────────────────────────────
def open_map_picker():
    """
    Modal map picker — clean rewrite.
    Step 1: click map → green START pin.
    Step 2: move mouse → arrow rotates live. Click → lock heading.
    Search bar pans map; click anywhere to place start.
    """
    d = tk.Toplevel(root)
    d.title("Pick Start Position & Heading")
    d.configure(bg=C["bg"])
    d.geometry("1060x760")
    d.grab_set()
    _apply_icon(d)

    # ── state ──────────────────────────────────────────────────────────────
    st = {
        "step":          0,      # 0=place start  1=aim arrow  2=locked
        "start":         None,   # (lat, lon)
        "heading":       0.0,
        "start_marker":  None,
        "press_x":       0,
        "press_y":       0,
    }

    # ── top chrome ─────────────────────────────────────────────────────────
    tk.Frame(d, bg=C["accent"], height=3).pack(fill="x")
    hdr = tk.Frame(d, bg=C["bg"]); hdr.pack(fill="x", padx=16, pady=(8, 4))
    tk.Label(hdr, text="PICK START POSITION  &  HEADING",
             font=("Consolas", 11, "bold"),
             bg=C["bg"], fg=C["accent"]).pack(side="left")
    zf = tk.Frame(hdr, bg=C["bg"]); zf.pack(side="right")
    mk_btn(zf, "＋", C["panel2"],
           lambda: (pm.set_zoom(min(pm.zoom+1, 19))),
           font=("Consolas", 11, "bold")).pack(side="right", padx=2)
    mk_btn(zf, "－", C["panel2"],
           lambda: (pm.set_zoom(max(pm.zoom-1, 2))),
           font=("Consolas", 11, "bold")).pack(side="right", padx=2)
    tk.Frame(d, bg=C["border"], height=1).pack(fill="x")

    # ── search bar ─────────────────────────────────────────────────────────
    sf = tk.Frame(d, bg=C["panel2"]); sf.pack(fill="x", padx=10, pady=(6, 0))
    tk.Label(sf, text="🔍", font=("Consolas", 11),
             bg=C["panel2"], fg=C["accent"]).pack(side="left", padx=(10, 4))
    search_var = tk.StringVar()
    search_entry = tk.Entry(sf, textvariable=search_var,
                            font=("Consolas", 10),
                            bg=C["panel2"], fg=C["text"],
                            insertbackground=C["text"],
                            relief="flat", highlightthickness=0)
    search_entry.pack(side="left", fill="x", expand=True, ipady=6)
    search_status = tk.Label(sf, text="", font=("Consolas", 8),
                              bg=C["panel2"], fg=C["muted"])
    search_status.pack(side="left", padx=8)
    mk_btn(sf, "Search", C["blue"], lambda: _do_search(),
            font=("Consolas", 8, "bold")).pack(side="right", padx=6, pady=4)

    # Results listbox (hidden until search)
    results_frame = tk.Frame(d, bg=C["panel"])
    results_lb = tk.Listbox(results_frame,
                             bg=C["panel2"], fg=C["text"],
                             selectbackground=C["accent"],
                             selectforeground="black",
                             font=("Consolas", 8), activestyle="none",
                             relief="flat", borderwidth=0, height=0)
    results_lb.pack(fill="x")
    _search_results = []

    def _hide_results():
        results_lb.delete(0, tk.END)
        results_frame.place_forget()

    def _show_results():
        d.update_idletasks()
        x = sf.winfo_x(); y = sf.winfo_y() + sf.winfo_height()
        results_frame.place(x=x, y=y, width=sf.winfo_width())
        results_frame.lift()

    def _do_search():
        q = search_var.get().strip()
        if not q: return
        search_status.config(text="…", fg=C["muted"])
        d.update_idletasks()
        def _thread():
            res = nominatim_search(q)
            d.after(0, lambda: _on_search_done(res))
        threading.Thread(target=_thread, daemon=True).start()

    def _on_search_done(res):
        _search_results.clear(); _search_results.extend(res)
        results_lb.delete(0, tk.END)
        if not res:
            search_status.config(text="no results", fg=C["red"])
            return
        search_status.config(text=f"{len(res)} result(s)", fg=C["green"])
        for r in res:
            short = ", ".join(r["display_name"].split(",")[:3])
            results_lb.insert(tk.END, "  " + short)
        results_lb.config(height=min(len(res), 5))
        _show_results()

    def _on_result_select(event=None):
        sel = results_lb.curselection()
        if not sel: return
        r = _search_results[sel[0]]
        try:
            pm.set_position(r["lat"], r["lon"])
            pm.set_zoom(15)
        except Exception: pass
        _hide_results()
        search_status.config(text="")

    results_lb.bind("<<ListboxSelect>>", _on_result_select)
    results_lb.bind("<Return>",          _on_result_select)
    search_entry.bind("<Return>",        lambda e: _do_search())
    search_entry.bind("<Escape>",        lambda e: _hide_results())

    # ── instruction bar ────────────────────────────────────────────────────
    instr_frame = tk.Frame(d, bg=C["panel"], height=32)
    instr_frame.pack(fill="x", pady=(6, 0))
    instr_frame.pack_propagate(False)
    step_dot = tk.Label(instr_frame, text="●", font=("Consolas", 11),
                         bg=C["panel"], fg=C["green"])
    step_dot.pack(side="left", padx=(14, 6))
    instr_var = tk.StringVar(
        value="Click anywhere on the map to place the START point")
    tk.Label(instr_frame, textvariable=instr_var,
              font=("Consolas", 8), bg=C["panel"], fg=C["text"],
              anchor="w").pack(side="left", fill="x", expand=True)

    # ── map ────────────────────────────────────────────────────────────────
    map_border = tk.Frame(d, bg=C["accent"], padx=2, pady=2)
    map_border.pack(fill="both", expand=True, padx=10, pady=(4, 0))
    pm = tkintermapview.TkinterMapView(map_border, corner_radius=0)
    pm.pack(fill="both", expand=True)
    pm.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
    try:
        pm.set_position(float(lat_var.get()), float(lon_var.get()))
        pm.set_zoom(14)
    except ValueError:
        pm.set_position(40.0, -3.7); pm.set_zoom(4)

    # ── info bar ───────────────────────────────────────────────────────────
    info_bar = tk.Frame(d, bg=C["panel2"], height=44)
    info_bar.pack(fill="x", padx=10, pady=(4, 0))
    info_bar.pack_propagate(False)
    coord_lbl = tk.Label(info_bar, text="—",
                          font=("Consolas", 9),
                          bg=C["panel2"], fg=C["muted"])
    coord_lbl.pack(side="left", padx=14)
    hdg_lbl = tk.Label(info_bar, text="",
                        font=("Consolas", 10, "bold"),
                        bg=C["panel2"], fg=C["accent"])
    hdg_lbl.pack(side="left", padx=14)
    bb = tk.Frame(info_bar, bg=C["panel2"]); bb.pack(side="right", padx=10)

    def _reset():
        st["step"] = 0; st["start"] = None; st["heading"] = 0.0
        if st["start_marker"]:
            try: st["start_marker"].delete()
            except Exception: pass
            st["start_marker"] = None
        coord_lbl.config(text="—"); hdg_lbl.config(text="")
        step_dot.config(fg=C["green"])
        confirm_btn.config(state="disabled", bg=C["dim"], fg=C["muted"])
        instr_var.set("Click anywhere on the map to place the START point")

    mk_btn(bb, "↺ Reset",         C["dim"],   _reset,
            font=("Consolas", 8, "bold")).pack(side="left", padx=(0, 6))
    confirm_btn = mk_btn(bb, "✓ Confirm & Apply", C["green"], lambda: None,
                          state="disabled", font=("Consolas", 9, "bold"))
    confirm_btn.pack(side="left", padx=(0, 6))
    mk_btn(bb, "Cancel",          C["dim"],   d.destroy,
            font=("Consolas", 8, "bold")).pack(side="left")
    tk.Frame(d, bg=C["accent"], height=3).pack(fill="x", side="bottom")

    def _confirm():
        if st["start"] is None:
            messagebox.showwarning("No position", "Place a start point first.", parent=d)
            return
        slat, slon = st["start"]
        lat_var.set(f"{slat:.7f}")
        lon_var.set(f"{slon:.7f}")
        heading_var.set(f"{st['heading']:.1f}")
        status_lbl.config(
            text=f"Start ({slat:.6f}, {slon:.6f})  ·  "
                 f"heading {st['heading']:.1f}° {compass_label(st['heading'])}")
        d.destroy()

    confirm_btn.config(command=_confirm)

    # ── arrow drawing — directly on pm.canvas, tag-based ──────────────────
    # tkintermapview calls canvas.delete("all") on every tile redraw.
    # We redraw every 100ms so the arrow is never gone for more than a blink.

    def _canvas_xy():
        """lat/lon of start → (cx,cy) on pm.canvas, or None."""
        if st["start"] is None: return None
        return latlon_to_canvas(pm, st["start"][0], st["start"][1])

    def _draw_arrow(cx, cy, hdg_deg, locked=False):
        c = pm.canvas
        c.delete("picker_arrow")
        rad    = math.radians(hdg_deg)
        tip_x  = cx + ARROW_LENGTH * math.sin(rad)
        tip_y  = cy - ARROW_LENGTH * math.cos(rad)
        base_x = cx - ARROW_LENGTH * 0.18 * math.sin(rad)
        base_y = cy + ARROW_LENGTH * 0.18 * math.cos(rad)
        col    = C["accent"] if locked else "#ffe066"
        lw     = ARROW_WIDTH + 1 if locked else ARROW_WIDTH
        sh = 2
        c.create_line(base_x+sh, base_y+sh, tip_x+sh, tip_y+sh,
                      fill="#000000", width=lw+3, tags="picker_arrow")
        c.create_line(base_x, base_y, tip_x, tip_y,
                      fill=col, width=lw, tags="picker_arrow")
        px = math.cos(rad)*(ARROW_HEAD_W/2)
        py = math.sin(rad)*(ARROW_HEAD_W/2)
        bx = tip_x - ARROW_HEAD*math.sin(rad)
        by = tip_y + ARROW_HEAD*math.cos(rad)
        c.create_polygon(tip_x, tip_y, bx+px, by+py, bx-px, by-py,
                         fill=col, outline="", tags="picker_arrow")
        c.create_oval(cx-CIRCLE_R-1, cy-CIRCLE_R-1,
                      cx+CIRCLE_R+1, cy+CIRCLE_R+1,
                      fill="#000000", outline="", tags="picker_arrow")
        c.create_oval(cx-CIRCLE_R, cy-CIRCLE_R,
                      cx+CIRCLE_R, cy+CIRCLE_R,
                      fill=C["green"], outline="white", width=2,
                      tags="picker_arrow")
        anch = "w" if math.sin(rad) >= 0 else "e"
        lx = tip_x + 16*math.sin(rad); ly = tip_y - 16*math.cos(rad)
        c.create_text(lx+1, ly+1,
                      text=f"{hdg_deg:.0f}°  {compass_label(hdg_deg)}",
                      fill="#000000", font=("Consolas", 10, "bold"),
                      anchor=anch, tags="picker_arrow")
        c.create_text(lx, ly,
                      text=f"{hdg_deg:.0f}°  {compass_label(hdg_deg)}",
                      fill=col, font=("Consolas", 10, "bold"),
                      anchor=anch, tags="picker_arrow")
        if not locked:
            c.create_text(cx, cy + ARROW_LENGTH + 28,
                          text="move mouse to aim  ·  click to lock",
                          fill=C["muted"], font=("Consolas", 8),
                          tags="picker_arrow")

    # ── poll: redraw arrow every 100ms (survives tile-reload erasure) ──────
    def _poll():
        if not d.winfo_exists(): return
        if st["step"] in (1, 2) and st["start"] is not None:
            sc = _canvas_xy()
            if sc is not None:
                _draw_arrow(sc[0], sc[1], st["heading"],
                            locked=(st["step"] == 2))
        d.after(100, _poll)

    d.after(150, _poll)

    # ── heading update from mouse position ─────────────────────────────────
    def _aim(mx, my):
        sc = _canvas_xy()
        if sc is None: return
        dx, dy = mx - sc[0], my - sc[1]
        if abs(dx) < 1 and abs(dy) < 1: return
        st["heading"] = math.degrees(math.atan2(dx, -dy)) % 360.0
        hdg_lbl.config(
            text=f"{st['heading']:.0f}°  {compass_label(st['heading'])}")

    # ── pm.canvas click detection (coexists with native pan via add="+") ───
    def _on_press(e):
        st["press_x"] = e.x; st["press_y"] = e.y

    def _on_release(e):
        if (abs(e.x - st["press_x"]) > DRAG_THRESHOLD or
                abs(e.y - st["press_y"]) > DRAG_THRESHOLD):
            return  # was a pan — ignore
        lat, lon = canvas_to_latlon(pm, e.x, e.y)
        if lat is None: return

        if st["step"] == 0:
            st["start"] = (lat, lon)
            if st["start_marker"]:
                try: st["start_marker"].delete()
                except Exception: pass
            st["start_marker"] = pm.set_marker(
                lat, lon, text="START",
                marker_color_circle=C["green"],
                marker_color_outside="#1b5e20")
            coord_lbl.config(text=f"{lat:.6f},  {lon:.6f}")
            step_dot.config(fg=C["accent"])
            instr_var.set(
                "Move mouse to aim the arrow, then click to lock heading")
            st["step"] = 1
            st["heading"] = 0.0
            confirm_btn.config(state="normal", bg=C["orange"], fg="white")

        elif st["step"] == 1:
            _aim(e.x, e.y)
            sc = _canvas_xy()
            if sc is not None:
                _draw_arrow(sc[0], sc[1], st["heading"], locked=True)
            cmp = compass_label(st["heading"])
            step_dot.config(fg=C["green"])
            instr_var.set(
                f"Heading {st['heading']:.0f}° ({cmp})  "
                "— click to re-aim, or Confirm")
            confirm_btn.config(state="normal", bg=C["green"], fg="white")
            st["step"] = 2

        elif st["step"] == 2:
            st["step"] = 1
            step_dot.config(fg=C["accent"])
            instr_var.set("Move mouse to re-aim, then click to lock")
            confirm_btn.config(state="normal", bg=C["orange"], fg="white")

    def _on_motion(e):
        if st["step"] == 1:
            _aim(e.x, e.y)

    pm.canvas.bind("<ButtonPress-1>",   _on_press,   add="+")
    pm.canvas.bind("<ButtonRelease-1>", _on_release, add="+")
    pm.canvas.bind("<Motion>",          _on_motion,  add="+")

    d.after(100, search_entry.focus_set)
    d.wait_window()

def show_splash():
    sp = tk.Toplevel(root); sp.overrideredirect(True)
    sp.configure(bg=C["bg"])
    sw, sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w, h   = 640, 310
    sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x")
    body = tk.Frame(sp, bg=C["bg"]); body.pack(expand=True, fill="both", padx=40)
    tk.Label(body, text="ROAD SCOUT",
             font=("Consolas", 26, "bold"),
             bg=C["bg"], fg=C["accent"]).pack(pady=(22, 3))
    tk.Label(body, text="Visual Odometry GPX Estimator",
             font=("Consolas", 10), bg=C["bg"], fg=C["text"]).pack()
    tk.Label(body, text=f"{VERSION}  ·  by {AUTHOR}  ·  {datetime.now().year}",
             font=("Consolas", 8), bg=C["bg"], fg=C["muted"]).pack()
    tk.Label(body, text="derive GPS tracks from onboard video — no embedded GPS required",
             font=("Consolas", 8, "italic"), bg=C["bg"], fg=C["dim"]
             ).pack(pady=(4, 16))
    pbv = tk.DoubleVar()
    pb  = ttk.Progressbar(body, variable=pbv, maximum=100, length=560); pb.pack()
    pct = tk.Label(body, text="0%", font=("Consolas", 8),
                   bg=C["bg"], fg=C["dim"]); pct.pack(pady=4)
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")
    steps = max(20, SPLASH_SECONDS * 25)
    ivl   = max(1, int(SPLASH_SECONDS * 1000 / steps))
    def _step(i=0):
        if not sp.winfo_exists(): return
        pbv.set(i / steps * 100); pct.config(text=f"{int(i / steps * 100)}%")
        if i < steps: root.after(ivl, _step, i + 1)
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
tk.Label(tb, text="ROAD SCOUT",
         font=("Consolas", 13, "bold"),
         bg=C["bg"], fg=C["accent"]).pack(side="left")
tk.Label(tb, text="visual odometry GPX estimator",
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
# LEFT SIDEBAR  (scrollable — same Canvas pattern as GPX Ironer)
# ═══════════════════════════════════════════════════════════════════════════════
left_outer = tk.Frame(body_frame, bg=C["panel"], width=275)
left_outer.pack(side="left", fill="y", padx=(10, 0), pady=10)
left_outer.pack_propagate(False)

_left_canvas = tk.Canvas(left_outer, bg=C["panel"], highlightthickness=0)
_left_sb     = ttk.Scrollbar(left_outer, orient="vertical",
                              command=_left_canvas.yview)
_left_canvas.configure(yscrollcommand=_left_sb.set)
_left_sb.pack(side="right", fill="y")
_left_canvas.pack(side="left", fill="both", expand=True)

left = tk.Frame(_left_canvas, bg=C["panel"])
_left_win = _left_canvas.create_window((0, 0), window=left, anchor="nw")

def _on_left_frame_configure(e):
    _left_canvas.configure(scrollregion=_left_canvas.bbox("all"))

def _on_left_canvas_configure(e):
    _left_canvas.itemconfig(_left_win, width=e.width)

left.bind("<Configure>",         _on_left_frame_configure)
_left_canvas.bind("<Configure>", _on_left_canvas_configure)

# Mousewheel scrolls sidebar only when cursor is over it
def _left_mousewheel(e):
    try:
        ox = left_outer.winfo_rootx(); ow = left_outer.winfo_width()
        oy = left_outer.winfo_rooty(); oh = left_outer.winfo_height()
        if ox <= e.x_root <= ox + ow and oy <= e.y_root <= oy + oh:
            units = int(-1 * (e.delta / 120)) if e.delta else (-1 if e.num == 4 else 1)
            _left_canvas.yview_scroll(units, "units")
    except Exception:
        pass

root.bind("<MouseWheel>", _left_mousewheel, add="+")
root.bind("<Button-4>",   _left_mousewheel, add="+")
root.bind("<Button-5>",   _left_mousewheel, add="+")

# Force scrollregion after full layout is resolved
root.after(200, lambda: _left_canvas.configure(
    scrollregion=_left_canvas.bbox("all")))

# ── FILE ──────────────────────────────────────────────────────────────────────
sec_hdr(left, "FILE")
ff = tk.Frame(left, bg=C["panel"]); ff.pack(fill="x", padx=10, pady=6)
video_lbl = tk.Label(left, text="No video selected",
                      font=("Consolas", 7, "italic"),
                      bg=C["panel"], fg=C["muted"], wraplength=255, anchor="w")

def pick_video():
    p = filedialog.askopenfilename(
        title="Select onboard video",
        filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv *.MP4 *.AVI *.MOV *.MKV")])
    if p:
        video_path_var.set(p)
        video_lbl.config(text=Path(p).name)
        status_lbl.config(text=f"Loaded: {Path(p).name}")

mk_btn(ff, "📂  Select Video", C["blue"], pick_video).pack(fill="x", pady=2)
video_lbl.pack(padx=10, anchor="w")

# ── CAMERA ────────────────────────────────────────────────────────────────────
sec_hdr(left, "CAMERA")
cf = tk.Frame(left, bg=C["panel"]); cf.pack(fill="x", padx=10, pady=4)
labeled_entry(cf, "Height (m):",   cam_height_var)
labeled_entry(cf, "H-FOV (°):",    hfov_var)
labeled_entry(cf, "Sample (fps):", sample_fps_var)
labeled_entry(cf, "Smoothing:",    smoothing_var)
dim_lbl(left,
        "Measure height from lens to road surface.\n"
        "Dashcam ≈1.2–1.5m  ·  Helmet ≈1.7m\n"
        "Chest ≈1.2m  ·  Handlebar ≈1.0m\n"
        "GoPro Wide ≈122°  ·  Linear ≈86°\n"
        "Dashcam ≈120°  ·  Phone ≈75°")

# ── CALIBRATION ───────────────────────────────────────────────────────────────
sec_hdr(left, "CALIBRATION")
cal_f = tk.Frame(left, bg=C["panel"]); cal_f.pack(fill="x", padx=10, pady=4)
labeled_entry(cal_f, "Speed ×:",    speed_cal_var)
labeled_entry(cal_f, "Hdg sens.:", hdg_sensitivity_var)
dim_lbl(left,
        "Speed ×: distance multiplier.\n"
        "  1.80 = calibrated for EIS dashcams.\n"
        "Hdg sens.: 0 = heading locked (use\n"
        "  Road Snap). Try 1.0–5.0 to enable\n"
        "  turn detection from video.\n"
        "  Higher = more responsive turns.\n"
        "  Lower = smoother, less noise.")

# ── START POSITION ────────────────────────────────────────────────────────────
sec_hdr(left, "START POSITION")
pf = tk.Frame(left, bg=C["panel"]); pf.pack(fill="x", padx=10, pady=(4, 2))

pick_map_btn = mk_btn(pf, "🗺  Pick on Map", C["accent"],
                       open_map_picker, font=("Consolas", 9, "bold"))
pick_map_btn.pack(fill="x", pady=(0, 6))
pick_map_btn.config(fg="black", activeforeground="black")

labeled_entry(pf, "Latitude:",    lat_var)
labeled_entry(pf, "Longitude:",   lon_var)
labeled_entry(pf, "Heading (°):", heading_var)
dim_lbl(left, "Use 'Pick on Map' — search, click start, rotate arrow.\n"
              "Or type values directly.\n"
              "Heading: 0=N  90=E  180=S  270=W")

# ── START TIME ────────────────────────────────────────────────────────────────
sec_hdr(left, "START TIME")
tf2 = tk.Frame(left, bg=C["panel"]); tf2.pack(fill="x", padx=10, pady=4)
labeled_entry(tf2, "Date / time:", start_time_var, width=18)
dim_lbl(left, "Format: YYYY-MM-DD HH:MM:SS")

# ── SAVE TO ───────────────────────────────────────────────────────────────────
sec_hdr(left, "SAVE TO")
of = tk.Frame(left, bg=C["panel"]); of.pack(fill="x", padx=10, pady=4)
_rkw = dict(bg=C["panel"], fg=C["text"],
            activebackground=C["panel"], activeforeground=C["accent"],
            selectcolor=C["accent2"], font=("Consolas", 8),
            anchor="w", relief="flat")
tk.Radiobutton(of, text="Same folder as video",
               variable=dest_var, value=1, **_rkw).pack(fill="x", pady=1)
tk.Radiobutton(of, text="Desktop / Tracked",
               variable=dest_var, value=2, **_rkw).pack(fill="x", pady=1)
tk.Radiobutton(of, text="Select folder…",
               variable=dest_var, value=3, **_rkw).pack(fill="x", pady=1)

# ── PROCESSING ────────────────────────────────────────────────────────────────
sec_hdr(left, "PROCESSING")
ctrl = tk.Frame(left, bg=C["panel"]); ctrl.pack(fill="x", padx=10, pady=6)

start_btn = mk_btn(ctrl, "▶  Start",       C["green"],  lambda: start_processing())
start_btn.pack(fill="x", pady=2)
pause_btn = mk_btn(ctrl, "⏸  Pause",       C["orange"], lambda: toggle_pause(),
                   state="disabled")
pause_btn.pack(fill="x", pady=2)
pause_btn_ref[0] = pause_btn
stop_btn  = mk_btn(ctrl, "⏹  Stop & Save", C["red"],    lambda: request_stop(),
                   state="disabled")
stop_btn.pack(fill="x", pady=2)
dim_lbl(left, "Pause suspends frame analysis.\nStop saves whatever was tracked so far.")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT AREA
# ═══════════════════════════════════════════════════════════════════════════════
main = tk.Frame(body_frame, bg=C["bg"])
main.pack(side="left", fill="both", expand=True, padx=8, pady=10)

top_row = tk.Frame(main, bg=C["bg"])
top_row.pack(fill="both", expand=True)
top_row.grid_columnconfigure(0, weight=1)
top_row.grid_columnconfigure(1, weight=1)
top_row.grid_rowconfigure(0, weight=1)

# — Video preview ─────────────────────────────────────────────────────────────
vid_col = tk.Frame(top_row, bg=C["bg"])
vid_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
vid_col.pack_propagate(False)

vh = tk.Frame(vid_col, bg=C["bg"]); vh.pack(fill="x", pady=(0, 4))
tk.Label(vh, text="FLOW OVERLAY  ·  ROAD ZONE (amber)  ·  BORDER STRIPS (teal)",
         font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

vid_border = tk.Frame(vid_col, bg=C["accent"], padx=2, pady=2)
vid_border.pack(fill="both", expand=True)
vid_inner  = tk.Frame(vid_border, bg="black")
vid_inner.pack(fill="both", expand=True)
frame_lbl  = tk.Label(vid_inner, bg="black")
frame_lbl.pack(fill="both", expand=True)
vid_inner.bind("<Configure>", lambda e: _video_w.__setitem__(0, max(64, e.width)))

# — Live map ──────────────────────────────────────────────────────────────────
map_col = tk.Frame(top_row, bg=C["bg"])
map_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
map_col.pack_propagate(False)

mh = tk.Frame(map_col, bg=C["bg"]); mh.pack(fill="x", pady=(0, 4))
tk.Label(mh, text="LIVE TRACK MAP",
         font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

zf = tk.Frame(mh, bg=C["bg"]); zf.pack(side="right")

def toggle_autocenter():
    if autocenter_var.get():
        ac_btn.config(text="⊙  Auto-center: ON",  bg=C["accent"], fg="black")
    else:
        ac_btn.config(text="⊙  Auto-center: OFF", bg=C["dim"],    fg=C["muted"])

ac_btn = mk_btn(zf, "⊙  Auto-center: ON", C["accent"],
                lambda: (autocenter_var.set(not autocenter_var.get()),
                         toggle_autocenter()),
                font=("Consolas", 8))
ac_btn.config(fg="black")
ac_btn.pack(side="right", padx=(8, 0))

def zoom_in():
    _current_zoom[0] = min(_current_zoom[0] + 1, 19)
    map_widget.set_zoom(_current_zoom[0])

def zoom_out():
    _current_zoom[0] = max(_current_zoom[0] - 1, 2)
    map_widget.set_zoom(_current_zoom[0])

mk_btn(zf, "＋", C["panel2"], zoom_in,  font=("Consolas", 11, "bold")).pack(side="right", padx=2)
mk_btn(zf, "－", C["panel2"], zoom_out, font=("Consolas", 11, "bold")).pack(side="right", padx=2)

map_border2 = tk.Frame(map_col, bg=C["accent"], padx=2, pady=2)
map_border2.pack(fill="both", expand=True)
map_widget  = tkintermapview.TkinterMapView(map_border2, corner_radius=0)
map_widget.pack(fill="both", expand=True)
map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
map_widget.set_position(40.0, -3.7); map_widget.set_zoom(4)


# ── log panel ─────────────────────────────────────────────────────────────────
log_row = tk.Frame(main, bg=C["bg"], height=148)
log_row.pack(fill="x", pady=(8, 0))
log_row.pack_propagate(False)

lh2 = tk.Frame(log_row, bg=C["bg"]); lh2.pack(fill="x", pady=(0, 4))
tk.Label(lh2, text="PROCESSING LOG",
         font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

def _clear_log():
    log_text.config(state="normal"); log_text.delete("1.0", tk.END)
    log_text.config(state="disabled")

mk_btn(lh2, "Clear", C["dim"], _clear_log, font=("Consolas", 8)).pack(side="right")

lb3 = tk.Frame(log_row, bg=C["accent"], padx=1, pady=1)
lb3.pack(fill="both", expand=True)
li3 = tk.Frame(lb3, bg=C["panel2"]); li3.pack(fill="both", expand=True)
lsb2 = ttk.Scrollbar(li3, orient="vertical"); lsb2.pack(side="right", fill="y")
log_text = tk.Text(li3, bg=C["panel2"], fg=C["text"],
                   font=("Consolas", 8), relief="flat", borderwidth=0,
                   state="disabled", wrap="none", yscrollcommand=lsb2.set)
log_text.pack(fill="both", expand=True)
lsb2.config(command=log_text.yview)
log_text.tag_config("ok",   foreground=C["green"])
log_text.tag_config("err",  foreground=C["red"])
log_text.tag_config("info", foreground=C["accent"])


def log_append(msg, tag=""):
    ts = datetime.now().strftime("%H:%M:%S")
    log_text.config(state="normal")
    log_text.insert(tk.END, f"[{ts}]  {msg}\n", tag)
    log_text.see(tk.END)
    log_text.config(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
# STATUS BAR
# ─────────────────────────────────────────────────────────────────────────────
sb = tk.Frame(root, bg=C["panel"], height=28)
sb.pack(fill="x", side="bottom")
tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")

status_lbl = tk.Label(
    sb,
    text="Ready.  Use 'Pick on Map' to set start position and heading, then click ▶ Start.",
    font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
status_lbl.pack(side="left", padx=10, pady=3)

progress_var = tk.DoubleVar()
progress_bar = ttk.Progressbar(sb, variable=progress_var, maximum=100, length=200)
progress_bar.pack(side="left", padx=8, pady=3)

eta_lbl  = tk.Label(sb, text="", font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
eta_lbl.pack(side="left", padx=4)
spd_lbl  = tk.Label(sb, text="", font=("Consolas", 8, "bold"), bg=C["panel"], fg=C["accent"])
spd_lbl.pack(side="left", padx=(8, 0))
hdg_lbl  = tk.Label(sb, text="", font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
hdg_lbl.pack(side="left", padx=(8, 0))
dist_lbl = tk.Label(sb, text="", font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
dist_lbl.pack(side="left", padx=(8, 0))
pt_lbl   = tk.Label(sb, text="", font=("Consolas", 8, "bold"), bg=C["panel"], fg=C["accent"])
pt_lbl.pack(side="right", padx=10)


# ─────────────────────────────────────────────────────────────────────────────
# UI QUEUE PUMP
# ─────────────────────────────────────────────────────────────────────────────
def pump_ui_queue():
    try:
        while True:
            msg = ui_q.get_nowait()
            cmd = msg[0]

            if cmd == "frame":
                pil   = msg[1]
                w     = max(64, vid_inner.winfo_width() or _video_w[0])
                h     = max(1, int(w * pil.height / pil.width))
                img   = pil.resize((w, h), Image.LANCZOS)
                tkimg = ImageTk.PhotoImage(img)
                frame_lbl.config(image=tkimg)
                frame_lbl._img = tkimg

            elif cmd == "track_point":
                _, lat, lon, reset = msg
                if reset:
                    map_coords.clear()
                    for obj in (map_path_obj, map_marker):
                        if obj[0]:
                            try: obj[0].delete()
                            except Exception: pass
                            obj[0] = None
                    try:
                        map_widget.set_position(lat, lon)
                        map_widget.set_zoom(15); _current_zoom[0] = 15
                    except Exception: pass

                map_coords.append((lat, lon))
                if len(map_coords) > 1:
                    if map_path_obj[0]:
                        try: map_path_obj[0].delete()
                        except Exception: pass
                    try:
                        map_path_obj[0] = map_widget.set_path(
                            map_coords[-3000:], color=C["red"], width=2)
                    except Exception: pass

                if map_marker[0]:
                    try: map_marker[0].delete()
                    except Exception: pass
                try:
                    map_marker[0] = map_widget.set_marker(
                        lat, lon,
                        marker_color_circle=C["red"],
                        marker_color_outside="#b71c1c")
                except Exception: pass

                if autocenter_var.get():
                    try:
                        map_widget.set_position(lat, lon)
                        map_widget.set_zoom(_current_zoom[0])
                    except Exception: pass

            elif cmd == "progress":
                _, pct, eta, spd_kmh, hdg, lat, lon, dist_m, n_pts = msg
                progress_var.set(pct)
                eta_lbl.config( text=f"ETA {eta}")
                spd_lbl.config( text=f"{spd_kmh:5.1f} km/h")
                hdg_lbl.config( text=f"hdg {hdg:6.1f}°")
                dist_lbl.config(text=f"{dist_m/1000:.3f} km")
                pt_lbl.config(  text=f"{n_pts:,} pts")
                status_lbl.config(text=f"{pct}%  ·  ({lat:.6f}, {lon:.6f})")

            elif cmd == "log":
                log_append(msg[1], msg[2])

            elif cmd == "done":
                _, out_path, n_pts, dist_m = msg
                _on_processing_finished()
                progress_var.set(100)
                status_lbl.config(text=f"Done — {n_pts:,} pts · {dist_m/1000:.3f} km")
                messagebox.showinfo(
                    "Road Scout — Complete",
                    f"Track successfully written!\n\n"
                    f"  Points   : {n_pts:,}\n"
                    f"  Distance : {dist_m/1000:.3f} km\n\n"
                    f"  Saved → {Path(out_path).name}")

            elif cmd == "done_err":
                _on_processing_finished()
                progress_var.set(0)
                status_lbl.config(text="Processing failed — see log.")

    except queue.Empty:
        pass

    if proc_state["running"]:
        root.after(80, pump_ui_queue)


def _on_processing_finished():
    proc_state["running"] = False
    start_btn.config(state="normal",   bg=C["green"], fg="white")
    pause_btn.config(state="disabled", bg=C["dim"],   fg=C["muted"], text="⏸  Pause")
    stop_btn.config( state="disabled", bg=C["dim"],   fg=C["muted"])
    eta_lbl.config(text=""); spd_lbl.config(text=""); hdg_lbl.config(text="")


# ─────────────────────────────────────────────────────────────────────────────
# CONTROL CALLBACKS
# ─────────────────────────────────────────────────────────────────────────────
def validate_inputs():
    errs = []
    if not video_path_var.get() or not Path(video_path_var.get()).exists():
        errs.append("No valid video file selected.")
    for name, var in [("Latitude",      lat_var),
                      ("Longitude",     lon_var),
                      ("Heading",       heading_var),
                      ("Camera height", cam_height_var),
                      ("H-FOV",         hfov_var),
                      ("Sample fps",    sample_fps_var),
                      ("Smoothing",     smoothing_var),
                      ("Speed ×",       speed_cal_var),
                      ("Hdg sens.",     hdg_sensitivity_var)]:
        try:    float(var.get())
        except ValueError: errs.append(f"'{name}' must be a number.")
    try:
        datetime.strptime(start_time_var.get().strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        errs.append("Start time must be YYYY-MM-DD HH:MM:SS.")
    return errs


def resolve_output_path(video_path):
    stem = Path(video_path).stem
    ch   = dest_var.get()
    if ch == 1: return str(Path(video_path).with_name(stem + "_roadscout.gpx"))
    if ch == 2:
        d = Path.home() / "Desktop" / "Tracked"
        d.mkdir(parents=True, exist_ok=True)
        return str(d / (stem + "_roadscout.gpx"))
    folder = filedialog.askdirectory(title="Select output folder")
    if not folder: return None
    return str(Path(folder) / (stem + "_roadscout.gpx"))


def start_processing():
    if proc_state["running"]:
        messagebox.showinfo("Busy", "Processing is already in progress.")
        return
    errs = validate_inputs()
    if errs:
        messagebox.showerror("Input errors", "\n".join(errs))
        return
    out = resolve_output_path(video_path_var.get())
    if not out: return

    try:
        t_start = datetime.strptime(
            start_time_var.get().strip(), "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        t_start = datetime.now(timezone.utc)

    stop_ev.clear(); pause_ev.set()
    _clear_log(); progress_var.set(0)
    for lbl in (eta_lbl, spd_lbl, hdg_lbl, dist_lbl, pt_lbl):
        lbl.config(text="")
    status_lbl.config(text="Initialising…")

    start_btn.config(state="disabled", bg=C["dim"],    fg=C["muted"])
    pause_btn.config(state="normal",   bg=C["orange"], fg="white", text="⏸  Pause")
    stop_btn.config( state="normal",   bg=C["red"],    fg="white")
    proc_state["running"] = True

    kwargs = dict(
        video_path      = video_path_var.get(),
        start_lat       = float(lat_var.get()),
        start_lon       = float(lon_var.get()),
        initial_heading = float(heading_var.get()),
        cam_h_m         = float(cam_height_var.get()),
        hfov_deg        = float(hfov_var.get()),
        sample_fps      = float(sample_fps_var.get()),
        smoothing       = max(1, int(float(smoothing_var.get()))),
        speed_cal       = float(speed_cal_var.get()),
        hdg_sensitivity = float(hdg_sensitivity_var.get()),
        start_time      = t_start,
        output_gpx      = out,
        ui_queue        = ui_q,
        stop_event      = stop_ev,
        pause_event     = pause_ev,
    )
    t = threading.Thread(target=process_video, kwargs=kwargs, daemon=True)
    proc_state["thread"] = t
    t.start()
    root.after(80, pump_ui_queue)


def toggle_pause():
    if not proc_state["running"]:
        messagebox.showinfo("Pause", "No active processing.")
        return
    if pause_ev.is_set():
        pause_ev.clear()
        pause_btn.config(text="▶  Resume", bg=C["green"])
        status_lbl.config(text="Paused.")
    else:
        pause_ev.set()
        pause_btn.config(text="⏸  Pause",  bg=C["orange"])
        status_lbl.config(text="Processing…")


def request_stop():
    if not proc_state["running"]:
        messagebox.showinfo("Stop", "No active processing.")
        return
    if messagebox.askyesno("Stop & Save", "Stop processing and save the partial track?"):
        pause_ev.set(); stop_ev.set()
        status_lbl.config(text="Stopping — saving partial track…")


# ─────────────────────────────────────────────────────────────────────────────
# CLOSE HANDLER
# ─────────────────────────────────────────────────────────────────────────────
def on_close():
    if proc_state["running"]:
        if not messagebox.askyesno("Quit", "Processing is in progress. Quit anyway?"):
            return
        stop_ev.set(); pause_ev.set()
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root.mainloop()
