#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Road Snap  v1.0
Author : Marco Cot
Contact: marcocot1982@gmail.com

Snaps a GPX track to the road network via OSRM map-matching.
Human-in-the-loop: review each chunk, accept or reject individually.

Workflow:
  1. Open GPX file
  2. Set OSRM endpoint (local server recommended)
  3. Run Matching  → chunks are sent to OSRM, results appear live
  4. Click a chunk row to preview original (amber) vs snapped (teal) on map
  5. Accept / Reject individual chunks or use Accept All / Reject All
  6. Save Result  → accepted chunks use snapped coords; rejected keep original
"""

import os, math, time, threading, calendar
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import requests
import gpxpy, gpxpy.gpx
import tkintermapview

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
VERSION        = "v1.0"
AUTHOR         = "Marco Cot"
CONTACT        = "marcocot1982@gmail.com"
SPLASH_SECONDS = 3

DEFAULT_OSRM    = "http://localhost:5000"
DEFAULT_CHUNK   = 80
DEFAULT_OVERLAP = 10

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE  (identical to the rest of the suite)
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
    "teal":   "#26a69a",
    "text":   "#e8e8e8",
    "muted":  "#888888",
    "dim":    "#555555",
}

# ──────────────────────────────────────────────────────────────────────────────
# ICON  (GPS pin + road stripes, drawn with PIL at runtime)
# ──────────────────────────────────────────────────────────────────────────────
def _apply_icon(win):
    try:
        from PIL import Image, ImageDraw, ImageTk
        S = 48
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        cx  = S // 2
        cr  = int(S * 0.36);  cy = int(S * 0.38)
        # pin body
        d.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=(245, 166, 35, 255))
        tip_y = int(S * 0.92)
        d.polygon([(cx - int(cr*0.55), cy + int(cr*0.60)),
                   (cx + int(cr*0.55), cy + int(cr*0.60)),
                   (cx, tip_y)], fill=(245, 166, 35, 255))
        # dark inner circle
        ir = int(cr * 0.50)
        d.ellipse([cx-ir, cy-ir, cx+ir, cy+ir], fill=(20, 20, 20, 255))
        # two white road-lane stripes inside
        lw = max(2, int(ir * 0.22));  lh = int(ir * 0.95)
        for dx in (-int(ir*0.32), int(ir*0.32)):
            lx = cx + dx - lw // 2
            d.rectangle([lx, cy - lh//2, lx + lw, cy + lh//2],
                        fill=(232, 232, 232, 200))
        tk_img = ImageTk.PhotoImage(img)
        win._icon_ref = tk_img        # keep reference alive
        win.iconphoto(True, tk_img)
    except Exception:
        pass   # never crash on icon failure

# ──────────────────────────────────────────────────────────────────────────────
# GEOMETRY HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ──────────────────────────────────────────────────────────────────────────────
# OSRM  (match/v1/driving)
# ──────────────────────────────────────────────────────────────────────────────
def osrm_match(points, osrm_url, timeout=30):
    """
    Send points = [(lat, lon, time|None), …] to OSRM map-matching.

    Returns (snapped_points, confidence):
      • snapped_points  — same length as input; unmatched points keep original coords
      • confidence      — average confidence across all matchings (0.0–1.0)

    Raises on HTTP / OSRM error.
    """
    if not points:
        return [], 0.0

    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon, _ in points)
    params = {
        "overview":   "false",
        "geometries": "geojson",
        "annotations":"false",
        "gaps":       "ignore",
        "tidy":       "false",
    }

    # Attach timestamps when all points have them (improves match quality)
    all_times = [t for _, _, t in points]
    if all(t is not None for t in all_times):
        try:
            ts_vals = [int(calendar.timegm(t.timetuple())) for t in all_times]
            # OSRM requires non-decreasing timestamps
            if all(ts_vals[i] <= ts_vals[i+1] for i in range(len(ts_vals)-1)):
                params["timestamps"] = ";".join(str(v) for v in ts_vals)
        except Exception:
            pass

    url = f"{osrm_url.rstrip('/')}/match/v1/driving/{coords}"
    r   = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    code = data.get("code", "")
    if code != "Ok":
        raise ValueError(f"OSRM error: {data.get('message', code)}")

    tracepoints = data.get("tracepoints", [])
    matchings   = data.get("matchings",   [])

    confidence = (sum(m.get("confidence", 0.0) for m in matchings) / len(matchings)
                  if matchings else 0.0)

    result = []
    for i, (orig_lat, orig_lon, orig_t) in enumerate(points):
        tp = tracepoints[i] if i < len(tracepoints) else None
        if tp and tp.get("location"):
            snap_lon, snap_lat = tp["location"]
            result.append((snap_lat, snap_lon, orig_t))
        else:
            result.append((orig_lat, orig_lon, orig_t))

    return result, confidence


def osrm_ping(url, timeout=5):
    """Quick connectivity test. Returns (ok: bool, message: str)."""
    try:
        r = requests.get(f"{url.rstrip('/')}/", timeout=timeout)
        if r.status_code < 500:
            return True, f"Connected  (HTTP {r.status_code})"
        return False, f"Server error  (HTTP {r.status_code})"
    except requests.exceptions.ConnectionError:
        return False, "Connection refused — is OSRM running?"
    except Exception as e:
        return False, str(e)

# ──────────────────────────────────────────────────────────────────────────────
# CHUNKING
# ──────────────────────────────────────────────────────────────────────────────
def make_chunks(points, chunk_size, overlap):
    """
    Split *points* into overlapping windows of size *chunk_size* advancing
    by (chunk_size − overlap) each step.

    Each chunk dict: { start, end, pts }
      start / end are indices into the original points list  (end exclusive).
    """
    n      = len(points)
    step   = max(1, chunk_size - overlap)
    chunks = []
    i = 0
    while i < n:
        j = min(i + chunk_size, n)
        chunks.append({"start": i, "end": j, "pts": points[i:j]})
        if j >= n:
            break
        i += step
    return chunks

# ──────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ──────────────────────────────────────────────────────────────────────────────
class RoadSnapApp:

    def __init__(self, root):
        self.root = root
        root.title(f"Road Snap  {VERSION}")
        root.configure(bg=C["bg"])
        try:    root.state("zoomed")
        except: root.geometry("1440x860")
        root.resizable(True, True)
        _apply_icon(root)

        # Data state
        self.points      = []   # [(lat, lon, time|None), …]
        self.source_path = ""
        self.chunks      = []   # list of chunk dicts (see below)
        self._matching   = False

        # Map overlay objects (deleted/recreated as needed)
        self._orig_path_obj = None   # full original track, blue
        self._snap_path_obj = None   # all snapped segments, green
        self._sel_orig_obj  = None   # selected chunk – original, amber
        self._sel_snap_obj  = None   # selected chunk – snapped, teal
        self._zoom_level    = [13]

        self._build_style()
        self._build_ui()

    # ── ttk style ────────────────────────────────────────────────────────────
    def _build_style(self):
        sty = ttk.Style(self.root)
        sty.theme_use("clam")
        sty.configure(".",
                       background=C["bg"], foreground=C["text"])
        sty.configure("TLabel",
                       background=C["bg"], foreground=C["text"], font=("Consolas", 9))
        sty.configure("TFrame",   background=C["bg"])
        sty.configure("TEntry",
                       fieldbackground=C["panel2"], foreground=C["text"],
                       insertcolor=C["text"], font=("Consolas", 9))
        sty.configure("TScrollbar",
                       background=C["panel2"], troughcolor=C["border"],
                       arrowcolor=C["muted"])
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
        sty.configure("Horizontal.TProgressbar",
                       background=C["accent"], troughcolor=C["panel2"],
                       bordercolor=C["border"],
                       lightcolor=C["accent"], darkcolor=C["accent2"])

    # ── UI helpers ────────────────────────────────────────────────────────────
    def _mk_btn(self, parent, text, bg, cmd, width=None, font=("Consolas", 9, "bold")):
        kw = dict(
            text=text, bg=bg,
            fg="white" if bg not in (C["dim"], C["panel2"]) else C["muted"],
            activebackground=bg, activeforeground="white",
            relief="flat", cursor="hand2", command=cmd,
            font=font, pady=4, padx=8,
        )
        if width:
            kw["width"] = width
        return tk.Button(parent, **kw)

    def _sec_hdr(self, parent, text):
        f = tk.Frame(parent, bg=C["panel"])
        f.pack(fill="x", padx=10, pady=(12, 3))
        tk.Label(f, text=text, font=("Consolas", 8, "bold"),
                 bg=C["panel"], fg=C["accent"]).pack(side="left")
        tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=10)

    def _set_status(self, msg):
        self.status_lbl.config(text=msg)

    # ── BUILD UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── top chrome ────────────────────────────────────────────────────────
        tk.Frame(self.root, bg=C["accent"], height=3).pack(fill="x")
        tb = tk.Frame(self.root, bg=C["bg"])
        tb.pack(fill="x", padx=16, pady=5)
        tk.Label(tb, text="ROAD SNAP",
                 font=("Consolas", 13, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        tk.Label(tb,
                 text=f"{VERSION}  ·  {AUTHOR}  ·  2025–{datetime.now().year}",
                 font=("Consolas", 8), bg=C["bg"], fg=C["dim"]).pack(side="right")
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True)

        # ════════════════════════ LEFT SIDEBAR ═══════════════════════════════
        left = tk.Frame(body, bg=C["panel"], width=262)
        left.pack(side="left", fill="y", padx=(10, 0), pady=10)
        left.pack_propagate(False)

        # — File —————————————————————————————————————————————————————————————
        self._sec_hdr(left, "FILE")
        fr = tk.Frame(left, bg=C["panel"])
        fr.pack(fill="x", padx=10, pady=6)
        self._mk_btn(fr, "📂  Open GPX",   C["blue"],  self._open_gpx).pack(fill="x", pady=2)
        self._mk_btn(fr, "💾  Save Result", C["green"], self._save_result).pack(fill="x", pady=2)
        self.file_lbl = tk.Label(
            fr, text="No file loaded",
            font=("Consolas", 7, "italic"), bg=C["panel"],
            fg=C["muted"], wraplength=235, anchor="w", justify="left")
        self.file_lbl.pack(anchor="w", pady=(4, 0))

        # — OSRM ─────────────────────────────────────────────────────────────
        self._sec_hdr(left, "OSRM SERVER")
        osrm_f = tk.Frame(left, bg=C["panel"])
        osrm_f.pack(fill="x", padx=10, pady=6)

        tk.Label(osrm_f, text="Endpoint:",
                 font=("Consolas", 8), bg=C["panel"], fg=C["muted"]).pack(anchor="w")
        self.osrm_var = tk.StringVar(value=DEFAULT_OSRM)
        osrm_e = tk.Entry(
            osrm_f, textvariable=self.osrm_var,
            bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
            relief="flat", highlightthickness=1,
            highlightcolor=C["accent"], highlightbackground=C["border"],
            font=("Consolas", 9))
        osrm_e.pack(fill="x", pady=(2, 6))

        self.ping_lbl = tk.Label(
            osrm_f, text="", font=("Consolas", 8),
            bg=C["panel"], fg=C["muted"])
        self.ping_lbl.pack(anchor="w", pady=(0, 4))

        self._mk_btn(osrm_f, "⚡  Test Connection", C["dim"],
                     self._test_osrm, font=("Consolas", 8, "bold")).pack(fill="x")

        tk.Label(osrm_f,
                 text="Run a local OSRM server:\nosrm-routed --algorithm mld data.osrm",
                 font=("Consolas", 7), bg=C["panel"], fg=C["dim"],
                 justify="left").pack(anchor="w", pady=(6, 0))

        # — Chunking ──────────────────────────────────────────────────────────
        self._sec_hdr(left, "CHUNKING")
        ch_f = tk.Frame(left, bg=C["panel"])
        ch_f.pack(fill="x", padx=10, pady=6)

        def _spin_row(parent, label, var_name, default, lo, hi, step):
            r = tk.Frame(parent, bg=C["panel"]); r.pack(fill="x", pady=2)
            tk.Label(r, text=label, font=("Consolas", 8),
                     bg=C["panel"], fg=C["muted"]).pack(side="left")
            v = tk.StringVar(value=str(default))
            setattr(self, var_name, v)
            tk.Spinbox(
                r, textvariable=v, from_=lo, to=hi, increment=step, width=6,
                bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
                buttonbackground=C["panel"], font=("Consolas", 9),
                relief="flat", highlightthickness=0,
            ).pack(side="right")

        _spin_row(ch_f, "Chunk size (pts):", "chunk_var",   DEFAULT_CHUNK,   10, 100, 10)
        _spin_row(ch_f, "Overlap (pts):",    "overlap_var", DEFAULT_OVERLAP,  0,  30,  5)
        tk.Label(
            ch_f,
            text="Smaller chunks = better accuracy\nbut more API calls.\n"
                 "Overlap avoids seam artefacts.",
            font=("Consolas", 7), bg=C["panel"], fg=C["dim"], justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # — Matching ──────────────────────────────────────────────────────────
        self._sec_hdr(left, "MATCHING")
        ma_f = tk.Frame(left, bg=C["panel"])
        ma_f.pack(fill="x", padx=10, pady=6)

        self.run_btn = self._mk_btn(
            ma_f, "🗺  Run Matching", C["orange"], self._run_matching)
        self.run_btn.pack(fill="x", pady=2)

        ba2 = tk.Frame(ma_f, bg=C["panel"]); ba2.pack(fill="x", pady=2)
        self._mk_btn(ba2, "✅  Accept All", C["green"],
                     self._accept_all).pack(side="left", expand=True, fill="x", padx=(0, 2))
        self._mk_btn(ba2, "✕  Reject All", C["red"],
                     self._reject_all).pack(side="left", expand=True, fill="x", padx=(2, 0))

        self.prog_var = tk.DoubleVar()
        ttk.Progressbar(
            ma_f, variable=self.prog_var,
            maximum=100, length=1, mode="determinate",
        ).pack(fill="x", pady=(8, 2))
        self.prog_lbl = tk.Label(
            ma_f, text="", font=("Consolas", 7),
            bg=C["panel"], fg=C["muted"])
        self.prog_lbl.pack(anchor="w")

        # — Statistics ────────────────────────────────────────────────────────
        self._sec_hdr(left, "STATISTICS")
        st_f = tk.Frame(left, bg=C["panel"])
        st_f.pack(fill="x", padx=10, pady=6)
        self.stats_lbl = tk.Label(
            st_f, text="—",
            font=("Consolas", 8), bg=C["panel"], fg=C["muted"], justify="left")
        self.stats_lbl.pack(anchor="w")

        # ════════════════════════ CENTER — CHUNK LIST ═════════════════════════
        center = tk.Frame(body, bg=C["bg"], width=400)
        center.pack(side="left", fill="y", padx=8, pady=10)
        center.pack_propagate(False)

        ch_hdr = tk.Frame(center, bg=C["bg"])
        ch_hdr.pack(fill="x", pady=(0, 4))
        tk.Label(ch_hdr, text="CHUNKS",
                 font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

        # quick-action buttons aligned right
        btn_row = tk.Frame(ch_hdr, bg=C["bg"])
        btn_row.pack(side="right")
        self._mk_btn(btn_row, "✓ Accept", C["green"],
                     self._accept_selected, font=("Consolas", 8, "bold")).pack(side="left", padx=2)
        self._mk_btn(btn_row, "✕ Reject", C["red"],
                     self._reject_selected, font=("Consolas", 8, "bold")).pack(side="left", padx=2)
        self._mk_btn(btn_row, "👁 Preview", C["panel2"],
                     self._preview_selected, font=("Consolas", 8, "bold")).pack(side="left", padx=2)

        tree_border = tk.Frame(center, bg=C["accent"], padx=1, pady=1)
        tree_border.pack(fill="both", expand=True)
        tree_inner = tk.Frame(tree_border, bg=C["panel2"])
        tree_inner.pack(fill="both", expand=True)

        cols = ("chunk", "pts", "status", "conf", "shift")
        self.tree = ttk.Treeview(
            tree_inner, columns=cols, show="headings", selectmode="extended")
        hdrs   = {"chunk": "#", "pts": "Points", "status": "Status",
                  "conf": "Match %", "shift": "Δ avg m"}
        widths = {"chunk": 34,  "pts": 52,      "status": 88,
                  "conf": 62,   "shift": 64}
        for c in cols:
            self.tree.heading(c, text=hdrs[c])
            self.tree.column(c, width=widths[c], anchor="center")

        # row tags — status-driven background / foreground
        self.tree.tag_configure("pending",    foreground=C["dim"],     background=C["panel2"])
        self.tree.tag_configure("processing", foreground=C["accent"],  background=C["panel2"])
        self.tree.tag_configure("matched",    foreground=C["text"],    background=C["panel2"])
        self.tree.tag_configure("accepted",   foreground=C["green"],   background="#192b19")
        self.tree.tag_configure("rejected",   foreground=C["dim"],     background="#2a1a1a")
        self.tree.tag_configure("failed",     foreground=C["red"],     background="#2a1414")

        tsb = ttk.Scrollbar(tree_inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # keyboard shortcuts while treeview has focus
        self.tree.bind("a", lambda e: self._accept_selected())
        self.tree.bind("r", lambda e: self._reject_selected())
        self.tree.bind("<Return>", lambda e: self._accept_selected())

        self.chunk_lbl = tk.Label(
            center, text="",
            font=("Consolas", 8), bg=C["bg"], fg=C["muted"])
        self.chunk_lbl.pack(anchor="w", pady=(4, 0))

        # legend for keyboard shortcuts
        tk.Label(
            center,
            text="Keys (treeview focus):  a = accept  ·  r = reject  ·  Enter = accept",
            font=("Consolas", 7), bg=C["bg"], fg=C["dim"],
        ).pack(anchor="w")

        # ════════════════════════ RIGHT — MAP ═════════════════════════════════
        map_outer = tk.Frame(body, bg=C["bg"])
        map_outer.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=10)

        mh = tk.Frame(map_outer, bg=C["bg"])
        mh.pack(fill="x", pady=(0, 4))
        tk.Label(mh, text="TRACK MAP",
                 font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

        # colour legend
        leg = tk.Frame(mh, bg=C["bg"])
        leg.pack(side="left", padx=18)
        for col, txt in [
            (C["blue"],   "Original"),
            (C["green"],  "Snapped"),
            (C["accent"], "Sel. original"),
            (C["teal"],   "Sel. snapped"),
        ]:
            tk.Frame(leg, bg=col, width=20, height=3).pack(side="left", padx=(0, 3))
            tk.Label(leg, text=txt, font=("Consolas", 7),
                     bg=C["bg"], fg=C["muted"]).pack(side="left", padx=(0, 10))

        # zoom + fit buttons
        zf = tk.Frame(mh, bg=C["bg"])
        zf.pack(side="right")
        self._mk_btn(zf, "⊡ Fit",  C["panel2"],
                     self._fit_track, font=("Consolas", 8, "bold")).pack(side="left", padx=(0, 6))
        self._mk_btn(zf, "＋",     C["panel2"],
                     self._zoom_in,  font=("Consolas", 11, "bold")).pack(side="left", padx=2)
        self._mk_btn(zf, "－",     C["panel2"],
                     self._zoom_out, font=("Consolas", 11, "bold")).pack(side="left", padx=2)

        map_border = tk.Frame(map_outer, bg=C["accent"], padx=2, pady=2)
        map_border.pack(fill="both", expand=True)
        self.map_widget = tkintermapview.TkinterMapView(map_border, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)
        self.map_widget.set_tile_server(
            "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
        self.map_widget.set_position(45.0, 7.0)
        self.map_widget.set_zoom(5)

        # ── STATUS BAR ────────────────────────────────────────────────────────
        sb = tk.Frame(self.root, bg=C["panel"], height=26)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        self.status_lbl = tk.Label(
            sb, text="Ready. Open a GPX file to begin.",
            font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
        self.status_lbl.pack(side="left", padx=10, pady=3)

    # ── ZOOM / FIT ────────────────────────────────────────────────────────────
    def _zoom_in(self):
        z = min(self._zoom_level[0] + 1, 19)
        self._zoom_level[0] = z
        self.map_widget.set_zoom(z)

    def _zoom_out(self):
        z = max(self._zoom_level[0] - 1, 2)
        self._zoom_level[0] = z
        self.map_widget.set_zoom(z)

    def _fit_track(self):
        if not self.points:
            return
        lats = [p[0] for p in self.points]
        lons = [p[1] for p in self.points]
        try:
            self.map_widget.fit_bounding_box(
                (max(lats), min(lons)), (min(lats), max(lons)))
        except Exception:
            span = max(max(lats) - min(lats), max(lons) - min(lons))
            z    = (7  if span > 5   else
                    9  if span > 2   else
                    10 if span > 1   else
                    12 if span > 0.3 else
                    13 if span > 0.1 else 14)
            self._zoom_level[0] = z
            self.map_widget.set_position(
                (min(lats) + max(lats)) / 2,
                (min(lons) + max(lons)) / 2)
            self.map_widget.set_zoom(z)

    # ── FILE OPS ──────────────────────────────────────────────────────────────
    def _open_gpx(self):
        path = filedialog.askopenfilename(
            title="Open GPX file",
            filetypes=[("GPX files", "*.gpx")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                gpx = gpxpy.parse(fh)
            pts = [(p.latitude, p.longitude, p.time)
                   for t in gpx.tracks
                   for s in t.segments
                   for p in s.points]
        except Exception as e:
            messagebox.showerror("Load error", str(e))
            return

        if not pts:
            messagebox.showwarning("Empty", "No trackpoints found in this file.")
            return

        self.points      = pts
        self.source_path = path
        self.chunks      = []

        self.file_lbl.config(
            text=f"{os.path.basename(path)}\n{len(pts):,} trackpoints")
        self._set_status(
            f"Loaded: {os.path.basename(path)}  ·  {len(pts):,} points")
        self.prog_var.set(0)
        self.prog_lbl.config(text="")
        self._refresh_tree()
        self._update_stats()
        self._draw_original()
        self._clear_snapped()
        self._fit_track()

    # ── MAP DRAWING ───────────────────────────────────────────────────────────
    def _del_obj(self, obj):
        if obj:
            try:    obj.delete()
            except: pass
        return None

    def _draw_original(self):
        """Redraw the full original track in blue."""
        self._orig_path_obj = self._del_obj(self._orig_path_obj)
        if len(self.points) < 2:
            return
        coords = [(p[0], p[1]) for p in self.points]
        try:
            self._orig_path_obj = self.map_widget.set_path(
                coords, color=C["blue"], width=2)
        except Exception:
            pass

    def _clear_snapped(self):
        self._snap_path_obj = self._del_obj(self._snap_path_obj)

    def _draw_snapped_full(self):
        """
        Draw all snapped segments (every matched chunk, regardless of
        accept/reject decision) in green so the user can compare freely.
        """
        self._snap_path_obj = self._del_obj(self._snap_path_obj)
        all_snapped = []
        for ch in self.chunks:
            if ch.get("snapped"):
                all_snapped.extend(ch["snapped"])
        if len(all_snapped) < 2:
            return
        coords = [(p[0], p[1]) for p in all_snapped]
        try:
            self._snap_path_obj = self.map_widget.set_path(
                coords, color=C["green"], width=2)
        except Exception:
            pass

    def _highlight_chunk(self, chunk_idx):
        """
        Overlay the selected chunk on the map:
          • amber — original GPX segment
          • teal  — OSRM-snapped segment (if matched)
        """
        self._sel_orig_obj = self._del_obj(self._sel_orig_obj)
        self._sel_snap_obj = self._del_obj(self._sel_snap_obj)

        if chunk_idx is None or chunk_idx >= len(self.chunks):
            return
        ch = self.chunks[chunk_idx]

        # original segment (amber, thick)
        orig_coords = [(p[0], p[1]) for p in ch["pts"]]
        if len(orig_coords) >= 2:
            try:
                self._sel_orig_obj = self.map_widget.set_path(
                    orig_coords, color=C["accent"], width=4)
            except Exception:
                pass

        # snapped segment (teal, thick)
        sp = ch.get("snapped")
        if sp and len(sp) >= 2:
            snap_coords = [(p[0], p[1]) for p in sp]
            try:
                self._sel_snap_obj = self.map_widget.set_path(
                    snap_coords, color=C["teal"], width=4)
            except Exception:
                pass

        # Pan to the midpoint of the chunk without changing zoom
        if orig_coords:
            mid = orig_coords[len(orig_coords) // 2]
            try:
                self.map_widget.set_position(mid[0], mid[1])
            except Exception:
                pass

        # Show chunk detail in status bar
        n_pts = len(ch["pts"])
        conf  = int(ch.get("confidence", 0.0) * 100)
        shift = ch.get("shift_m", 0.0)
        err   = ch.get("error", "")
        if ch["status"] == "failed":
            detail = f"  ·  FAILED: {err}"
        elif ch.get("snapped"):
            detail = f"  ·  match {conf}%  ·  avg shift {shift:.1f} m"
        else:
            detail = ""
        self._set_status(
            f"Chunk {chunk_idx+1}/{len(self.chunks)}  ·  "
            f"pts {ch['start']}–{ch['end']-1}  ({n_pts} pts){detail}")

    # ── OSRM TEST ─────────────────────────────────────────────────────────────
    def _test_osrm(self):
        url = self.osrm_var.get().strip()
        self.ping_lbl.config(text="Testing…", fg=C["muted"])
        self.root.update_idletasks()

        def _ping():
            ok, msg = osrm_ping(url)
            color   = C["green"] if ok else C["red"]
            self.root.after(0, lambda: self.ping_lbl.config(text=msg, fg=color))

        threading.Thread(target=_ping, daemon=True).start()

    # ── RUN MATCHING ──────────────────────────────────────────────────────────
    def _run_matching(self):
        if not self.points:
            messagebox.showwarning("No file", "Open a GPX file first.")
            return
        if self._matching:
            messagebox.showinfo("Busy", "Matching already in progress.")
            return

        try:
            chunk_size = max(2, int(self.chunk_var.get()))
            overlap    = min(max(0, int(self.overlap_var.get())), chunk_size - 1)
        except ValueError:
            messagebox.showerror("Error", "Invalid chunk / overlap value.")
            return

        url = self.osrm_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Enter an OSRM endpoint URL.")
            return

        # Build fresh chunk list
        raw = make_chunks(self.points, chunk_size, overlap)
        self.chunks = [{
            "start":      rc["start"],
            "end":        rc["end"],
            "pts":        rc["pts"],
            "status":     "pending",
            "snapped":    None,
            "confidence": 0.0,
            "shift_m":    0.0,
            "error":      None,
        } for rc in raw]

        self._refresh_tree()
        self._draw_original()
        self._clear_snapped()

        self._matching = True
        self.run_btn.config(state="disabled", bg=C["dim"])
        self.prog_var.set(0)
        self._set_status(
            f"Matching {len(self.chunks)} chunks via OSRM  ({chunk_size} pts / chunk, "
            f"{overlap} pt overlap)…")

        threading.Thread(target=self._match_thread,
                         args=(url,), daemon=True).start()

    def _match_thread(self, url):
        """Background thread: process each chunk, update UI after each one."""
        n = len(self.chunks)
        for i, ch in enumerate(self.chunks):
            # mark as processing
            ch["status"] = "processing"
            self.root.after(0, lambda i=i: self._tree_update_row(i))

            try:
                snapped, conf = osrm_match(ch["pts"], url)
                shifts = [
                    haversine(ch["pts"][j][0], ch["pts"][j][1],
                              snapped[j][0],   snapped[j][1])
                    for j in range(len(snapped))
                ]
                ch["snapped"]    = snapped
                ch["confidence"] = conf
                ch["shift_m"]    = sum(shifts) / len(shifts) if shifts else 0.0
                ch["status"]     = "matched"
                ch["error"]      = None
            except Exception as e:
                ch["snapped"]    = None
                ch["status"]     = "failed"
                ch["error"]      = str(e)

            pct = (i + 1) / n * 100

            def _ui(i=i, pct=pct):
                self._tree_update_row(i)
                self.prog_var.set(pct)
                self.prog_lbl.config(text=f"{i+1} / {n} chunks processed")
                self._draw_snapped_full()
                self._update_stats()

            self.root.after(0, _ui)

        self._matching = False

        def _done():
            self.run_btn.config(state="normal", bg=C["orange"])
            n_ok  = sum(1 for c in self.chunks if c["status"] == "matched")
            n_err = sum(1 for c in self.chunks if c["status"] == "failed")
            self._set_status(
                f"Matching complete — {n_ok} matched, {n_err} failed.  "
                "Select chunks to preview; Accept or Reject each one.")
            self.prog_lbl.config(text="Done — review chunks in the list")

        self.root.after(0, _done)

    # ── TREEVIEW ──────────────────────────────────────────────────────────────
    def _refresh_tree(self):
        """Rebuild the entire treeview from self.chunks."""
        self.tree.delete(*self.tree.get_children())
        for i, ch in enumerate(self.chunks):
            conf_s  = ""
            shift_s = ""
            if ch.get("snapped"):
                conf_s  = f"{int(ch['confidence'] * 100)}%"
                shift_s = f"{ch['shift_m']:.1f}"
            elif ch["status"] == "failed":
                conf_s = "ERR"
            self.tree.insert(
                "", "end",
                values=(i + 1, len(ch["pts"]), ch["status"].upper(),
                        conf_s, shift_s),
                tags=(ch["status"],))
        self.chunk_lbl.config(text=f"{len(self.chunks)} chunks  ·  {len(self.points):,} total pts")

    def _tree_update_row(self, i):
        """Update a single treeview row in-place (faster than full refresh)."""
        if i >= len(self.chunks):
            return
        items = self.tree.get_children()
        if i >= len(items):
            return
        ch = self.chunks[i]
        conf_s  = ""
        shift_s = ""
        if ch.get("snapped"):
            conf_s  = f"{int(ch['confidence'] * 100)}%"
            shift_s = f"{ch['shift_m']:.1f}"
        elif ch["status"] == "failed":
            conf_s = "ERR"
        self.tree.item(
            items[i],
            values=(i + 1, len(ch["pts"]), ch["status"].upper(), conf_s, shift_s),
            tags=(ch["status"],))

    def _on_tree_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        # preview the last selected row
        idx = self.tree.index(sel[-1])
        self._highlight_chunk(idx)

    def _preview_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        self._highlight_chunk(self.tree.index(sel[-1]))

    # ── ACCEPT / REJECT ───────────────────────────────────────────────────────
    def _set_decision(self, indices, decision):
        """
        Set 'accepted' or 'rejected' on the given chunk indices.
        Only matched chunks can be accepted.
        """
        changed = False
        for idx in indices:
            if idx >= len(self.chunks):
                continue
            ch = self.chunks[idx]
            if decision == "accepted" and not ch.get("snapped"):
                continue    # can't accept a failed chunk
            ch["status"] = decision
            self._tree_update_row(idx)
            changed = True
        if changed:
            self._update_stats()

    def _accept_selected(self):
        indices = [self.tree.index(i) for i in self.tree.selection()]
        self._set_decision(indices, "accepted")

    def _reject_selected(self):
        indices = [self.tree.index(i) for i in self.tree.selection()]
        self._set_decision(indices, "rejected")

    def _accept_all(self):
        self._set_decision(range(len(self.chunks)), "accepted")

    def _reject_all(self):
        self._set_decision(range(len(self.chunks)), "rejected")

    # ── STATISTICS ────────────────────────────────────────────────────────────
    def _update_stats(self):
        if not self.chunks:
            self.stats_lbl.config(text="—")
            return
        n_tot  = len(self.chunks)
        n_ok   = sum(1 for c in self.chunks if c["snapped"])
        n_acc  = sum(1 for c in self.chunks if c["status"] == "accepted")
        n_rej  = sum(1 for c in self.chunks if c["status"] == "rejected")
        n_pend = sum(1 for c in self.chunks if c["status"] in ("pending", "matched"))
        n_fail = sum(1 for c in self.chunks if c["status"] == "failed")
        avg_conf = 0.0
        if n_ok:
            avg_conf = sum(c["confidence"] for c in self.chunks
                           if c.get("snapped")) / n_ok
        avg_shift = 0.0
        if n_ok:
            avg_shift = sum(c["shift_m"] for c in self.chunks
                            if c.get("snapped")) / n_ok
        self.stats_lbl.config(
            text=(f"Chunks:    {n_tot}\n"
                  f"Matched:   {n_ok}\n"
                  f"Accepted:  {n_acc}\n"
                  f"Rejected:  {n_rej}\n"
                  f"Pending:   {n_pend}\n"
                  f"Failed:    {n_fail}\n"
                  f"Avg conf:  {int(avg_conf*100)}%\n"
                  f"Avg shift: {avg_shift:.1f} m"))

    # ── SAVE ──────────────────────────────────────────────────────────────────
    def _save_result(self):
        if not self.chunks:
            messagebox.showwarning("Nothing to save",
                                   "Run matching first, then accept/reject chunks.")
            return

        n_acc = sum(1 for c in self.chunks if c["status"] == "accepted")
        n_rej = sum(1 for c in self.chunks if c["status"] == "rejected")
        n_und = len(self.chunks) - n_acc - n_rej - sum(
            1 for c in self.chunks if c["status"] == "failed")

        if n_und > 0:
            if not messagebox.askyesno(
                "Undecided chunks",
                f"{n_und} chunk(s) have not been accepted or rejected.\n"
                "They will be saved using the ORIGINAL coordinates.\n\n"
                "Proceed?",
            ):
                return

        # Build merged result:
        #   accepted → snapped coords
        #   everything else → original coords
        # Overlap deduplication: skip points already covered by the previous chunk.
        result_pts = []
        prev_end   = 0

        for ch in self.chunks:
            use         = ch["snapped"] if ch["status"] == "accepted" else ch["pts"]
            core_offset = max(0, prev_end - ch["start"])
            result_pts.extend(use[core_offset:])
            prev_end    = ch["end"]

        if not result_pts:
            messagebox.showwarning("Empty", "No points to save.")
            return

        stem     = (os.path.splitext(os.path.basename(self.source_path))[0]
                    if self.source_path else "track")
        def_name = stem + "_snapped.gpx"
        path     = filedialog.asksaveasfilename(
            defaultextension=".gpx",
            initialfile=def_name,
            filetypes=[("GPX files", "*.gpx")],
        )
        if not path:
            return

        # Write GPX
        gpx = gpxpy.gpx.GPX()
        trk = gpxpy.gpx.GPXTrack(); gpx.tracks.append(trk)
        seg = gpxpy.gpx.GPXTrackSegment(); trk.segments.append(seg)
        for lat, lon, t in result_pts:
            seg.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, time=t))

        with open(path, "w", encoding="utf-8") as f:
            f.write(gpx.to_xml())

        self._set_status(
            f"Saved → {os.path.basename(path)}  ·  "
            f"{len(result_pts):,} pts  ·  "
            f"{n_acc}/{len(self.chunks)} chunks snapped")
        messagebox.showinfo(
            "Saved",
            f"Saved {len(result_pts):,} trackpoints.\n\n"
            f"  Accepted (snapped):  {n_acc}\n"
            f"  Rejected (original): {n_rej}\n"
            f"  Other / failed:      {len(self.chunks)-n_acc-n_rej}\n\n"
            f"→ {path}",
        )


# ──────────────────────────────────────────────────────────────────────────────
# SPLASH
# ──────────────────────────────────────────────────────────────────────────────
def show_splash(root):
    sp = tk.Toplevel(root)
    sp.overrideredirect(True)
    sp.configure(bg=C["bg"])
    sw, sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w, h   = 620, 300
    sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x")
    body = tk.Frame(sp, bg=C["bg"])
    body.pack(expand=True, fill="both", padx=40)

    tk.Label(body, text="ROAD SNAP",
             font=("Consolas", 22, "bold"), bg=C["bg"], fg=C["accent"]).pack(pady=(28, 4))
    tk.Label(body,
             text=f"{VERSION}  ·  by {AUTHOR}  ·  {datetime.now().year}",
             font=("Consolas", 9), bg=C["bg"], fg=C["muted"]).pack()
    tk.Label(body,
             text="snap GPX tracks to the road network via OSRM",
             font=("Consolas", 9, "italic"), bg=C["bg"], fg=C["dim"]).pack(pady=(4, 16))

    pbv = tk.DoubleVar()
    pb  = ttk.Progressbar(body, variable=pbv, maximum=100, length=540)
    pb.pack()
    pct = tk.Label(body, text="Loading…",
                   font=("Consolas", 8), bg=C["bg"], fg=C["dim"])
    pct.pack(pady=4)

    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")

    steps       = max(15, SPLASH_SECONDS * 20)
    interval_ms = int(SPLASH_SECONDS * 1000 / steps)

    def _step(i=0):
        if not sp.winfo_exists():
            _finish(); return
        pbv.set(i / steps * 100)
        pct.config(text=f"{int(i / steps * 100)}%")
        if i < steps:
            root.after(interval_ms, _step, i + 1)
        else:
            root.after(50, _finish)

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
    app  = RoadSnapApp(root)
    root.mainloop()
