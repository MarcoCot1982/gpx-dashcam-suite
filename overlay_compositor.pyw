#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Overlay Compositor  v1.0
Author : Marco Cot
Contact: marcocot1982@gmail.com

Step 5 of the GPX Dashcam Suite pipeline.
Composites a GPX comment video (from Towns_video_dx) onto a dashcam base video.
Lets the user crop just the text strip, position it, scale it, and set a start offset.
"""

import os, sys, re, subprocess, threading, time, queue
from datetime import datetime, timedelta

import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageTk

VERSION        = "v1.0"
AUTHOR         = "Marco Cot"
CONTACT        = "marcocot1982@gmail.com"
SPLASH_SECONDS = 3
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))

# Suppress console window on Windows
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE  (shared across GPX Dashcam Suite)
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def mk_btn(parent, text, bg, cmd, state="normal", width=None, font=("Consolas", 9, "bold")):
    kw = dict(text=text, bg=bg,
              fg="white" if bg not in (C["dim"], C["panel2"]) else C["muted"],
              activebackground=bg, activeforeground="white",
              disabledforeground=C["dim"],
              relief="flat", cursor="hand2", command=cmd,
              font=font, pady=5, padx=8, state=state)
    if width: kw["width"] = width
    return tk.Button(parent, **kw)

def sec_hdr(parent, text):
    f = tk.Frame(parent, bg=C["panel"]); f.pack(fill="x", padx=10, pady=(12, 3))
    tk.Label(f, text=text, font=("Consolas", 8, "bold"),
             bg=C["panel"], fg=C["accent"]).pack(side="left")
    tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=10)

def mk_lbl(parent, text, fg=None, font=None):
    return tk.Label(parent, text=text,
                    bg=C["panel"], fg=fg or C["muted"],
                    font=font or ("Consolas", 8))

def mk_entry(parent, textvariable, width=14):
    return tk.Entry(parent, textvariable=textvariable, width=width,
                    bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
                    relief="flat", highlightthickness=1,
                    highlightcolor=C["accent"], highlightbackground=C["border"],
                    font=("Consolas", 9))

# ──────────────────────────────────────────────────────────────────────────────
# ICON  (GPS pin + film-strip holes — same as video_to_gpx)
# ──────────────────────────────────────────────────────────────────────────────
def _make_icon_image(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    s   = size
    pin_cx = s // 2; pin_top = int(s * 0.04); pin_r = int(s * 0.36)
    circle_bot = pin_top + pin_r * 2; pin_tip = int(s * 0.93); inner_cy = pin_top + pin_r
    sc = (120, 60, 0, 140)
    d.ellipse([pin_cx-pin_r+2, pin_top+2, pin_cx+pin_r+2, circle_bot+2], fill=sc)
    d.polygon([(pin_cx-pin_r//2+2, circle_bot+1), (pin_cx+pin_r//2+2, circle_bot+1),
               (pin_cx+2, pin_tip+2)], fill=sc)
    orange = (245, 166, 35, 255)
    d.ellipse([pin_cx-pin_r, pin_top, pin_cx+pin_r, circle_bot], fill=orange)
    d.polygon([(pin_cx-pin_r//2, circle_bot-1), (pin_cx+pin_r//2, circle_bot-1),
               (pin_cx, pin_tip)], fill=orange)
    d.ellipse([pin_cx-pin_r, pin_top, pin_cx+pin_r, circle_bot],
              outline=(180, 110, 0, 255), width=max(1, s // 32))
    hole_h = max(3, int(s * 0.09)); hole_w = max(2, int(s * 0.06))
    gap = max(2, int(s * 0.06)); strip_w = 3*hole_w + 2*gap
    sx = pin_cx - strip_w // 2; voff = max(1, s // 20); hc = (30, 15, 0, 255)
    for i in range(3):
        hx = sx + i * (hole_w + gap)
        d.rectangle([hx, inner_cy-hole_h-voff, hx+hole_w, inner_cy-voff], fill=hc)
        d.rectangle([hx, inner_cy+voff,        hx+hole_w, inner_cy+hole_h+voff], fill=hc)
    dr = max(2, int(s * 0.11))
    d.ellipse([pin_cx-dr, inner_cy-dr, pin_cx+dr, inner_cy+dr], fill=(255, 255, 255, 235))
    return img

def apply_window_icon(root):
    try:
        imgs   = [_make_icon_image(sz) for sz in (16, 24, 32, 48)]
        tk_imgs = [ImageTk.PhotoImage(im) for im in imgs]
        root._icon_refs = tk_imgs
        root.iconphoto(True, *tk_imgs)
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# VIDEO UTILITIES
# ──────────────────────────────────────────────────────────────────────────────
def video_info(path):
    """Return (width, height, fps, duration_s)."""
    cap = cv2.VideoCapture(path)
    w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    fc  = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    dur = fc / fps if fps > 0 else 0.0
    cap.release()
    return w, h, fps, dur

def read_frame_at(path, t_sec, rgba=False):
    """Read one frame from video at t_sec.
    rgba=True uses ffmpeg pipe to preserve VP9 alpha (needed for WebM overlays).
    Returns PIL RGBA image or None."""
    if rgba:
        return _read_frame_rgba_ffmpeg(path, t_sec)
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0, t_sec) * 1000)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return None
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

def _read_frame_rgba_ffmpeg(path, t_sec):
    """Extract one RGBA frame from a video using ffmpeg subprocess.
    This is the only reliable way to read VP9 alpha from WebM files."""
    try:
        w, h, fps, dur = video_info(path)
        if w == 0 or h == 0:
            return None
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{max(0, t_sec):.3f}",
            "-i", path,
            "-vframes", "1",
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "pipe:1"
        ]
        proc = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
        if proc.returncode != 0 or len(proc.stdout) < w * h * 4:
            return None
        arr = np.frombuffer(proc.stdout[:w * h * 4], dtype=np.uint8).reshape(h, w, 4)
        return Image.fromarray(arr, "RGBA")
    except Exception:
        return None

def scan_overlay_widths(path, is_webm, status_cb=None):
    """
    Sample frames every 30s throughout the overlay video and return the
    widest content bounding-box found (col_min, col_max).
    status_cb(n_done, n_total) is called on each frame for progress updates.
    Fast: only reads ~1 frame per 30s regardless of video length.
    """
    w, h, fps, dur = video_info(path)
    interval = 30.0
    times = list(np.arange(0, max(dur, 1), interval))
    if not times:
        times = [0.0]
    col_min_all = w; col_max_all = 0

    for i, t in enumerate(times):
        if is_webm:
            img = _read_frame_rgba_ffmpeg(path, t)
            if img is None:
                continue
            arr  = np.array(img.convert("RGBA"))
            mask = arr[:, :, 3] > 10
        else:
            img = read_frame_at(path, t)
            if img is None:
                continue
            arr  = np.array(img.convert("RGBA"))
            mask = np.any(arr[:, :, :3] > 20, axis=2)

        cols = np.any(mask, axis=0)
        if cols.any():
            col_min = int(np.argmax(cols))
            col_max = int(len(cols) - 1 - np.argmax(cols[::-1]))
            col_min_all = min(col_min_all, col_min)
            col_max_all = max(col_max_all, col_max)

        if status_cb:
            status_cb(i + 1, len(times))

    return col_min_all, col_max_all

def parse_hms(s):
    """HH:MM:SS or raw seconds string → float seconds."""
    try:
        parts = s.strip().split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(s)
    except Exception:
        return 0.0

def composite_frames(base_img, ov_img, crop, position_xy, scale_pct):
    """
    Alpha-composite (cropped + scaled) ov_img onto a copy of base_img.
    crop = (cx, cy, cw, ch) in overlay pixels — None for no crop.
    Returns PIL RGB Image.
    """
    result = base_img.copy().convert("RGBA")
    ov     = ov_img.convert("RGBA")

    if crop:
        cx, cy, cw, ch = crop
        if cw > 0 and ch > 0:
            ov = ov.crop((cx, cy, cx + cw, cy + ch))

    if scale_pct != 100:
        nw = max(2, int(ov.width  * scale_pct / 100))
        nh = max(2, int(ov.height * scale_pct / 100))
        ov = ov.resize((nw, nh), Image.LANCZOS)

    ox, oy = int(position_xy[0]), int(position_xy[1])
    result.paste(ov, (ox, oy), ov)
    return result.convert("RGB")

# ──────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ──────────────────────────────────────────────────────────────────────────────
_POS_LABELS = [
    ("↖", "top-left"),  ("↑", "top-center"),  ("↗", "top-right"),
    ("←", "mid-left"),  ("·", "center"),       ("→", "mid-right"),
    ("↙", "bot-left"),  ("↓", "bot-center"),   ("↘", "bot-right"),
]

class CompositorApp:
    def __init__(self, root):
        self.root = root
        root.title(f"GPX Overlay Compositor  {VERSION}")
        apply_window_icon(root)
        root.configure(bg=C["bg"])
        try:    root.state("zoomed")
        except: root.geometry("1440x860")
        root.resizable(True, True)

        # ── state ────────────────────────────────────────────────────────────
        self.base_path      = None
        self.overlay_path   = None
        self.base_info      = None   # (w, h, fps, dur)
        self.overlay_info   = None
        self._base_frame    = None   # PIL RGB, first frame of base
        self._ov_frame      = None   # PIL RGB, first frame of overlay
        self.crop           = None   # (cx, cy, cw, ch) in overlay pixels, or None

        # crop-drag state
        self._crop_drag_start  = None
        self._crop_rect_id     = None
        self._ov_canvas_scale  = 1.0
        self._ov_canvas_offset = (0, 0)

        # drag-to-position state (on composite preview canvas)
        self._comp_drag_active  = False
        self._comp_drag_last    = None   # (canvas_x, canvas_y) of last mouse event
        self._comp_canvas_scale  = 1.0   # video-pixel → canvas-pixel ratio
        self._comp_canvas_offset = (0, 0)

        # render
        self._render_proc   = None
        self._stop_flag     = threading.Event()
        self._ui_queue      = queue.Queue()

        # ttk style
        sty = ttk.Style(root); sty.theme_use("clam")
        sty.configure(".",          background=C["bg"],    foreground=C["text"])
        sty.configure("TLabel",     background=C["bg"],    foreground=C["text"], font=("Consolas", 9))
        sty.configure("TFrame",     background=C["bg"])
        sty.configure("TScrollbar", background=C["panel2"], troughcolor=C["border"],
                                    arrowcolor=C["muted"])
        sty.configure("Horizontal.TProgressbar",
                       background=C["accent"], troughcolor=C["panel2"],
                       bordercolor=C["border"], lightcolor=C["accent"],
                       darkcolor=C["accent2"])

        self._build_ui()
        self.root.after(80, self._pump_queue)

    # ── BUILD UI ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        tk.Frame(self.root, bg=C["accent"], height=3).pack(fill="x")
        tb = tk.Frame(self.root, bg=C["bg"]); tb.pack(fill="x", padx=16, pady=5)
        tk.Label(tb, text="GPX OVERLAY COMPOSITOR",
                 font=("Consolas", 13, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        tk.Label(tb, text=f"{VERSION}  ·  {AUTHOR}  ·  2025–{datetime.now().year}",
                 font=("Consolas", 8), bg=C["bg"], fg=C["dim"]).pack(side="right")
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self.root, bg=C["bg"]); body.pack(fill="both", expand=True)

        # ── LEFT SIDEBAR ─────────────────────────────────────────────────────
        left = tk.Frame(body, bg=C["panel"], width=268)
        left.pack(side="left", fill="y", padx=(10, 0), pady=10)
        left.pack_propagate(False)

        # — Files ——————————————————————————————————————————————————————————————
        sec_hdr(left, "FILES")
        ff = tk.Frame(left, bg=C["panel"]); ff.pack(fill="x", padx=10, pady=6)
        mk_btn(ff, "📹  Base (Dashcam) Video",    C["blue"],  self.select_base).pack(fill="x", pady=2)
        self._base_lbl = mk_lbl(ff, "No file selected", fg=C["dim"]); self._base_lbl.pack(anchor="w", pady=(0,4))
        mk_btn(ff, "🎞  Overlay (Comment) Video", C["blue"],  self.select_overlay).pack(fill="x", pady=2)
        self._ov_lbl   = mk_lbl(ff, "No file selected", fg=C["dim"]); self._ov_lbl.pack(anchor="w")

        # — Crop ———————————————————————————————————————————————————————————————
        sec_hdr(left, "OVERLAY CROP")
        cf = tk.Frame(left, bg=C["panel"]); cf.pack(fill="x", padx=10, pady=6)
        mk_lbl(cf, "Click & drag on the right panel →").pack(anchor="w", pady=(0, 4))
        cr2 = tk.Frame(cf, bg=C["panel"]); cr2.pack(fill="x", pady=(0, 2))
        self._autocrop_btn = mk_btn(cr2, "⚡ Auto-crop to text", C["orange"],
               self._auto_crop, font=("Consolas", 8, "bold"))
        self._autocrop_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))
        mk_btn(cr2, "✕ Reset", C["dim"],
               self.reset_crop, font=("Consolas", 8, "bold")).pack(side="left")
        self._crop_lbl = mk_lbl(cf, "Full frame — no crop active", fg=C["muted"])
        self._crop_lbl.pack(anchor="w", pady=(4, 0))

        # — Scale ——————————————————————————————————————————————————————————————
        sec_hdr(left, "SCALE OVERLAY  (%)")
        sf = tk.Frame(left, bg=C["panel"]); sf.pack(fill="x", padx=10, pady=6)
        self._scale_var = tk.IntVar(value=100)
        self._scale_slider = tk.Scale(
            sf, from_=25, to=200, orient="horizontal",
            variable=self._scale_var, bg=C["panel"], fg=C["text"],
            activebackground=C["accent"], troughcolor=C["panel2"],
            highlightthickness=0, bd=0, font=("Consolas", 8),
            command=lambda _: self._refresh_composite())
        self._scale_slider.pack(fill="x")
        self._scale_lbl = mk_lbl(sf, "100%", fg=C["accent"]); self._scale_lbl.pack(anchor="w")
        self._scale_var.trace_add("write",
            lambda *_: self._scale_lbl.config(text=f"{self._scale_var.get()}%"))

        # — Position ——————————————————————————————————————————————————————————
        sec_hdr(left, "POSITION ON BASE VIDEO")
        pf = tk.Frame(left, bg=C["panel"]); pf.pack(fill="x", padx=10, pady=6)
        self._pos_var = tk.StringVar(value="bot-center")
        grid_f = tk.Frame(pf, bg=C["panel"]); grid_f.pack()
        self._pos_btns = {}
        for idx, (sym, val) in enumerate(_POS_LABELS):
            r, c = divmod(idx, 3)
            b = tk.Button(grid_f, text=sym, width=3,
                          bg=C["accent"] if val == "bot-center" else C["panel2"],
                          fg="black" if val == "bot-center" else C["text"],
                          relief="flat", font=("Consolas", 10, "bold"),
                          command=lambda v=val: self._set_pos(v))
            b.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            self._pos_btns[val] = b

        # drag-to-position toggle — drag the overlay on the composite preview
        drag_row = tk.Frame(pf, bg=C["panel"]); drag_row.pack(fill="x", pady=(6, 0))
        self._drag_pos_btn = mk_btn(drag_row, "✋  Drag to position: OFF", C["dim"],
                                     self._toggle_drag_pos, font=("Consolas", 8, "bold"))
        self._drag_pos_btn.pack(fill="x")
        mk_lbl(pf, "drag overlay on composite preview ↑").pack(anchor="w", pady=(2, 0))

        cxy = tk.Frame(pf, bg=C["panel"]); cxy.pack(fill="x", pady=(6, 0))
        mk_lbl(cxy, "X:").pack(side="left")
        self._pos_x_var = tk.StringVar()
        mk_entry(cxy, self._pos_x_var, width=6).pack(side="left", padx=(2, 6))
        mk_lbl(cxy, "Y:").pack(side="left")
        self._pos_y_var = tk.StringVar()
        mk_entry(cxy, self._pos_y_var, width=6).pack(side="left", padx=2)
        mk_lbl(cxy, "(grid sets preset)").pack(side="left", padx=4)
        self._pos_x_var.trace_add("write", lambda *_: self._refresh_composite())
        self._pos_y_var.trace_add("write", lambda *_: self._refresh_composite())

        # — Timing ——————————————————————————————————————————————————————————————
        sec_hdr(left, "TIMING")
        tf2 = tk.Frame(left, bg=C["panel"]); tf2.pack(fill="x", padx=10, pady=6)

        mk_lbl(tf2, "Overlay starts at (HH:MM:SS):").pack(anchor="w")
        self._offset_var = tk.StringVar(value="00:00:00")
        mk_entry(tf2, self._offset_var, width=14).pack(anchor="w", pady=(2, 6))

        mk_lbl(tf2, "Base video output range:").pack(anchor="w")
        br2 = tk.Frame(tf2, bg=C["panel"]); br2.pack(fill="x", pady=(2, 0))
        mk_lbl(br2, "From:").pack(side="left")
        self._base_start_var = tk.StringVar(value="00:00:00")
        mk_entry(br2, self._base_start_var, width=9).pack(side="left", padx=(2, 6))
        mk_lbl(br2, "To:").pack(side="left")
        self._base_end_var = tk.StringVar(value="")
        mk_entry(br2, self._base_end_var, width=9).pack(side="left", padx=2)
        mk_lbl(tf2, "blank To = full duration", fg=C["dim"]).pack(anchor="w", pady=(2, 6))

        mk_lbl(tf2, "When range is active:").pack(anchor="w")
        self._range_mode_var = tk.IntVar(value=1)
        _rkw2 = dict(bg=C["panel"], fg=C["text"],
                     activebackground=C["panel"], activeforeground=C["accent"],
                     selectcolor=C["accent2"], font=("Consolas", 8),
                     anchor="w", relief="flat")
        tk.Radiobutton(tf2, text="Full video  (label only in range)",
                       variable=self._range_mode_var, value=1, **_rkw2).pack(fill="x", pady=1)
        tk.Radiobutton(tf2, text="Trimmed  (labeled section only)",
                       variable=self._range_mode_var, value=2, **_rkw2).pack(fill="x", pady=1)

        # — Output —————————————————————————————————————————————————————————————
        sec_hdr(left, "OUTPUT")
        of = tk.Frame(left, bg=C["panel"]); of.pack(fill="x", padx=10, pady=6)
        self._dest_var = tk.IntVar(value=2)
        _rkw = dict(bg=C["panel"], fg=C["text"],
                    activebackground=C["panel"], activeforeground=C["accent"],
                    selectcolor=C["accent2"], font=("Consolas", 8),
                    anchor="w", relief="flat")
        tk.Radiobutton(of, text="Same folder as base video",
                       variable=self._dest_var, value=1, **_rkw).pack(fill="x", pady=1)
        tk.Radiobutton(of, text="Desktop / Composited",
                       variable=self._dest_var, value=2, **_rkw).pack(fill="x", pady=1)

        # — Render —————————————————————————————————————————————————————————————
        sec_hdr(left, "RENDER")
        rf = tk.Frame(left, bg=C["panel"]); rf.pack(fill="x", padx=10, pady=6)
        self._render_btn = mk_btn(rf, "▶  Start Render", C["green"], self.start_render)
        self._render_btn.pack(fill="x", pady=2)
        self._stop_btn   = mk_btn(rf, "⏹  Stop",         C["red"],   self.stop_render, state="disabled")
        self._stop_btn.pack(fill="x", pady=2)

        # ── MAIN CONTENT ─────────────────────────────────────────────────────
        main = tk.Frame(body, bg=C["bg"])
        main.pack(side="left", fill="both", expand=True, padx=8, pady=10)

        # top row: composite preview | overlay crop selector
        top = tk.Frame(main, bg=C["bg"]); top.pack(fill="both", expand=True)
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=1)
        top.grid_rowconfigure(0, weight=1)

        # composite preview
        left_col = tk.Frame(top, bg=C["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        lh = tk.Frame(left_col, bg=C["bg"]); lh.pack(fill="x", pady=(0, 4))
        tk.Label(lh, text="COMPOSITE PREVIEW  —  enable drag to reposition overlay",
                 font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        base_border = tk.Frame(left_col, bg=C["accent"], padx=2, pady=2)
        base_border.pack(fill="both", expand=True)
        self._comp_canvas = tk.Canvas(base_border, bg="black", highlightthickness=0)
        self._comp_canvas.pack(fill="both", expand=True)
        self._comp_canvas.bind("<Configure>",      lambda e: self._refresh_composite())
        self._comp_canvas.bind("<ButtonPress-1>",   self._drag_pos_press)
        self._comp_canvas.bind("<B1-Motion>",       self._drag_pos_motion)
        self._comp_canvas.bind("<ButtonRelease-1>", self._drag_pos_release)

        # overlay crop selector
        right_col = tk.Frame(top, bg=C["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        rh = tk.Frame(right_col, bg=C["bg"]); rh.pack(fill="x", pady=(0, 4))
        tk.Label(rh, text="OVERLAY PREVIEW  —  drag to select crop area",
                 font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        ov_border = tk.Frame(right_col, bg=C["accent"], padx=2, pady=2)
        ov_border.pack(fill="both", expand=True)
        self._ov_canvas = tk.Canvas(ov_border, bg="#0a0a0a",
                                     cursor="crosshair", highlightthickness=0)
        self._ov_canvas.pack(fill="both", expand=True)
        self._ov_canvas.bind("<ButtonPress-1>",   self._crop_press)
        self._ov_canvas.bind("<B1-Motion>",       self._crop_drag)
        self._ov_canvas.bind("<ButtonRelease-1>", self._crop_release)
        self._ov_canvas.bind("<Configure>",       lambda e: self._redraw_ov_canvas())

        # ── CURRENT TEXT STRIP ────────────────────────────────────────────────
        # Shows the cropped overlay portion — makes the text being added visible
        ct_outer = tk.Frame(main, bg=C["accent"], padx=2, pady=2)
        ct_outer.pack(fill="x", pady=(8, 4))
        ct_inner = tk.Frame(ct_outer, bg=C["panel"]); ct_inner.pack(fill="x")
        ct_hdr   = tk.Frame(ct_inner, bg=C["panel"]); ct_hdr.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(ct_hdr, text="CURRENT OVERLAY TEXT  (what is being composited right now)",
                 font=("Consolas", 7, "bold"), bg=C["panel"], fg=C["muted"]).pack(side="left")
        self._text_canvas = tk.Canvas(ct_inner, bg=C["panel2"],
                                       height=72, highlightthickness=0)
        self._text_canvas.pack(fill="x", padx=6, pady=4)
        self._text_canvas.bind("<Configure>", lambda e: self._redraw_text_canvas())
        self._text_frame_pil = None  # PIL image to display in strip

        # ── LOG ───────────────────────────────────────────────────────────────
        log_row = tk.Frame(main, bg=C["bg"], height=120)
        log_row.pack(fill="x", pady=(2, 0))
        log_row.pack_propagate(False)
        lh2 = tk.Frame(log_row, bg=C["bg"]); lh2.pack(fill="x", pady=(0, 4))
        tk.Label(lh2, text="RENDER LOG",
                 font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        log_border = tk.Frame(log_row, bg=C["accent"], padx=1, pady=1)
        log_border.pack(fill="both", expand=True)
        log_inner = tk.Frame(log_border, bg=C["panel2"]); log_inner.pack(fill="both", expand=True)
        self._log = scrolledtext.ScrolledText(
            log_inner, bg=C["panel2"], fg=C["text"],
            insertbackground=C["text"], font=("Consolas", 8),
            state="disabled", relief="flat", borderwidth=0)
        self._log.pack(fill="both", expand=True)

        # ── STATUS BAR ───────────────────────────────────────────────────────
        sb = tk.Frame(self.root, bg=C["panel"], height=28)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        self._status_lbl = tk.Label(
            sb, text="Select a base video and an overlay video to begin.",
            font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
        self._status_lbl.pack(side="left", padx=10, pady=3)
        self._progress_var = tk.DoubleVar()
        self._prog_bar = ttk.Progressbar(
            sb, variable=self._progress_var, maximum=100, length=320)
        self._prog_bar.pack(side="left", padx=8, pady=3)
        self._eta_lbl = tk.Label(sb, text="", font=("Consolas", 8),
                                  bg=C["panel"], fg=C["muted"])
        self._eta_lbl.pack(side="left", padx=4)

    # ── POSITION GRID ─────────────────────────────────────────────────────────
    def _set_pos(self, val):
        self._pos_var.set(val)
        for v, btn in self._pos_btns.items():
            btn.config(bg=C["accent"] if v == val else C["panel2"],
                       fg="black"    if v == val else C["text"])
        self._refresh_composite()

    def _compute_overlay_xy(self):
        """Return (ox, oy) in base-video pixels for current position setting."""
        bw = self.base_info[0]  if self.base_info  else 1280
        bh = self.base_info[1]  if self.base_info  else 720
        ow, oh = self._cropped_ov_size()
        sc = self._scale_var.get() / 100
        ow = int(ow * sc); oh = int(oh * sc)
        margin = 10
        # custom X/Y overrides grid
        try:
            return (int(self._pos_x_var.get()), int(self._pos_y_var.get()))
        except Exception:
            pass
        table = {
            "top-left":   (margin,         margin),
            "top-center": ((bw-ow)//2,     margin),
            "top-right":  (bw-ow-margin,   margin),
            "mid-left":   (margin,         (bh-oh)//2),
            "center":     ((bw-ow)//2,     (bh-oh)//2),
            "mid-right":  (bw-ow-margin,   (bh-oh)//2),
            "bot-left":   (margin,         bh-oh-margin),
            "bot-center": ((bw-ow)//2,     bh-oh-margin),
            "bot-right":  (bw-ow-margin,   bh-oh-margin),
        }
        return table.get(self._pos_var.get(), ((bw-ow)//2, bh-oh-margin))

    def _cropped_ov_size(self):
        if self._ov_frame is None: return (320, 60)
        if self.crop:
            cx, cy, cw, ch = self.crop
            return (cw, ch)
        return (self._ov_frame.width, self._ov_frame.height)

    # ── OVERLAY CANVAS + CROP DRAG ────────────────────────────────────────────
    def _redraw_ov_canvas(self):
        if self._ov_frame is None: return
        c  = self._ov_canvas
        cw = c.winfo_width(); ch = c.winfo_height()
        if cw < 4 or ch < 4: return
        # Composite overlay onto a dark background so transparency shows correctly
        ov   = self._ov_frame.convert("RGBA")
        bg   = Image.new("RGBA", ov.size, (20, 20, 20, 255))
        bg.paste(ov, (0, 0), ov)
        img  = bg.convert("RGB")
        scale = min(cw / img.width, ch / img.height)
        nw    = int(img.width * scale); nh = int(img.height * scale)
        ox    = (cw - nw) // 2; oy = (ch - nh) // 2
        self._ov_canvas_scale  = scale
        self._ov_canvas_offset = (ox, oy)
        img = img.resize((nw, nh), Image.LANCZOS)
        self._ov_tk = ImageTk.PhotoImage(img)
        c.delete("all")
        c.create_image(ox, oy, anchor="nw", image=self._ov_tk)
        if self.crop:
            self._draw_crop_rect_on_canvas()

    def _draw_crop_rect_on_canvas(self):
        if not self.crop: return
        cx, cy, cw, ch = self.crop
        sc = self._ov_canvas_scale; ox, oy = self._ov_canvas_offset
        x1 = ox + cx * sc; y1 = oy + cy * sc
        x2 = x1 + cw * sc; y2 = y1 + ch * sc
        if self._crop_rect_id:
            self._ov_canvas.delete(self._crop_rect_id)
        self._crop_rect_id = self._ov_canvas.create_rectangle(
            x1, y1, x2, y2, outline=C["accent"], width=2, dash=(5, 3))

    def _canvas_to_vid(self, cx, cy):
        ox, oy = self._ov_canvas_offset; sc = self._ov_canvas_scale
        vx = max(0, (cx - ox) / sc); vy = max(0, (cy - oy) / sc)
        if self._ov_frame:
            vx = min(vx, self._ov_frame.width)
            vy = min(vy, self._ov_frame.height)
        return int(vx), int(vy)

    def _crop_press(self, event):
        self._crop_drag_start = (event.x, event.y)
        if self._crop_rect_id:
            self._ov_canvas.delete(self._crop_rect_id)
            self._crop_rect_id = None

    def _crop_drag(self, event):
        if not self._crop_drag_start: return
        x0, y0 = self._crop_drag_start
        if self._crop_rect_id:
            self._ov_canvas.delete(self._crop_rect_id)
        self._crop_rect_id = self._ov_canvas.create_rectangle(
            x0, y0, event.x, event.y,
            outline=C["accent"], width=2, dash=(5, 3))

    def _crop_release(self, event):
        if not self._crop_drag_start: return
        x0, y0 = self._crop_drag_start
        self._crop_drag_start = None
        if abs(event.x - x0) < 5 or abs(event.y - y0) < 5:
            return
        vx0, vy0 = self._canvas_to_vid(min(x0, event.x), min(y0, event.y))
        vx1, vy1 = self._canvas_to_vid(max(x0, event.x), max(y0, event.y))
        cw = vx1 - vx0; ch = vy1 - vy0
        if cw < 2 or ch < 2: return
        self.crop = (vx0, vy0, cw, ch)
        self._crop_lbl.config(text=f"x={vx0}  y={vy0}  w={cw}  h={ch}",
                               fg=C["accent"])
        self._draw_crop_rect_on_canvas()
        self._update_text_strip(self._ov_frame)
        self._refresh_composite()

    def reset_crop(self):
        self.crop = None
        if self._crop_rect_id:
            self._ov_canvas.delete(self._crop_rect_id)
            self._crop_rect_id = None
        self._crop_lbl.config(text="Full frame — no crop active", fg=C["muted"])
        self._update_text_strip(self._ov_frame)
        self._refresh_composite()

    # ── TEXT STRIP ────────────────────────────────────────────────────────────
    def _update_text_strip(self, ov_pil):
        """Extract the crop from ov_pil and display it in the text strip canvas."""
        self._text_frame_pil = ov_pil
        self._redraw_text_canvas()

    def _redraw_text_canvas(self):
        c = self._text_canvas
        cw = c.winfo_width(); ch = c.winfo_height()
        if cw < 4 or ch < 4 or self._text_frame_pil is None: return
        img = self._text_frame_pil.convert("RGBA")
        if self.crop:
            cx, cy, cw2, ch2 = self.crop
            if cw2 > 0 and ch2 > 0:
                img = img.crop((cx, cy, cx + cw2, cy + ch2))
        # composite on dark background so transparency is visible
        bg = Image.new("RGBA", img.size, (20, 20, 20, 255))
        bg.paste(img, (0, 0), img)
        img = bg.convert("RGB")
        # scale to fit strip height, keep aspect
        scale = ch / img.height
        nw    = min(cw, int(img.width * scale))
        nh    = ch
        img   = img.resize((nw, nh), Image.LANCZOS)
        self._text_tk = ImageTk.PhotoImage(img)
        c.delete("all")
        c.create_image((cw - nw) // 2, 0, anchor="nw", image=self._text_tk)

    # ── COMPOSITE PREVIEW ─────────────────────────────────────────────────────
    def _refresh_composite(self, *_):
        if self._base_frame is None or self._ov_frame is None: return
        try:
            ox, oy  = self._compute_overlay_xy()
            comp    = composite_frames(self._base_frame, self._ov_frame,
                                       self.crop, (ox, oy), self._scale_var.get())
            c       = self._comp_canvas
            cw      = c.winfo_width(); ch = c.winfo_height()
            if cw < 4 or ch < 4: return
            scale   = min(cw / comp.width, ch / comp.height)
            nw      = int(comp.width * scale); nh = int(comp.height * scale)
            img_ox  = (cw - nw) // 2;         img_oy = (ch - nh) // 2
            # store for drag-to-position coordinate conversion
            self._comp_canvas_scale  = scale
            self._comp_canvas_offset = (img_ox, img_oy)
            thumb   = comp.resize((nw, nh), Image.LANCZOS)
            self._comp_tk = ImageTk.PhotoImage(thumb)
            c.delete("all")
            c.create_image(img_ox, img_oy, anchor="nw", image=self._comp_tk)
        except Exception:
            pass

    # ── FILE SELECTION ────────────────────────────────────────────────────────
    def select_base(self):
        p = filedialog.askopenfilename(
            title="Select base (dashcam) video",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv")])
        if not p: return
        self.base_path  = p
        self.base_info  = video_info(p)
        self._base_frame = read_frame_at(p, 0)
        self._base_lbl.config(
            text=f"{os.path.basename(p)}  ({self.base_info[0]}×{self.base_info[1]})",
            fg=C["text"])
        self._set_status(f"Base: {os.path.basename(p)}  ·  {self.base_info[3]:.0f}s")
        self.root.after(100, self._refresh_composite)

    def select_overlay(self):
        p = filedialog.askopenfilename(
            title="Select overlay (GPX comment) video",
            filetypes=[("Video files", "*.mp4 *.webm *.avi")])
        if not p: return
        self.overlay_path  = p
        self.overlay_info  = video_info(p)
        is_webm = p.lower().endswith(".webm")
        # Use ffmpeg for WebM to preserve VP9 alpha; OpenCV strips it
        self._ov_frame = read_frame_at(p, 0, rgba=is_webm)
        if self._ov_frame is None:
            self._ov_frame = read_frame_at(p, 0, rgba=False)
        self.crop = None
        self._crop_lbl.config(text="Full frame — no crop active", fg=C["muted"])
        self._ov_lbl.config(
            text=f"{os.path.basename(p)}  ({self.overlay_info[0]}×{self.overlay_info[1]})",
            fg=C["text"])
        self._set_status(f"Overlay: {os.path.basename(p)}  ·  {self.overlay_info[3]:.0f}s")
        self.root.after(100, self._redraw_ov_canvas)
        self.root.after(120, lambda: self._update_text_strip(self._ov_frame))
        self.root.after(140, self._refresh_composite)

    # ── RENDER ────────────────────────────────────────────────────────────────
    def _resolve_output_dir(self):
        if self._dest_var.get() == 1:
            return os.path.dirname(self.base_path)
        d = os.path.join(os.path.expanduser("~"), "Desktop", "Composited")
        os.makedirs(d, exist_ok=True)
        return d

    def _build_ffmpeg_cmd(self, output_path):
        offset_s      = parse_hms(self._offset_var.get())
        base_start_s  = parse_hms(self._base_start_var.get())
        base_end_raw  = self._base_end_var.get().strip()
        base_end_s    = parse_hms(base_end_raw) if base_end_raw else None
        range_mode    = self._range_mode_var.get()   # 1=full, 2=trimmed

        # crop parameters in overlay pixels
        if self.crop:
            vcx, vcy, vcw, vch = self.crop
        else:
            vcx, vcy = 0, 0
            vcw, vch = self.overlay_info[0], self.overlay_info[1]

        # scale (must be even integers for libx264)
        sc  = self._scale_var.get() / 100
        sw  = max(2, int(vcw * sc)) & ~1
        sh  = max(2, int(vch * sc)) & ~1

        # position on base video
        ox, oy = self._compute_overlay_xy()
        if self.base_info:
            ox = max(0, min(ox, self.base_info[0] - sw))
            oy = max(0, min(oy, self.base_info[1] - sh))

        # alpha handling
        is_webm = self.overlay_path.lower().endswith(".webm")
        fmt_opt = "format=auto" if is_webm else "format=rgb"
        crop_f  = f"crop={vcw}:{vch}:{vcx}:{vcy}"
        scale_f = f"scale={sw}:{sh},format=rgba" if is_webm else f"scale={sw}:{sh}"

        cmd = ["ffmpeg", "-y"]

        if range_mode == 2:
            # ── TRIMMED MODE ──────────────────────────────────────────────────
            # Output only the range [base_start_s, base_end_s] of the base video.
            # Adjust overlay offset relative to the trimmed clip start.
            if base_start_s > 0:
                cmd += ["-ss", f"{base_start_s:.3f}"]
            cmd += ["-i", self.base_path]
            if base_end_s is not None:
                cmd += ["-to", f"{base_end_s - base_start_s:.3f}"]

            # Effective overlay offset within the trimmed clip
            eff_offset = offset_s - base_start_s
            if eff_offset >= 0:
                # overlay starts after clip start — delay it
                if eff_offset > 0:
                    cmd += ["-itsoffset", f"{eff_offset:.3f}"]
                cmd += ["-i", self.overlay_path]
            else:
                # overlay started before trim point — skip into it
                cmd += ["-ss", f"{-eff_offset:.3f}", "-i", self.overlay_path]

            filter_complex = (
                f"[1:v]{crop_f},{scale_f}[ov];"
                f"[0:v][ov]overlay={ox}:{oy}:{fmt_opt}[out]"
            )

        else:
            # ── FULL VIDEO MODE ───────────────────────────────────────────────
            # Output the full base video; overlay is visible only within its
            # natural window. If a range is set, restrict visibility with enable.
            cmd += ["-i", self.base_path]
            if offset_s > 0:
                cmd += ["-itsoffset", f"{offset_s:.3f}"]
            cmd += ["-i", self.overlay_path]

            ov_dur = self.overlay_info[3] if self.overlay_info else 0
            en_start = offset_s
            en_end   = offset_s + ov_dur
            # further restrict to the user-supplied range if set
            if base_start_s > 0:
                en_start = max(en_start, base_start_s)
            if base_end_s is not None:
                en_end   = min(en_end, base_end_s)

            # Only add enable expression if there is an actual restriction
            needs_enable = (base_start_s > 0 or base_end_s is not None
                            or offset_s > 0)
            if needs_enable:
                # escape commas so ffmpeg doesn't split the filter at them
                enable_expr = f"enable='between(t\\,{en_start:.3f}\\,{en_end:.3f})'"
                filter_complex = (
                    f"[1:v]{crop_f},{scale_f}[ov];"
                    f"[0:v][ov]overlay={ox}:{oy}:{fmt_opt}:{enable_expr}[out]"
                )
            else:
                filter_complex = (
                    f"[1:v]{crop_f},{scale_f}[ov];"
                    f"[0:v][ov]overlay={ox}:{oy}:{fmt_opt}[out]"
                )

        cmd += ["-filter_complex", filter_complex,
                "-map", "[out]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "copy",
                output_path]
        return cmd

    def start_render(self):
        if not self.base_path or not self.overlay_path:
            messagebox.showwarning("Missing files",
                "Please select both a base video and an overlay video.")
            return
        out_dir  = self._resolve_output_dir()
        stem     = os.path.splitext(os.path.basename(self.base_path))[0]
        out_path = os.path.join(out_dir, f"{stem}_composited.mp4")
        cmd      = self._build_ffmpeg_cmd(out_path)

        self._log_append(f"Output → {out_path}")
        self._log_append("cmd: " + " ".join(
            f'"{a}"' if " " in str(a) else str(a) for a in cmd))

        self._stop_flag.clear()
        self._render_btn.config(state="disabled", bg=C["dim"], fg=C["dim"])
        self._stop_btn.config(state="normal",   bg=C["red"],  fg="white")
        self._progress_var.set(0)
        self._set_status("Rendering…")

        base_dur = self.base_info[3] if self.base_info else 0
        threading.Thread(
            target=self._render_worker,
            args=(cmd, out_path, base_dur),
            daemon=True).start()

    def stop_render(self):
        self._stop_flag.set()
        if self._render_proc:
            try: self._render_proc.terminate()
            except Exception: pass

    def _render_worker(self, cmd, out_path, total_dur):
        wall_start = time.time()
        offset_s   = parse_hms(self._offset_var.get())
        preview_stop = threading.Event()
        threading.Thread(
            target=self._preview_sampler,
            args=(preview_stop, offset_s, total_dur),
            daemon=True).start()
        try:
            self._render_proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE,
                universal_newlines=True,
                creationflags=_NO_WINDOW)
            for line in self._render_proc.stderr:
                if self._stop_flag.is_set(): break
                # parse ffmpeg progress line
                m = re.search(r"time=(\d+):(\d+):([\d.]+)", line)
                if m:
                    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    done  = h * 3600 + mi * 60 + s
                    pct   = min(100.0, done / total_dur * 100) if total_dur else 0
                    el    = time.time() - wall_start
                    eta_s = max(0, (el / (pct / 100)) - el) if pct > 0.5 else 0
                    eta_str = str(timedelta(seconds=int(eta_s)))
                    self._ui_queue.put(("progress", pct, eta_str,
                                        f"{done:.1f}s / {total_dur:.0f}s"))
            self._render_proc.wait()
            preview_stop.set()
            ok = (self._render_proc.returncode == 0 and not self._stop_flag.is_set())
            if ok:
                self._ui_queue.put(("done", True,
                    f"✅  Saved → {os.path.basename(out_path)}"))
            else:
                self._ui_queue.put(("done", False,
                    "⏹  Render stopped."))
        except Exception as e:
            preview_stop.set()
            self._ui_queue.put(("done", False, f"❌  Error: {e}"))

    def _preview_sampler(self, stop_event, offset_s, total_dur):
        t        = offset_s
        interval = 1.2
        is_webm  = self.overlay_path and self.overlay_path.lower().endswith(".webm")
        while not stop_event.is_set():
            try:
                ov_t       = max(0.0, t - offset_s)
                base_frame = read_frame_at(self.base_path, t, rgba=False)
                ov_frame   = read_frame_at(self.overlay_path, ov_t, rgba=is_webm)
                if ov_frame is None and is_webm:
                    ov_frame = read_frame_at(self.overlay_path, ov_t, rgba=False)
                if base_frame and ov_frame:
                    ox, oy = self._compute_overlay_xy()
                    comp   = composite_frames(base_frame, ov_frame,
                                              self.crop, (ox, oy),
                                              self._scale_var.get())
                    self._ui_queue.put(("frame", comp, ov_frame, t))
            except Exception:
                pass
            t = min(t + interval, total_dur if total_dur else t + interval)
            stop_event.wait(interval)

    # ── DRAG TO POSITION ──────────────────────────────────────────────────────
    def _toggle_drag_pos(self):
        self._comp_drag_active = not self._comp_drag_active
        if self._comp_drag_active:
            self._drag_pos_btn.config(text="✋  Drag to position: ON",  bg=C["orange"])
            self._comp_canvas.config(cursor="fleur")
            self._set_status("Drag mode ON — click and drag the overlay on the composite preview.")
        else:
            self._drag_pos_btn.config(text="✋  Drag to position: OFF", bg=C["dim"])
            self._comp_canvas.config(cursor="")
            self._set_status("Drag mode OFF.")

    def _drag_pos_press(self, event):
        if not self._comp_drag_active: return
        self._comp_drag_last = (event.x, event.y)

    def _drag_pos_motion(self, event):
        if not self._comp_drag_active or self._comp_drag_last is None: return
        dx = event.x - self._comp_drag_last[0]
        dy = event.y - self._comp_drag_last[1]
        self._comp_drag_last = (event.x, event.y)
        sc = self._comp_canvas_scale
        if sc <= 0: return
        # convert canvas-pixel delta → video-pixel delta
        vdx = int(dx / sc); vdy = int(dy / sc)
        if vdx == 0 and vdy == 0: return
        # read current position (custom X/Y or computed preset)
        try:
            cx = int(self._pos_x_var.get())
            cy = int(self._pos_y_var.get())
        except Exception:
            cx, cy = self._compute_overlay_xy()
        cx += vdx; cy += vdy
        # clamp to base video bounds
        if self.base_info:
            ow, oh = self._cropped_ov_size()
            sc2 = self._scale_var.get() / 100
            ow = int(ow * sc2); oh = int(oh * sc2)
            cx = max(0, min(cx, self.base_info[0] - ow))
            cy = max(0, min(cy, self.base_info[1] - oh))
        self._pos_x_var.set(str(cx))
        self._pos_y_var.set(str(cy))
        self._refresh_composite()

    def _drag_pos_release(self, event):
        self._comp_drag_last = None

    # ── AUTO-CROP TO TEXT ─────────────────────────────────────────────────────
    def _auto_crop(self):
        """
        1. Scan first frame for the Y bounds of the COMMENT line only
           (exclude the timestamp at the bottom by detecting the gap between them).
        2. Scan the full video (sampled every 30s) in a background thread to find
           the WIDEST comment — so short comments don't clip long ones.
        """
        if self._ov_frame is None:
            messagebox.showwarning("No overlay", "Load an overlay video first.")
            return
        if self.overlay_path is None:
            return

        is_webm = self.overlay_path.lower().endswith(".webm")

        # ── Step 1: determine Y bounds from first frame ───────────────────────
        try:
            first = self._ov_frame.convert("RGBA")
            arr   = np.array(first)
            if is_webm:
                mask = arr[:, :, 3] > 10
            else:
                mask = np.any(arr[:, :, :3] > 20, axis=2)

            row_has_content = np.any(mask, axis=1)   # True for each row with pixels
            if not row_has_content.any():
                messagebox.showinfo("Auto-crop",
                    "No visible content found in first overlay frame.\n"
                    "Try loading the overlay again.")
                return

            # Find all contiguous bands of content rows
            bands = []
            in_band = False; band_start = 0
            for r, val in enumerate(row_has_content):
                if val and not in_band:
                    in_band = True; band_start = r
                elif not val and in_band:
                    in_band = False; bands.append((band_start, r - 1))
            if in_band:
                bands.append((band_start, len(row_has_content) - 1))

            if not bands:
                messagebox.showinfo("Auto-crop", "Could not detect content bands.")
                return

            # The Towns video layout (bottom of frame first):
            #   band[-1] = timestamp (lowest / last band)
            #   band[-2] = comment text (the one we want)
            #   separator line is between them (or above the comment)
            # If only one band exists, just use it (no timestamp visible).
            if len(bands) >= 2:
                # Use the second-to-last band (comment), skip last (timestamp)
                y_top    = max(0, bands[-2][0] - 8)    # 8px padding above
                y_bottom = min(first.height, bands[-2][1] + 8)
            else:
                y_top    = max(0, bands[0][0] - 8)
                y_bottom = min(first.height, bands[0][1] + 8)

            # Also keep any separator line that sits just above the comment
            sep_check_top = max(0, y_top - 20)
            sep_rows = row_has_content[sep_check_top:y_top]
            if sep_rows.any():
                y_top = max(0, sep_check_top + int(np.argmax(sep_rows)) - 4)

        except Exception as e:
            messagebox.showerror("Auto-crop", f"Failed analysing first frame:\n{e}")
            return

        # ── Step 2: scan video for widest comment (background thread) ─────────
        self._set_status("⏳  Scanning overlay for widest comment…  (every 30 s)")
        self._auto_crop_btn_state("disabled")
        h_ref    = first.height
        w_ref    = first.width

        def _scan():
            def _progress(done, total):
                pct = int(done / total * 100)
                self.root.after(0, lambda: self._set_status(
                    f"⏳  Scanning overlay…  {done}/{total} frames  ({pct}%)"))

            col_min, col_max = scan_overlay_widths(
                self.overlay_path, is_webm, status_cb=_progress)

            if col_max <= col_min:
                # fallback: use full width
                col_min, col_max = 0, w_ref - 1

            pad   = 8
            x0    = max(0, col_min - pad)
            x1    = min(w_ref, col_max + pad)
            cw    = x1 - x0
            ch    = y_bottom - y_top

            def _apply():
                self._auto_crop_btn_state("normal")
                if cw < 2 or ch < 2:
                    messagebox.showinfo("Auto-crop", "Bounding box too small.")
                    return
                self.crop = (x0, y_top, cw, ch)
                self._crop_lbl.config(
                    text=f"auto  x={x0}  y={y_top}  w={cw}  h={ch}",
                    fg=C["accent"])
                self._redraw_ov_canvas()
                self._update_text_strip(self._ov_frame)
                self._refresh_composite()
                self._set_status(
                    f"✅  Auto-crop applied: {cw}×{ch} px at ({x0},{y_top})"
                    f"  —  comment line only, widest frame used for width")

            self.root.after(0, _apply)

        threading.Thread(target=_scan, daemon=True).start()

    def _auto_crop_btn_state(self, state):
        """Enable/disable the auto-crop button (stored ref needed)."""
        try:
            self._autocrop_btn.config(state=state,
                bg=C["dim"] if state == "disabled" else C["orange"])
        except Exception:
            pass

    # ── LOG / STATUS ──────────────────────────────────────────────────────────
    def _log_append(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.configure(state="normal")
        self._log.insert("1.0", f"[{ts}]  {msg}\n")
        self._log.configure(state="disabled")

    def _set_status(self, msg):
        self._status_lbl.config(text=msg)

    # ── UI QUEUE PUMP ─────────────────────────────────────────────────────────
    def _pump_queue(self):
        try:
            while True:
                item = self._ui_queue.get_nowait()
                tag  = item[0]

                if tag == "progress":
                    _, pct, eta, info = item
                    self._progress_var.set(pct)
                    self._eta_lbl.config(text=f"ETA {eta}")
                    self._set_status(f"Rendering…  {info}  ({pct:.1f}%)")

                elif tag == "frame":
                    _, comp_img, ov_frame, t = item
                    # update composite preview
                    c = self._comp_canvas
                    cw = c.winfo_width(); ch = c.winfo_height()
                    if cw > 4 and ch > 4:
                        sc = min(cw / comp_img.width, ch / comp_img.height)
                        nw = int(comp_img.width * sc); nh = int(comp_img.height * sc)
                        thumb = comp_img.resize((nw, nh), Image.LANCZOS)
                        self._comp_tk = ImageTk.PhotoImage(thumb)
                        c.delete("all")
                        c.create_image((cw-nw)//2, (ch-nh)//2,
                                        anchor="nw", image=self._comp_tk)
                    # update text strip with cropped overlay frame
                    self._text_frame_pil = ov_frame
                    self._redraw_text_canvas()

                elif tag == "done":
                    _, ok, msg = item
                    self._log_append(msg)
                    self._set_status(msg)
                    self._progress_var.set(100 if ok else 0)
                    self._eta_lbl.config(text="")
                    self._render_btn.config(state="normal",   bg=C["green"], fg="white")
                    self._stop_btn.config(state="disabled",  bg=C["dim"],   fg=C["muted"])
                    self._stop_flag.clear()

        except queue.Empty:
            pass
        self.root.after(80, self._pump_queue)


# ──────────────────────────────────────────────────────────────────────────────
# SPLASH
# ──────────────────────────────────────────────────────────────────────────────
def show_splash(root):
    sp = tk.Toplevel(root); sp.overrideredirect(True); sp.configure(bg=C["bg"])
    sw, sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w, h   = 620, 280; sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x")
    body = tk.Frame(sp, bg=C["bg"]); body.pack(expand=True, fill="both", padx=40)
    tk.Label(body, text="GPX OVERLAY COMPOSITOR",
             font=("Consolas", 20, "bold"), bg=C["bg"], fg=C["accent"]).pack(pady=(22, 4))
    tk.Label(body, text=f"{VERSION}  ·  by {AUTHOR}  ·  {datetime.now().year}",
             font=("Consolas", 9), bg=C["bg"], fg=C["muted"]).pack()
    tk.Label(body, text="overlay GPX text onto dashcam footage",
             font=("Consolas", 9, "italic"), bg=C["bg"], fg=C["dim"]).pack(pady=(4, 14))
    pbv = tk.DoubleVar()
    pb  = ttk.Progressbar(body, variable=pbv, maximum=100, length=540); pb.pack()
    pct = tk.Label(body, text="0%", font=("Consolas", 8), bg=C["bg"], fg=C["dim"]); pct.pack(pady=4)
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")
    steps = max(15, SPLASH_SECONDS * 20)
    iv    = int(SPLASH_SECONDS * 1000 / steps)

    def _step(i=0):
        if not sp.winfo_exists(): _finish(); return
        pbv.set(i / steps * 100); pct.config(text=f"{int(i / steps * 100)}%")
        if i < steps: root.after(iv, _step, i + 1)
        else:         root.after(50, _finish)

    def _finish():
        try:    sp.destroy()
        except: pass
        root.deiconify()
        try:    root.state("zoomed")
        except: pass

    root.withdraw()
    root.after(50, _step)


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    show_splash(root)
    app  = CompositorApp(root)
    root.mainloop()
