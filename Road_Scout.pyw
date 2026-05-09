#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Road Scout  v1.1
Author : Marco Cot
Contact: marcocot1982@gmail.com

Visual Odometry GPX Estimator.
Estimates a GPS track from any forward-facing onboard video.
No embedded GPS needed — only a known start position and camera height.

New in v1.1:
  • "Pick on Map" dialog: click once to place the start position,
    click a second time in the direction the camera is aimed to set
    the initial heading.  Both are confirmed before applying.

Scale derivation (no speed input required):
  For a camera at height h above a flat road, a road pixel at row v satisfies:
      depth  D  = fy * h / (v - cy)
  Between two frames:
      flow_y ≈ fy * h * ΔD / D²
  Solved for the forward displacement per frame step:
      ΔD = flow_y * fy * h / (v - cy)²
  Median across all valid road rows → displacement in TRUE METRES.

Heading change: Lucas-Kanade sparse tracking + Essential Matrix (RANSAC)
                → recoverPose → yaw from rotation matrix.
Border lateral flow: motion-present signal and fallback when road is hidden.
"""

import os, sys, math, time, threading, queue
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
VERSION        = "v1.1"
AUTHOR         = "Marco Cot"
CONTACT        = "marcocot1982@gmail.com"
SPLASH_SECONDS = 4

ROAD_DEPTH_MIN_M  = 2.0
ROAD_DEPTH_MAX_M  = 28.0
STOP_FLOW_THRESH  = 0.35
BORDER_STRIP_FRAC = 0.09
FLOW_ARROW_SCALE  = 3
FLOW_STEP_PX      = 32
DRAG_THRESHOLD    = 6       # px — below this a press+release is a click

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE  (matches the rest of the GPX suite)
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

# ─────────────────────────────────────────────────────────────────────────────
# WINDOW ICON  (GPS pin + road dashes, drawn with PIL)
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


def move_point(lat: float, lon: float, heading_deg: float, dist_m: float):
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


def bearing_between(lat1: float, lon1: float,
                    lat2: float, lon2: float) -> float:
    """
    True bearing (degrees, 0=N clockwise) from point 1 to point 2.
    Uses the forward azimuth formula on the spherical earth.
    """
    la1, lo1 = math.radians(lat1), math.radians(lon1)
    la2, lo2 = math.radians(lat2), math.radians(lon2)
    dlo = lo2 - lo1
    x   = math.sin(dlo) * math.cos(la2)
    y   = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def canvas_to_latlon(map_widget, cx: int, cy: int):
    """
    Convert tkintermapview canvas pixel coords to (lat, lon).
    Tries the public API first; falls back to tile-maths.
    """
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
# CAMERA MODEL
# ─────────────────────────────────────────────────────────────────────────────
def build_camera_matrix(w: int, h: int, hfov_deg: float) -> np.ndarray:
    fx = (w / 2.0) / math.tan(math.radians(hfov_deg / 2.0))
    fy = fx
    return np.array([[fx,  0, w / 2.0],
                     [ 0, fy, h / 2.0],
                     [ 0,  0,     1.0]], dtype=np.float64)


# ─────────────────────────────────────────────────────────────────────────────
# OPTICAL FLOW ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _road_row_range(cam: np.ndarray, frame_h: int, cam_h_m: float):
    fy     = cam[1, 1]
    cy     = cam[1, 2]
    v_near = int(fy * cam_h_m / ROAD_DEPTH_MIN_M + cy)
    v_far  = int(fy * cam_h_m / ROAD_DEPTH_MAX_M + cy)
    v_near = min(v_near, int(frame_h * 0.94))
    v_far  = max(v_far,  int(frame_h * 0.42))
    return v_near, v_far


def estimate_forward_displacement(flow: np.ndarray,
                                   cam: np.ndarray,
                                   cam_h_m: float) -> float:
    h_px, w_px = flow.shape[:2]
    fy   = cam[1, 1]
    cy   = cam[1, 2]
    v_near, v_far = _road_row_range(cam, h_px, cam_h_m)
    col_lo = int(w_px * 0.18)
    col_hi = int(w_px * 0.82)
    estimates = []
    for v in range(v_far, v_near, 4):
        dv = v - cy
        if dv < 2:
            continue
        row_vy   = flow[v, col_lo:col_hi, 1]
        fwd_mask = row_vy > STOP_FLOW_THRESH
        if fwd_mask.sum() < 5:
            continue
        median_vy = float(np.median(row_vy[fwd_mask]))
        D_est     = fy * cam_h_m / dv
        delta_m   = median_vy * fy * cam_h_m / (dv ** 2)
        if 0.0 < delta_m < D_est:
            estimates.append(delta_m)
    if len(estimates) < 6:
        return 0.0
    return float(np.median(estimates))


def estimate_border_activity(flow: np.ndarray, h: int, w: int) -> float:
    bw    = max(1, int(w * BORDER_STRIP_FRAC))
    r_lo  = int(h * 0.38)
    r_hi  = int(h * 0.82)
    left  = np.abs(flow[r_lo:r_hi, :bw,     0])
    right = np.abs(flow[r_lo:r_hi, w - bw:, 0])
    return float((np.median(left) + np.median(right)) / 2.0)


def estimate_heading_delta(gray1: np.ndarray, gray2: np.ndarray,
                            cam: np.ndarray,
                            prev_pts: np.ndarray = None) -> tuple:
    lk_params   = dict(winSize=(21, 21), maxLevel=3,
                       criteria=(cv2.TERM_CRITERIA_EPS |
                                  cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    feat_params = dict(maxCorners=400, qualityLevel=0.01,
                       minDistance=8, blockSize=7)

    if prev_pts is None or len(prev_pts) < 60:
        prev_pts = cv2.goodFeaturesToTrack(gray1, mask=None, **feat_params)
    if prev_pts is None or len(prev_pts) < 8:
        return 0.0, None

    next_pts, status, _ = cv2.calcOpticalFlowPyrLK(
        gray1, gray2, prev_pts, None, **lk_params)
    if next_pts is None:
        return 0.0, None

    ok = status.ravel() == 1
    if ok.sum() < 8:
        return 0.0, None

    p1, p2 = prev_pts[ok], next_pts[ok]
    E, mask_e = cv2.findEssentialMat(
        p1, p2, cam, method=cv2.RANSAC, prob=0.999, threshold=1.0)
    if E is None:
        return 0.0, p2

    _, R, _t, mask_rp = cv2.recoverPose(E, p1, p2, cam, mask=mask_e)
    yaw_deg = math.degrees(math.atan2(float(R[0, 2]), float(R[2, 2])))

    if mask_rp is not None:
        keep = mask_rp.ravel() == 255
        if keep.sum() >= 8:
            return yaw_deg, p2[keep]
    return yaw_deg, p2


# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC OVERLAY
# ─────────────────────────────────────────────────────────────────────────────
def draw_overlay(frame_bgr, flow, cam, cam_h_m, heading, speed_kmh, dist_km):
    vis    = frame_bgr.copy()
    fh, fw = vis.shape[:2]
    v_near, v_far = _road_row_range(cam, fh, cam_h_m)
    col_lo = int(fw * 0.18)
    col_hi = int(fw * 0.82)
    bw     = max(1, int(fw * BORDER_STRIP_FRAC))
    r_lo   = int(fh * 0.38)
    r_hi   = int(fh * 0.82)

    cv2.rectangle(vis, (col_lo, v_far), (col_hi, min(v_near, fh - 2)),
                  (245, 166, 35), 1)
    cv2.putText(vis, "road plane", (col_lo + 4, v_far + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.36, (245, 166, 35), 1)

    cv2.rectangle(vis, (0, r_lo),       (bw,    r_hi), (38, 166, 154), 1)
    cv2.rectangle(vis, (fw - bw, r_lo), (fw - 1, r_hi), (38, 166, 154), 1)
    cv2.putText(vis, "L", (2,          r_lo + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (38, 166, 154), 1)
    cv2.putText(vis, "R", (fw - bw + 2, r_lo + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (38, 166, 154), 1)

    step = FLOW_STEP_PX
    for vy in range(0, fh, step):
        for vx in range(0, fw, step):
            dx  = float(flow[vy, vx, 0]) * FLOW_ARROW_SCALE
            dy  = float(flow[vy, vx, 1]) * FLOW_ARROW_SCALE
            mag = math.hypot(dx, dy)
            if mag < 0.7:
                continue
            cv2.arrowedLine(vis, (vx, vy),
                            (int(vx + dx), int(vy + dy)),
                            (76, 175, 80), 1, tipLength=0.35)

    hud = (f"{speed_kmh:5.1f} km/h   "
           f"hdg {heading:6.1f}\xb0   "
           f"{dist_km:.3f} km")
    cv2.rectangle(vis, (0, fh - 22), (fw, fh), (20, 20, 20), -1)
    cv2.putText(vis, hud, (8, fh - 7),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (232, 232, 232), 1)
    return vis


# ─────────────────────────────────────────────────────────────────────────────
# GPX WRITER
# ─────────────────────────────────────────────────────────────────────────────
def write_gpx(track_pts, out_path, start_lat, start_lon, cam_h, hfov):
    gpx = gpxpy.gpx.GPX()
    gpx.name = Path(out_path).stem
    gpx.description = (
        f"Road Scout VO track · start ({start_lat:.6f},{start_lon:.6f}) "
        f"· cam height {cam_h}m · FOV {hfov}°"
    )
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

    log(f"📹  {Path(video_path).name}  —  "
        f"{w_full}×{h_full}  {vid_fps:.1f}fps  {duration_s:.0f}s")

    frame_step = max(1, int(round(vid_fps / sample_fps)))
    dt_step    = frame_step / vid_fps
    actual_fps = vid_fps / frame_step
    log(f"📐  Camera {cam_h_m}m · FOV {hfov_deg}° · "
        f"every {frame_step} frames ({actual_fps:.1f} fps effective)")

    SCALE    = 0.5
    w_ds     = max(1, int(w_full * SCALE))
    h_ds     = max(1, int(h_full * SCALE))
    cam_ds   = build_camera_matrix(w_ds, h_ds, hfov_deg)
    DISP_W   = min(w_full, 640)
    DISP_H   = max(1, int(h_full * DISP_W / w_full))
    cam_disp = build_camera_matrix(DISP_W, DISP_H, hfov_deg)

    lat, lon      = start_lat, start_lon
    heading       = initial_heading
    track_pts     = [(lat, lon, start_time)]
    total_dist    = 0.0
    prev_gray_ds  = None
    prev_pts      = None
    yaw_buf       = []
    spd_buf       = []
    wall_start    = time.time()
    frame_idx     = 0

    log("▶  Processing…", "info")
    ui_queue.put(("track_point", lat, lon, True))

    while True:
        ret, frame_bgr = cap.read()
        if not ret:
            break

        if frame_idx % frame_step != 0:
            frame_idx += 1
            continue

        while not pause_event.is_set():
            if stop_event.is_set():
                break
            time.sleep(0.08)
        if stop_event.is_set():
            log("⏹  Stopped — writing partial track…", "err")
            break

        frame_ds = cv2.resize(frame_bgr, (w_ds, h_ds),
                              interpolation=cv2.INTER_AREA)
        gray_ds  = cv2.cvtColor(frame_ds, cv2.COLOR_BGR2GRAY)

        elapsed_s  = frame_idx / vid_fps
        point_time = start_time + timedelta(seconds=elapsed_s)
        speed_ms   = 0.0
        dist_step  = 0.0

        if prev_gray_ds is not None:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray_ds, gray_ds, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0)

            disp_m = estimate_forward_displacement(flow, cam_ds, cam_h_m)
            if disp_m == 0.0:
                bact = estimate_border_activity(flow, h_ds, w_ds)
                if bact > STOP_FLOW_THRESH:
                    disp_m = bact * 8.0 / cam_ds[0, 0]

            spd_buf.append(disp_m)
            if len(spd_buf) > max(1, smoothing):
                spd_buf.pop(0)
            dist_step = float(np.median(spd_buf))
            speed_ms  = dist_step / max(dt_step, 1e-6)

            yaw_deg, prev_pts = estimate_heading_delta(
                prev_gray_ds, gray_ds, cam_ds, prev_pts)
            yaw_buf.append(yaw_deg)
            if len(yaw_buf) > max(1, smoothing):
                yaw_buf.pop(0)
            heading = (heading + float(np.mean(yaw_buf))) % 360.0

            if dist_step > 0:
                lat, lon = move_point(lat, lon, heading, dist_step)
                total_dist += dist_step

            track_pts.append((lat, lon, point_time))

            frame_disp = cv2.resize(frame_bgr, (DISP_W, DISP_H),
                                    interpolation=cv2.INTER_AREA)
            flow_disp  = cv2.resize(flow, (DISP_W, DISP_H),
                                    interpolation=cv2.INTER_AREA)
            vis = draw_overlay(frame_disp, flow_disp, cam_disp,
                               cam_h_m, heading,
                               speed_ms * 3.6, total_dist / 1000.0)
        else:
            vis = cv2.resize(frame_bgr, (DISP_W, DISP_H),
                             interpolation=cv2.INTER_AREA)

        prev_gray_ds = gray_ds

        pct     = int(100 * frame_idx / max(1, total_f))
        elapsed = time.time() - wall_start
        eta_s   = max(0, elapsed / pct * 100 - elapsed) if pct > 0 else 0
        eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_s))

        pil = Image.fromarray(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
        ui_queue.put(("frame",       pil))
        ui_queue.put(("track_point", lat, lon, False))
        ui_queue.put(("progress",    pct, eta_str,
                      speed_ms * 3.6, heading,
                      lat, lon, total_dist, len(track_pts)))
        frame_idx += 1

    cap.release()

    if len(track_pts) > 1:
        try:
            write_gpx(track_pts, output_gpx,
                      start_lat, start_lon, cam_h_m, hfov_deg)
            log(f"✅  {len(track_pts):,} points · "
                f"{total_dist/1000:.3f} km  →  {output_gpx}", "ok")
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
sty.configure("TLabel",     background=C["bg"],    foreground=C["text"],
                             font=("Consolas", 9))
sty.configure("TFrame",     background=C["bg"])
sty.configure("TScrollbar", background=C["panel2"],
                             troughcolor=C["border"], arrowcolor=C["muted"])
sty.configure("Horizontal.TProgressbar",
               background=C["accent"], troughcolor=C["panel2"],
               bordercolor=C["border"],
               lightcolor=C["accent"], darkcolor=C["accent2"])

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
start_time_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
dest_var       = tk.IntVar(value=2)
autocenter_var = tk.BooleanVar(value=True)


# ─────────────────────────────────────────────────────────────────────────────
# MAP PICKER DIALOG
# ─────────────────────────────────────────────────────────────────────────────
def open_map_picker():
    """
    Modal dialog with two-click workflow:
      Click 1 — place the START position (green marker)
      Click 2 — place the AIM point (amber marker + line from start)
                 heading = bearing(start → aim point)

    Uses ButtonPress + ButtonRelease with DRAG_THRESHOLD so panning still
    works normally and only genuine clicks trigger placement.
    """
    d = tk.Toplevel(root)
    d.title("Pick Start Position & Heading")
    d.configure(bg=C["bg"])
    d.geometry("1020x720")
    d.grab_set()
    _apply_icon(d)

    # ── state ──────────────────────────────────────────────────────────────
    ps = {
        "step":           0,       # 0 = waiting for start, 1 = waiting for aim
        "start":          None,    # (lat, lon)
        "aim":            None,    # (lat, lon)
        "heading":        None,    # float degrees
        "start_marker":   None,
        "aim_marker":     None,
        "heading_path":   None,
        "press_x":        0,
        "press_y":        0,
    }

    COMPASS = {0:"N", 22.5:"NNE", 45:"NE", 67.5:"ENE",
               90:"E", 112.5:"ESE", 135:"SE", 157.5:"SSE",
               180:"S", 202.5:"SSW", 225:"SW", 247.5:"WSW",
               270:"W", 292.5:"WNW", 315:"NW", 337.5:"NNW"}

    def compass_label(deg: float) -> str:
        nearest = min(COMPASS, key=lambda k: abs((deg - k + 180) % 360 - 180))
        return COMPASS[nearest]

    # ── top chrome ─────────────────────────────────────────────────────────
    tk.Frame(d, bg=C["accent"], height=3).pack(fill="x")
    hdr = tk.Frame(d, bg=C["bg"]); hdr.pack(fill="x", padx=16, pady=6)
    tk.Label(hdr, text="PICK START POSITION  &  HEADING",
             font=("Consolas", 11, "bold"),
             bg=C["bg"], fg=C["accent"]).pack(side="left")
    tk.Frame(d, bg=C["border"], height=1).pack(fill="x")

    # ── instruction bar ────────────────────────────────────────────────────
    instr_frame = tk.Frame(d, bg=C["panel"], height=36)
    instr_frame.pack(fill="x")
    instr_frame.pack_propagate(False)

    step_dot = tk.Label(instr_frame, text="●",
                         font=("Consolas", 11), bg=C["panel"], fg=C["green"])
    step_dot.pack(side="left", padx=(14, 6), pady=6)

    instr_var = tk.StringVar(
        value="Step 1  —  Click anywhere on the map to place the START position")
    instr_lbl = tk.Label(instr_frame, textvariable=instr_var,
                          font=("Consolas", 9), bg=C["panel"], fg=C["text"],
                          anchor="w")
    instr_lbl.pack(side="left", fill="x", expand=True)

    # ── map ────────────────────────────────────────────────────────────────
    map_border = tk.Frame(d, bg=C["accent"], padx=2, pady=2)
    map_border.pack(fill="both", expand=True, padx=10, pady=(6, 0))
    pm = tkintermapview.TkinterMapView(map_border, corner_radius=0)
    pm.pack(fill="both", expand=True)
    pm.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")

    # Try to pre-center on the current lat/lon entry values
    try:
        _init_lat = float(lat_var.get())
        _init_lon = float(lon_var.get())
        pm.set_position(_init_lat, _init_lon)
        pm.set_zoom(13)
    except ValueError:
        pm.set_position(40.0, -3.7)
        pm.set_zoom(4)

    # ── info / button bar ──────────────────────────────────────────────────
    info_bar = tk.Frame(d, bg=C["panel2"], height=44)
    info_bar.pack(fill="x", padx=10, pady=(4, 0))
    info_bar.pack_propagate(False)

    # Coordinate readout (left side)
    coord_lbl = tk.Label(info_bar, text="—",
                          font=("Consolas", 9), bg=C["panel2"], fg=C["muted"])
    coord_lbl.pack(side="left", padx=14)

    # Heading readout (centre)
    hdg_info = tk.Label(info_bar, text="",
                         font=("Consolas", 10, "bold"),
                         bg=C["panel2"], fg=C["accent"])
    hdg_info.pack(side="left", padx=20)

    # Buttons (right side)
    btn_bar = tk.Frame(info_bar, bg=C["panel2"])
    btn_bar.pack(side="right", padx=10)

    def _reset():
        ps["step"] = 0
        ps["start"] = ps["aim"] = ps["heading"] = None
        for key in ("start_marker", "aim_marker", "heading_path"):
            if ps[key]:
                try: ps[key].delete()
                except Exception: pass
                ps[key] = None
        confirm_btn.config(state="disabled", bg=C["dim"], fg=C["muted"])
        coord_lbl.config(text="—")
        hdg_info.config(text="")
        step_dot.config(fg=C["green"])
        instr_var.set(
            "Step 1  —  Click anywhere on the map to place the START position")

    reset_btn = mk_btn(btn_bar, "↺  Reset", C["dim"], _reset,
                        font=("Consolas", 8, "bold"))
    reset_btn.pack(side="left", padx=(0, 6))

    confirm_btn = mk_btn(btn_bar, "✓  Confirm & Apply", C["green"],
                          lambda: None,   # patched below
                          state="disabled", font=("Consolas", 9, "bold"))
    confirm_btn.pack(side="left", padx=(0, 6))

    mk_btn(btn_bar, "Cancel", C["dim"], d.destroy,
            font=("Consolas", 8, "bold")).pack(side="left")

    tk.Frame(d, bg=C["accent"], height=3).pack(fill="x", side="bottom")

    # ── confirm action ─────────────────────────────────────────────────────
    def _confirm():
        if ps["start"] is None:
            messagebox.showwarning("No position",
                                    "Please click a start position first.",
                                    parent=d)
            return
        slat, slon = ps["start"]
        lat_var.set(f"{slat:.7f}")
        lon_var.set(f"{slon:.7f}")
        if ps["heading"] is not None:
            heading_var.set(f"{ps['heading']:.1f}")
        status_lbl.config(
            text=f"Start set to ({slat:.6f}, {slon:.6f})  "
                 f"heading {ps['heading']:.1f}°"
                 if ps["heading"] is not None
                 else f"Start set to ({slat:.6f}, {slon:.6f})")
        d.destroy()

    confirm_btn.config(command=_confirm)

    # ── zoom buttons (float over map header) ──────────────────────────────
    def _zoom_in_picker():
        z = min(pm.zoom + 1, 19); pm.set_zoom(z)

    def _zoom_out_picker():
        z = max(pm.zoom - 1, 2); pm.set_zoom(z)

    zf2 = tk.Frame(hdr, bg=C["bg"]); zf2.pack(side="right")
    mk_btn(zf2, "＋", C["panel2"], _zoom_in_picker,
            font=("Consolas", 11, "bold")).pack(side="right", padx=2)
    mk_btn(zf2, "－", C["panel2"], _zoom_out_picker,
            font=("Consolas", 11, "bold")).pack(side="right", padx=2)

    # ── draw the heading arrow line between two points ─────────────────────
    def _draw_heading_line():
        if ps["heading_path"]:
            try: ps["heading_path"].delete()
            except Exception: pass
            ps["heading_path"] = None
        if ps["start"] and ps["aim"]:
            # Extend the line visually beyond the aim point
            slat, slon = ps["start"]
            alat, alon = ps["aim"]
            hdg = ps["heading"]
            # extend ~3× the distance for a visible arrow
            dist = math.hypot(alat - slat, alon - slon) * 111_000   # rough metres
            elat, elon = move_point(slat, slon, hdg, dist * 3)
            try:
                ps["heading_path"] = pm.set_path(
                    [(slat, slon), (elat, elon)],
                    color=C["accent"], width=3)
            except Exception:
                pass

    # ── map click handler ──────────────────────────────────────────────────
    def _handle_click(lat, lon):
        if ps["step"] == 0:
            # ── Place START marker ─────────────────────────────────────────
            ps["start"] = (lat, lon)
            if ps["start_marker"]:
                try: ps["start_marker"].delete()
                except Exception: pass
            ps["start_marker"] = pm.set_marker(
                lat, lon,
                text="START",
                marker_color_circle=C["green"],
                marker_color_outside="#1b5e20")
            coord_lbl.config(
                text=f"Start:  {lat:.7f},  {lon:.7f}")
            step_dot.config(fg=C["accent"])
            instr_var.set(
                "Step 2  —  Click in the direction the camera is aimed  "
                "(defines initial heading)")
            ps["step"] = 1
            confirm_btn.config(state="normal",
                                bg=C["orange"], fg="white")   # allow confirm with heading=0

        else:
            # ── Place AIM marker (step 1 or re-click to adjust) ────────────
            ps["aim"] = (lat, lon)
            hdg = bearing_between(ps["start"][0], ps["start"][1], lat, lon)
            ps["heading"] = hdg
            compass = compass_label(hdg)

            if ps["aim_marker"]:
                try: ps["aim_marker"].delete()
                except Exception: pass
            ps["aim_marker"] = pm.set_marker(
                lat, lon,
                text=f"→ {compass}",
                marker_color_circle=C["accent"],
                marker_color_outside=C["accent2"])

            _draw_heading_line()

            hdg_info.config(
                text=f"Heading  {hdg:.1f}°  {compass}")
            coord_lbl.config(
                text=f"Start:  {ps['start'][0]:.6f},  {ps['start'][1]:.6f}  "
                     f"│  Aim:  {lat:.6f},  {lon:.6f}")
            instr_var.set(
                f"Heading set to {hdg:.1f}° ({compass})  —  "
                "re-click to adjust aim, or Confirm")
            step_dot.config(fg=C["accent"])
            confirm_btn.config(state="normal",
                                bg=C["green"], fg="white")

    # ── click detection via press + release + drag guard ──────────────────
    # (same reliable pattern as Cache Editor)
    canvas = pm.canvas

    def _on_press(event):
        ps["press_x"] = event.x
        ps["press_y"] = event.y

    def _on_release(event):
        if (abs(event.x - ps["press_x"]) > DRAG_THRESHOLD or
                abs(event.y - ps["press_y"]) > DRAG_THRESHOLD):
            return   # was a pan drag — ignore
        lat, lon = canvas_to_latlon(pm, event.x, event.y)
        if lat is not None:
            _handle_click(lat, lon)

    canvas.bind("<ButtonPress-1>",   _on_press,   add="+")
    canvas.bind("<ButtonRelease-1>", _on_release, add="+")

    d.wait_window()


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
    tk.Label(body, text="ROAD SCOUT",
             font=("Consolas", 26, "bold"),
             bg=C["bg"], fg=C["accent"]).pack(pady=(22, 3))
    tk.Label(body, text="Visual Odometry GPX Estimator",
             font=("Consolas", 10), bg=C["bg"], fg=C["text"]).pack()
    tk.Label(body, text=f"{VERSION}  ·  by {AUTHOR}  ·  {datetime.now().year}",
             font=("Consolas", 8), bg=C["bg"], fg=C["muted"]).pack()
    tk.Label(body,
             text="derive GPS tracks from onboard video — no embedded GPS required",
             font=("Consolas", 8, "italic"),
             bg=C["bg"], fg=C["dim"]).pack(pady=(4, 16))
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
# BODY LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
body_frame = tk.Frame(root, bg=C["bg"])
body_frame.pack(fill="both", expand=True)


# ═══════════════════════════════════════════════════════════════════════════════
# LEFT SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
left = tk.Frame(body_frame, bg=C["panel"], width=265)
left.pack(side="left", fill="y", padx=(10, 0), pady=10)
left.pack_propagate(False)

# ── FILE ──────────────────────────────────────────────────────────────────────
sec_hdr(left, "FILE")
ff = tk.Frame(left, bg=C["panel"]); ff.pack(fill="x", padx=10, pady=6)

video_lbl = tk.Label(left, text="No video selected",
                      font=("Consolas", 7, "italic"),
                      bg=C["panel"], fg=C["muted"],
                      wraplength=245, anchor="w")

def pick_video():
    p = filedialog.askopenfilename(
        title="Select onboard video",
        filetypes=[("Video files",
                    "*.mp4 *.avi *.mov *.mkv *.MP4 *.AVI *.MOV *.MKV")])
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

# ── START POSITION ────────────────────────────────────────────────────────────
sec_hdr(left, "START POSITION")
pf = tk.Frame(left, bg=C["panel"]); pf.pack(fill="x", padx=10, pady=(4, 2))

# "Pick on Map" button — full width, prominent
mk_btn(pf, "🗺  Pick on Map", C["accent"],
        open_map_picker,
        font=("Consolas", 9, "bold")
        ).pack(fill="x", pady=(0, 6))
# Accent colour → black text for readability
pf.winfo_children()[0].config(fg="black", activeforeground="black")

labeled_entry(pf, "Latitude:",    lat_var)
labeled_entry(pf, "Longitude:",   lon_var)
labeled_entry(pf, "Heading (°):", heading_var)
dim_lbl(left,
        "Use 'Pick on Map' for easy placement.\n"
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

# ── PROCESSING CONTROLS ───────────────────────────────────────────────────────
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

dim_lbl(left,
        "Pause suspends frame analysis.\n"
        "Stop saves whatever was tracked so far.")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT AREA
# ═══════════════════════════════════════════════════════════════════════════════
main = tk.Frame(body_frame, bg=C["bg"])
main.pack(side="left", fill="both", expand=True, padx=8, pady=10)

# ── top row: video preview | live map ────────────────────────────────────────
top_row = tk.Frame(main, bg=C["bg"])
top_row.pack(fill="both", expand=True)
top_row.grid_columnconfigure(0, weight=1)
top_row.grid_columnconfigure(1, weight=1)
top_row.grid_rowconfigure(0, weight=1)

# — Video preview column ──────────────────────────────────────────────────────
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
vid_inner.bind("<Configure>",
               lambda e: _video_w.__setitem__(0, max(64, e.width)))

# — Live map column ───────────────────────────────────────────────────────────
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

mk_btn(zf, "＋", C["panel2"], zoom_in,
       font=("Consolas", 11, "bold")).pack(side="right", padx=2)
mk_btn(zf, "－", C["panel2"], zoom_out,
       font=("Consolas", 11, "bold")).pack(side="right", padx=2)

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
    log_text.config(state="normal")
    log_text.delete("1.0", tk.END)
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

eta_lbl  = tk.Label(sb, text="", font=("Consolas", 8),
                     bg=C["panel"], fg=C["muted"])
eta_lbl.pack(side="left", padx=4)

spd_lbl  = tk.Label(sb, text="", font=("Consolas", 8, "bold"),
                     bg=C["panel"], fg=C["accent"])
spd_lbl.pack(side="left", padx=(8, 0))

hdg_lbl  = tk.Label(sb, text="", font=("Consolas", 8),
                     bg=C["panel"], fg=C["muted"])
hdg_lbl.pack(side="left", padx=(8, 0))

dist_lbl = tk.Label(sb, text="", font=("Consolas", 8),
                     bg=C["panel"], fg=C["muted"])
dist_lbl.pack(side="left", padx=(8, 0))

pt_lbl   = tk.Label(sb, text="", font=("Consolas", 8, "bold"),
                     bg=C["panel"], fg=C["accent"])
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
                        map_widget.set_zoom(15)
                        _current_zoom[0] = 15
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
                status_lbl.config(
                    text=f"Done — {n_pts:,} pts · {dist_m/1000:.3f} km")
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
    pause_btn.config(state="disabled", bg=C["dim"],   fg=C["muted"],
                     text="⏸  Pause")
    stop_btn.config( state="disabled", bg=C["dim"],   fg=C["muted"])
    eta_lbl.config(text=""); spd_lbl.config(text="")
    hdg_lbl.config(text="")


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
                      ("Smoothing",     smoothing_var)]:
        try:
            float(var.get())
        except ValueError:
            errs.append(f"'{name}' must be a number.")
    try:
        datetime.strptime(start_time_var.get().strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        errs.append("Start time must be YYYY-MM-DD HH:MM:SS.")
    return errs


def resolve_output_path(video_path):
    stem = Path(video_path).stem
    ch   = dest_var.get()
    if ch == 1:
        return str(Path(video_path).with_name(stem + "_roadscout.gpx"))
    if ch == 2:
        d = Path.home() / "Desktop" / "Tracked"
        d.mkdir(parents=True, exist_ok=True)
        return str(d / (stem + "_roadscout.gpx"))
    folder = filedialog.askdirectory(title="Select output folder")
    if not folder:
        return None
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
    if not out:
        return

    try:
        t_start = datetime.strptime(
            start_time_var.get().strip(), "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        t_start = datetime.now(timezone.utc)

    stop_ev.clear(); pause_ev.set()
    _clear_log()
    progress_var.set(0)
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
    if messagebox.askyesno("Stop & Save",
                            "Stop processing and save the partial track?"):
        pause_ev.set()
        stop_ev.set()
        status_lbl.config(text="Stopping — saving partial track…")


# ─────────────────────────────────────────────────────────────────────────────
# CLOSE HANDLER
# ─────────────────────────────────────────────────────────────────────────────
def on_close():
    if proc_state["running"]:
        if not messagebox.askyesno(
                "Quit", "Processing is in progress. Quit anyway?"):
            return
        stop_ev.set(); pause_ev.set()
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root.mainloop()
