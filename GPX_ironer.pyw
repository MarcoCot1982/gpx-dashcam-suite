#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Ironer  v2.0
Author : Marco Cot
Contact: marcocot1982@gmail.com

Dark cinematic UI. Auto-saves a _temp file every 10 minutes after changes.
"""

import os, math, time, threading, sys
from datetime import datetime, timedelta

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import gpxpy, gpxpy.gpx
import tkintermapview

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
VERSION        = "v2.0"
AUTHOR         = "Marco Cot"
CONTACT        = "marcocot1982@gmail.com"
AUTOSAVE_SECS  = 600          # 10 minutes
SPLASH_SECONDS = 3

SEGMENT_COLORS = ["#2196F3","#4caf50","#e53935","#ab47bc",
                  "#00bcd4","#ff7043","#8d6e63","#26a69a"]

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE  (shared with geocoder / video app)
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
    "rogue":  "#3d1a1a",   # treeview row highlight for rogue points
}

# ──────────────────────────────────────────────────────────────────────────────
# APP ICON  (GPS pin ICO embedded as base64, written to temp file for iconbitmap)
# ──────────────────────────────────────────────────────────────────────────────
_ICON_B64 = (
    "AAABAAMAEBAAAAEAIACjAAAANgAAACAgAAABACAADAEAANkAAAAwMAAAAQAgAGwBAADlAQAAiVBO"
    "Rw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAaklEQVR4nGNgoBAw4pL4ukz5PzKfO+ou"
    "VrVMxGjGJYbVAFwKcckx4VMgn/eRQT7vI15DsHoBphkbG68LyAHUNQA5qh5O4mfAxkaPTqxxiysm"
    "sKUF2oQBNptISon4NBBtADmGYQX4kjZVAADVbyvSac34uAAAAABJRU5ErkJggolQTkcNChoKAAAA"
    "DUlIRFIAAAAgAAAAIAgGAAAAc3p69AAAANNJREFUeJzllrEVgzAMRIGXjoIRKLIVQ2SYDMFWFIyQ"
    "gprU5Nny3flc5KEOg6Svk2zcdXe3XnE61ueZWh+XjY5HOeQS14AM7uTstxAAE5D1KQIoyRnfEKAm"
    "ORrjoQaeX5/L8/6epDhZBSLy3+S5NSQWvAtaGQ0QVRq9swG47f8AomlXdkIWQPmxKLGkFqQqVc+"
    "BYpW1p2FJyaICNa1AfKEWKBCoDzwDDESTC0krowCQyth20Qo4zwcJIDIFTgJwqmBTQIWSAVwqWBRw"
    "DyZljpvzve0L5hZNhecLYLsAAAAASUVORK5CYIKJUE5HDQoaCgAAAA1JSERSAAAAMAAAADAIBgAA"
    "AFcC+YcAAAEzSURBVHic7Zm7EcJADEQNQ0ZACQR0RREUQxF0RUAJBMQQEXAztrXS0x0e32Y29p6e"
    "pPsAw9DVFdKGNnzdTu+pz/fnOzomZjYXeCkKJGyiBl4qCrKNvBwNnvBwAxDBE14uADL4qKcMkBF8"
    "xFsCyAzeO0ZoEv+DzEuYmpnj5flz/bgelNfNy+tOcjWoDLy8r4LMydRC1uyPBa8+o4y5+DmAAVgz"
    "qz47p16B1uoArYUBKOs7uReYAOivgeSYaAtZMkvvxFJmlfNQ5CykVBw/C31FZ3pMUgvVmAvqGPIc"
    "yITweLsmcQaE19O9CpEQEa9178REFZr+MkcEEFXTFiLgEYCWVcAqoEJQ0E1aiKwYCtCilapXgIbE"
    "AWpXIaUCYxAZcOs+SkypzHZWay2+Aumq8a9OV1dAH+B+b3avl+Q2AAAAAElFTkSuQmCC"
)

def _set_icon(root):
    """Write the embedded ICO to a temp file and apply it via iconbitmap."""
    try:
        import base64, tempfile, os
        ico_bytes = base64.b64decode(_ICON_B64)
        tmp = tempfile.NamedTemporaryFile(suffix=".ico", delete=False)
        tmp.write(ico_bytes); tmp.close()
        root.iconbitmap(tmp.name)
        # clean up after a short delay so tkinter has time to read it
        root.after(2000, lambda: _try_remove(tmp.name))
    except Exception:
        pass   # icon is cosmetic — never crash for this

def _try_remove(path):
    try:
        import os; os.remove(path)
    except Exception:
        pass
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = math.radians(lat2 - lat1); dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def speed_kph_between(a, b):
    if not a or not b or a[2] is None or b[2] is None: return 0
    secs = abs((b[2] - a[2]).total_seconds())
    return 0 if secs == 0 else (haversine(a[0],a[1],b[0],b[1])/secs)*3.6

def get_dir_indicator(p1, p2):
    if not p1 or not p2: return ""
    dlat, dlon = p2[0]-p1[0], p2[1]-p1[1]
    angle = math.degrees(math.atan2(dlon, dlat)) % 360
    return ["↑","↗","→","↘","↓","↙","←","↖","↑"][int((angle+22.5)/45)]

def splice_decimals(val_ref, val_target):
    sr, st = f"{val_ref:.10f}", f"{val_target:.10f}"
    return float(f"{sr.split('.')[0]}.{sr.split('.')[1][:3]}{st.split('.')[1][3:]}")

# ──────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ──────────────────────────────────────────────────────────────────────────────
class IronApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"GPX Ironer  {VERSION}")
        self.root.configure(bg=C["bg"])
        try:    self.root.state("zoomed")
        except: self.root.geometry("1440x860")
        self.root.resizable(True, True)

        # app icon (GPS pin via iconbitmap)
        _set_icon(self.root)

        self.points           = []
        self.current_filename = ""
        self.source_path      = ""
        self.filtered_indices = None
        self.focus_range      = None
        self._dirty           = False      # True after any unsaved change
        self._last_autosave   = time.time()
        self._last_temp_path  = ""
        self._pending_center  = None       # ("fit",) or ("point", lat, lon, zoom)
        self._undo_stack      = []         # list of points snapshots for undo
        self._drag_mode       = False      # True = drag-to-move, False = click-to-select
        self._drag_idx        = None       # index of point being dragged
        self._drag_marker     = None       # temporary marker shown during drag
        self._sel_marker      = None       # amber pin for selected point
        # multi-file support: list of {"path": str, "count": int}
        self._file_segments   = []

        # ── ttk style ─────────────────────────────────────────────────────────
        sty = ttk.Style(root); sty.theme_use("clam")
        sty.configure(".",              background=C["bg"],    foreground=C["text"])
        sty.configure("TLabel",         background=C["bg"],    foreground=C["text"],  font=("Consolas",9))
        sty.configure("TFrame",         background=C["bg"])
        sty.configure("TLabelframe",    background=C["panel"], foreground=C["accent"],
                                        font=("Consolas",8,"bold"), relief="flat", borderwidth=1)
        sty.configure("TLabelframe.Label", background=C["panel"], foreground=C["accent"],
                                           font=("Consolas",8,"bold"))
        sty.configure("TEntry",         fieldbackground=C["panel2"], foreground=C["text"],
                                        insertcolor=C["text"],  font=("Consolas",9))
        sty.configure("TScrollbar",     background=C["panel2"], troughcolor=C["border"],
                                        arrowcolor=C["muted"])
        sty.configure("Treeview",       background=C["panel2"], foreground=C["text"],
                                        fieldbackground=C["panel2"], font=("Consolas",8),
                                        rowheight=20, borderwidth=0)
        sty.configure("Treeview.Heading", background=C["panel"], foreground=C["accent"],
                                           font=("Consolas",8,"bold"), relief="flat")
        sty.map("Treeview",
                background=[("selected", C["accent"])],
                foreground=[("selected", "black")])
        sty.map("Treeview.Heading", background=[("active", C["panel2"])])

        # tk vars
        self.max_kph_iron       = tk.StringVar(value="5000")
        self.max_kph_bridge     = tk.StringVar(value="200")
        self.marker_freq_var    = tk.StringVar(value="100")
        self.color_interval_var = tk.StringVar(value="10")
        self.show_dots_var      = tk.BooleanVar(value=False)

        self._build_ui()
        self._schedule_autosave()

    # ── UI helpers ─────────────────────────────────────────────────────────────
    def _mk_btn(self, parent, text, bg, cmd, width=None, font=("Consolas",9,"bold")):
        kw = dict(text=text, bg=bg,
                  fg="white" if bg not in (C["dim"], C["panel2"]) else C["muted"],
                  activebackground=bg, activeforeground="white",
                  relief="flat", cursor="hand2", command=cmd,
                  font=font, pady=4, padx=8)
        if width: kw["width"] = width
        return tk.Button(parent, **kw)

    def _sec_hdr(self, parent, text):
        f = tk.Frame(parent, bg=C["panel"]); f.pack(fill="x", padx=10, pady=(12,3))
        tk.Label(f, text=text, font=("Consolas",8,"bold"),
                 bg=C["panel"], fg=C["accent"]).pack(side="left")
        tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=10)

    def _lbl_entry(self, parent, text, var_or_entry, width=6):
        """Returns an Entry widget packed inline."""
        r = tk.Frame(parent, bg=C["panel"]); r.pack(side="left")
        tk.Label(r, text=text, font=("Consolas",8), bg=C["panel"],
                 fg=C["muted"]).pack(side="left", padx=(6,1))
        if isinstance(var_or_entry, tk.StringVar):
            e = ttk.Entry(r, textvariable=var_or_entry, width=width); e.pack(side="left")
            return e
        else:
            e = ttk.Entry(r, width=width); e.pack(side="left"); return e

    # ── BUILD UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # top chrome
        tk.Frame(self.root, bg=C["accent"], height=3).pack(fill="x")
        tb = tk.Frame(self.root, bg=C["bg"]); tb.pack(fill="x", padx=16, pady=5)
        tk.Label(tb, text="GPX IRONER",
                 font=("Consolas",13,"bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        tk.Label(tb, text=f"{VERSION}  ·  {AUTHOR}  ·  2025–{datetime.now().year}",
                 font=("Consolas",8), bg=C["bg"], fg=C["dim"]).pack(side="right")
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

        # body
        body = tk.Frame(self.root, bg=C["bg"]); body.pack(fill="both", expand=True)

        # ── LEFT SIDEBAR (scrollable) ─────────────────────────────────────────
        left_outer = tk.Frame(body, bg=C["panel"], width=270)
        left_outer.pack(side="left", fill="y", padx=(10,0), pady=10)
        left_outer.pack_propagate(False)

        self._left_canvas = tk.Canvas(left_outer, bg=C["panel"], highlightthickness=0)
        left_sb = ttk.Scrollbar(left_outer, orient="vertical", command=self._left_canvas.yview)
        self._left_canvas.configure(yscrollcommand=left_sb.set)
        left_sb.pack(side="right", fill="y")
        self._left_canvas.pack(side="left", fill="both", expand=True)

        left = tk.Frame(self._left_canvas, bg=C["panel"])
        _left_win = self._left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_left_frame_resize(e):
            self._left_canvas.configure(scrollregion=self._left_canvas.bbox("all"))
        def _on_left_canvas_resize(e):
            self._left_canvas.itemconfig(_left_win, width=e.width)
        left.bind("<Configure>", _on_left_frame_resize)
        self._left_canvas.bind("<Configure>", _on_left_canvas_resize)

        # Root-level mousewheel: scroll sidebar only when cursor is over it.
        # Reliable on Windows (per-widget bindings get swallowed by ttk focus handling).
        def _root_wheel(e):
            try:
                ox = left_outer.winfo_rootx(); ow = left_outer.winfo_width()
                oy = left_outer.winfo_rooty(); oh = left_outer.winfo_height()
                if ox <= e.x_root <= ox+ow and oy <= e.y_root <= oy+oh:
                    units = int(-1*(e.delta/120)) if e.delta else (-1 if e.num==4 else 1)
                    self._left_canvas.yview_scroll(units, "units")
            except Exception: pass
        self.root.bind("<MouseWheel>", _root_wheel, add="+")
        self.root.bind("<Button-4>",   _root_wheel, add="+")
        self.root.bind("<Button-5>",   _root_wheel, add="+")

        self._sec_hdr(left, "FILE")
        fr = tk.Frame(left, bg=C["panel"]); fr.pack(fill="x", padx=10, pady=6)
        self._mk_btn(fr, "📂  Open GPX",   C["blue"],   self.select_files).pack(fill="x", pady=2)
        self._mk_btn(fr, "💾  Save GPX",   C["green"],  self.export_clean_gpx).pack(fill="x", pady=2)
        self._mk_btn(fr, "🔄  Refresh View",C["dim"],   self.refresh_map_and_tree).pack(fill="x", pady=2)

        self.file_lbl = tk.Label(left, text="No file loaded",
                                  font=("Consolas",8,"italic"), bg=C["panel"],
                                  fg=C["muted"], wraplength=240, anchor="w")
        self.file_lbl.pack(padx=10, anchor="w", pady=(0,4))

        # auto-save status
        self.autosave_lbl = tk.Label(left, text="",
                                      font=("Consolas",7), bg=C["panel"], fg=C["dim"])
        self.autosave_lbl.pack(padx=10, anchor="w")

        self._sec_hdr(left, "SELF-CORRECT")
        ib = tk.Frame(left, bg=C["panel"]); ib.pack(fill="x", padx=10, pady=6)
        r1 = tk.Frame(ib, bg=C["panel"]); r1.pack(fill="x", pady=2)
        self._lbl_entry(r1, "Iron KPH",   self.max_kph_iron,   width=6)
        self._lbl_entry(r1, "Bridge KPH", self.max_kph_bridge, width=6)
        r2 = tk.Frame(ib, bg=C["panel"]); r2.pack(fill="x", pady=4)
        self._mk_btn(r2, "⚙  Self-Correct", C["orange"], self.self_correct).pack(fill="x")

        self._sec_hdr(left, "VISUAL")
        vs = tk.Frame(left, bg=C["panel"]); vs.pack(fill="x", padx=10, pady=6)
        r3 = tk.Frame(vs, bg=C["panel"]); r3.pack(fill="x")
        self._lbl_entry(r3, "Color N",  self.color_interval_var, width=5)
        self._lbl_entry(r3, "Pin Freq", self.marker_freq_var,    width=5)
        # Show all points toggle (OFF by default — can be slow on large tracks)
        self._dots_btn = self._mk_btn(vs, "⬤  Show All Points: OFF", C["dim"],
                                      self._toggle_show_dots, font=("Consolas",8,"bold"))
        self._dots_btn.pack(fill="x", pady=(6,0))

        self._sec_hdr(left, "FOCUS")
        fc = tk.Frame(left, bg=C["panel"]); fc.pack(fill="x", padx=10, pady=6)
        fr2 = tk.Frame(fc, bg=C["panel"]); fr2.pack(fill="x")
        self.foc_min_e = self._lbl_entry(fr2, "From", None, width=6)
        self.foc_max_e = self._lbl_entry(fr2, "To",   None, width=6)
        # Set Focus + Clear: half width each
        fr3 = tk.Frame(fc, bg=C["panel"]); fr3.pack(fill="x", pady=(4,0))
        self._mk_btn(fr3, "Set Focus", C["orange"], self.apply_focus).pack(side="left", expand=True, fill="x", padx=(0,2))
        self._mk_btn(fr3, "Clear",     C["dim"],    self.clear_focus).pack(side="left", expand=True, fill="x", padx=(2,0))

        self._sec_hdr(left, "FILTER")
        fl = tk.Frame(left, bg=C["panel"]); fl.pack(fill="x", padx=10, pady=6)

        # Grid layout: all rows share the same 4 columns → perfectly aligned
        fl.grid_columnconfigure(1, weight=1)
        fl.grid_columnconfigure(3, weight=1)
        _lkw = dict(font=("Consolas",8), bg=C["panel"], fg=C["muted"])
        _ekw = dict(bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
                    relief="flat", highlightthickness=1,
                    highlightcolor=C["accent"], highlightbackground=C["border"],
                    font=("Consolas",9))

        tk.Label(fl, text="Idx ≥", **_lkw).grid(row=0, column=0, sticky="w", padx=(0,4), pady=2)
        self.idx_min_e = tk.Entry(fl, width=8, **_ekw); self.idx_min_e.grid(row=0, column=1, sticky="ew", padx=(0,8), pady=2)
        tk.Label(fl, text="Idx ≤", **_lkw).grid(row=0, column=2, sticky="w", padx=(0,4), pady=2)
        self.idx_max_e = tk.Entry(fl, width=8, **_ekw); self.idx_max_e.grid(row=0, column=3, sticky="ew", pady=2)

        tk.Label(fl, text="Lat ≥", **_lkw).grid(row=1, column=0, sticky="w", padx=(0,4), pady=2)
        self.lat_min_e = tk.Entry(fl, width=8, **_ekw); self.lat_min_e.grid(row=1, column=1, sticky="ew", padx=(0,8), pady=2)
        tk.Label(fl, text="Lat ≤", **_lkw).grid(row=1, column=2, sticky="w", padx=(0,4), pady=2)
        self.lat_max_e = tk.Entry(fl, width=8, **_ekw); self.lat_max_e.grid(row=1, column=3, sticky="ew", pady=2)

        tk.Label(fl, text="Lon ≥", **_lkw).grid(row=2, column=0, sticky="w", padx=(0,4), pady=2)
        self.lon_min_e = tk.Entry(fl, width=8, **_ekw); self.lon_min_e.grid(row=2, column=1, sticky="ew", padx=(0,8), pady=2)
        tk.Label(fl, text="Lon ≤", **_lkw).grid(row=2, column=2, sticky="w", padx=(0,4), pady=2)
        self.lon_max_e = tk.Entry(fl, width=8, **_ekw); self.lon_max_e.grid(row=2, column=3, sticky="ew", pady=2)

        # Apply Filter + Clear: half width each — back to pack in a separate frame
        fl4 = tk.Frame(fl, bg=C["panel"]); fl4.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6,0))
        self._mk_btn(fl4, "Apply Filter", C["blue"], self.apply_filter).pack(side="left", expand=True, fill="x", padx=(0,2))
        self._mk_btn(fl4, "Clear",        C["dim"],  self.clear_filter).pack(side="left", expand=True, fill="x", padx=(2,0))

        self._sec_hdr(left, "BULK ACTIONS")
        ba = tk.Frame(left, bg=C["panel"]); ba.pack(fill="x", padx=10, pady=6)
        # Delete Filtered: full width
        ba1 = tk.Frame(ba, bg=C["panel"]); ba1.pack(fill="x", pady=2)
        self._mk_btn(ba1, "🗑  Delete Filtered", C["red"], self.bulk_delete_filtered).pack(fill="x")
        # Set Int Lat + Set Int Lon: half width each
        ba2 = tk.Frame(ba, bg=C["panel"]); ba2.pack(fill="x", pady=2)
        self._mk_btn(ba2, "Lat degrees", C["orange"], lambda: self.bulk_set_integer("lat")).pack(side="left", expand=True, fill="x", padx=(0,2))
        self._mk_btn(ba2, "Lon degrees", C["orange"], lambda: self.bulk_set_integer("lon")).pack(side="left", expand=True, fill="x", padx=(2,0))
        # Avg ALL + Avg LAT + Avg LON: one third each
        ba3 = tk.Frame(ba, bg=C["panel"])
        ba3.pack(fill="x", pady=2)

        # Configure the columns to be equal weight
        ba3.grid_columnconfigure(0, weight=1)
        ba3.grid_columnconfigure(1, weight=1)
        ba3.grid_columnconfigure(2, weight=1)

        self._mk_btn(ba3, "Avg ALL ✥", C["blue"],  lambda: self.average_between("both")).grid(row=0, column=0, sticky="ew", padx=(0,1))
        self._mk_btn(ba3, "Avg LAT ↕", C["green"], lambda: self.average_between("lat")).grid(row=0, column=1, sticky="ew", padx=(1,1))
        self._mk_btn(ba3, "Avg LON ↔", C["green"], lambda: self.average_between("lon")).grid(row=0, column=2, sticky="ew", padx=(1,0))  
        # Shift Time: full width
        ba4 = tk.Frame(ba, bg=C["panel"]); ba4.pack(fill="x", pady=2)
        self._mk_btn(ba4, "⏱  Shift Time", C["dim"], self.bulk_time_shift).pack(fill="x")
        # Edit Gap: full width
        ba5 = tk.Frame(ba, bg=C["panel"]); ba5.pack(fill="x", pady=2)
        self._mk_btn(ba5, "✂  Edit Gap", C["blue"], self.edit_gap).pack(fill="x")
        # Set Avg Speed: full width
        ba6 = tk.Frame(ba, bg=C["panel"]); ba6.pack(fill="x", pady=2)
        self._mk_btn(ba6, "⚡  Set Avg Speed", C["blue"], self.set_avg_speed).pack(fill="x")

        self._sec_hdr(left, "GEOCODER")
        gc = tk.Frame(left, bg=C["panel"]); gc.pack(fill="x", padx=10, pady=6)
        self._mk_btn(gc, "🌍  Open in Geocoder", C["green"], self._launch_geocoder_ui).pack(fill="x", pady=2)
        tk.Label(gc, text="Launches GPX Geocoder on the\ncurrently loaded file",
                 font=("Consolas",7), bg=C["panel"], fg=C["dim"],
                 justify="left").pack(anchor="w", padx=2)

        # Force scrollregion update after layout is fully resolved
        self.root.after(200, lambda: self._left_canvas.configure(
            scrollregion=self._left_canvas.bbox("all")))

        # ── CENTER — TREEVIEW ─────────────────────────────────────────────────
        center = tk.Frame(body, bg=C["bg"], width=440)
        center.pack(side="left", fill="y", padx=8, pady=10)
        center.pack_propagate(False)

        ch = tk.Frame(center, bg=C["bg"]); ch.pack(fill="x", pady=(0,4))
        tk.Label(ch, text="TRACK POINTS",
                 font=("Consolas",8,"bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        self._mk_btn(ch, "⊙ Center on Sel", C["panel2"],
                     self.center_on_selected, font=("Consolas",8)).pack(side="right")

        tree_border = tk.Frame(center, bg=C["accent"], padx=1, pady=1)
        tree_border.pack(fill="both", expand=True)
        tree_inner  = tk.Frame(tree_border, bg=C["panel2"])
        tree_inner.pack(fill="both", expand=True)

        cols = ("idx","dir","lat","lon","dist","speed","time")
        self.tree = ttk.Treeview(tree_inner, columns=cols, show="headings")
        widths    = {"idx":42,"dir":36,"lat":82,"lon":82,"dist":58,"speed":58,"time":68}
        for c in cols:
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=widths.get(c,65), anchor="center")
        self.tree.tag_configure("rogue",    background=C["rogue"], foreground="#ff8a80")
        self.tree.tag_configure("selected_rogue", background=C["accent"], foreground="black")
        self.tree.tag_configure("boundary", background="#0d2a4a", foreground="#64b5f6")

        tsb = ttk.Scrollbar(tree_inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # point count label
        self.pt_count_lbl = tk.Label(center, text="",
                                      font=("Consolas",8), bg=C["bg"], fg=C["muted"])
        self.pt_count_lbl.pack(anchor="w", pady=(3,0))

        # ── RIGHT — MAP ───────────────────────────────────────────────────────
        map_outer = tk.Frame(body, bg=C["bg"])
        map_outer.pack(side="left", fill="both", expand=True, padx=(0,10), pady=10)

        mh = tk.Frame(map_outer, bg=C["bg"]); mh.pack(fill="x", pady=(0,4))
        tk.Label(mh, text="TRACK MAP",
                 font=("Consolas",8,"bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        zf = tk.Frame(mh, bg=C["bg"]); zf.pack(side="right")
        self._zoom_level = [13]
        self._mk_btn(zf, "＋", C["panel2"], self._zoom_in,  font=("Consolas",11,"bold")).pack(side="left", padx=2)
        self._mk_btn(zf, "－", C["panel2"], self._zoom_out, font=("Consolas",11,"bold")).pack(side="left", padx=2)
        # Undo button
        self._mk_btn(zf, "↩ Undo", C["dim"], self.undo, font=("Consolas",8,"bold")).pack(side="left", padx=(8,2))
        # Drag mode toggle
        self._drag_btn_var = tk.StringVar(value="✋ Drag OFF")
        self._drag_btn = self._mk_btn(zf, "✋ Drag OFF", C["dim"], self._toggle_drag_mode,
                                       font=("Consolas",8,"bold"))
        self._drag_btn.pack(side="left", padx=2)

        map_border = tk.Frame(map_outer, bg=C["accent"], padx=2, pady=2)
        map_border.pack(fill="both", expand=True)
        self.map_widget = tkintermapview.TkinterMapView(map_border, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)
        self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
        self.map_widget.set_position(45.0, 7.0)
        self.map_widget.set_zoom(5)
        self.map_widget.add_left_click_map_command(self._on_map_click)
        # Save tkintermapview's original canvas bindings so we can restore them
        # when drag mode is toggled off (we replace them when drag is ON)
        canvas = self.map_widget.canvas
        self._map_orig_press   = canvas.bind("<ButtonPress-1>")
        self._map_orig_motion  = canvas.bind("<B1-Motion>")
        self._map_orig_release = canvas.bind("<ButtonRelease-1>")
        # Redraw point dots after pan and after tile redraws (only when dots are enabled)
        canvas.bind("<ButtonRelease-1>", lambda e: self.show_dots_var.get() and self.root.after(80,  self._draw_point_dots), add="+")
        canvas.bind("<Configure>",       lambda e: self.show_dots_var.get() and self.root.after(150, self._draw_point_dots), add="+")
        # Ctrl+Z undo, Ctrl+D drag toggle
        self.root.bind("<Control-z>", self.undo)
        self.root.bind("<Control-Z>", self.undo)
        self.root.bind("<Control-d>", lambda e: self._toggle_drag_mode())
        self.root.bind("<Control-D>", lambda e: self._toggle_drag_mode())

        # ── STATUS BAR ────────────────────────────────────────────────────────
        sb = tk.Frame(self.root, bg=C["panel"], height=26)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        self.status_lbl = tk.Label(sb, text="Ready. Open a GPX file to begin.",
                                    font=("Consolas",8), bg=C["panel"], fg=C["muted"])
        self.status_lbl.pack(side="left", padx=10, pady=3)
        self.dirty_lbl = tk.Label(sb, text="",
                                   font=("Consolas",8,"bold"), bg=C["panel"], fg=C["orange"])
        self.dirty_lbl.pack(side="right", padx=10, pady=3)

    # ── ZOOM ───────────────────────────────────────────────────────────────────
    def _zoom_in(self):
        self._zoom_level[0] = min(self._zoom_level[0]+1, 19)
        self.map_widget.set_zoom(self._zoom_level[0])
        if self.show_dots_var.get():
            self.root.after(200, self._draw_point_dots)

    def _zoom_out(self):
        self._zoom_level[0] = max(self._zoom_level[0]-1, 2)
        self.map_widget.set_zoom(self._zoom_level[0])
        if self.show_dots_var.get():
            self.root.after(200, self._draw_point_dots)

    def _toggle_show_dots(self):
        self.show_dots_var.set(not self.show_dots_var.get())
        if self.show_dots_var.get():
            self._dots_btn.config(text="⬤  Show All Points: ON",  bg=C["orange"])
            self._draw_point_dots()
        else:
            self._dots_btn.config(text="⬤  Show All Points: OFF", bg=C["dim"])
            self._erase_point_dots()

    _PT_DOT_TAG  = "pt_dot"

    def _erase_point_dots(self):
        try: self.map_widget.canvas.delete(self._PT_DOT_TAG)
        except Exception: pass

    def _latlon_to_canvas(self, lat, lon):
        import math
        mw    = self.map_widget
        zoom  = round(mw.zoom)
        n     = 2.0 ** zoom
        lat_r = math.radians(lat)
        tx    = (lon + 180.0) / 360.0 * n
        ty    = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
        ul_x, ul_y = mw.upper_left_tile_pos
        ts    = mw.tile_size
        return (tx - ul_x) * ts, (ty - ul_y) * ts

    def _draw_point_dots(self):
        self._erase_point_dots()
        idxs = getattr(self, "_draw_point_dots_idxs", None)
        if not idxs or not self.points: return
        canvas = self.map_widget.canvas
        for i in idxs:
            try:
                x, y = self._latlon_to_canvas(self.points[i][0], self.points[i][1])
                # white halo (outer ring)
                canvas.create_oval(x-4, y-4, x+4, y+4,
                                   fill="white", outline="white", width=0,
                                   tags=self._PT_DOT_TAG)
                # black centre dot
                canvas.create_oval(x-2, y-2, x+2, y+2,
                                   fill="black", outline="black", width=0,
                                   tags=self._PT_DOT_TAG)
            except Exception:
                pass
        # raise above tile images so dots are always visible
        canvas.tag_raise(self._PT_DOT_TAG)

    def _toggle_drag_mode(self):
        self._drag_mode = not self._drag_mode
        canvas = self.map_widget.canvas
        if self._drag_mode:
            # Replace map's pan handlers entirely — no add, so ours are the only ones
            canvas.bind("<ButtonPress-1>",   self._drag_press)
            canvas.bind("<B1-Motion>",       self._drag_motion)
            canvas.bind("<ButtonRelease-1>", self._drag_release)
            self._drag_btn.config(text="✋ Drag ON", bg=C["orange"])
            self._set_status("Drag mode ON — click & drag a track point to reposition it.")
        else:
            # Restore tkintermapview's original pan handlers
            canvas.bind("<ButtonPress-1>",   self._map_orig_press)
            canvas.bind("<B1-Motion>",       self._map_orig_motion)
            canvas.bind("<ButtonRelease-1>", self._map_orig_release)
            self._drag_btn.config(text="✋ Drag OFF", bg=C["dim"])
            self._drag_idx = None
            if self._drag_marker:
                try: self._drag_marker.delete()
                except: pass
                self._drag_marker = None
            self._set_status("Drag mode OFF.")

    def _canvas_to_latlon(self, x, y):
        """Convert canvas pixel coords to (lat, lon) via tkintermapview internals."""
        return self.map_widget.convert_canvas_coords_to_decimal_coords(x, y)

    def _drag_press(self, event):
        if not self._drag_mode or not self.points: return
        try:
            click_lat, click_lon = self._canvas_to_latlon(event.x, event.y)
        except Exception: return
        visible = self._get_visible_indices()
        if not visible: return
        self._drag_idx = min(visible,
                             key=lambda i: haversine(click_lat, click_lon,
                                                     self.points[i][0], self.points[i][1]))
        p = self.points[self._drag_idx]
        # place a bright marker at the grabbed point
        if self._drag_marker:
            try: self._drag_marker.delete()
            except: pass
        self._drag_marker = self.map_widget.set_marker(p[0], p[1],
                                                        text=f"#{self._drag_idx}",
                                                        marker_color_circle=C["red"],
                                                        marker_color_outside=C["accent"])
        self._set_status(f"Dragging point #{self._drag_idx}…")

    def _drag_motion(self, event):
        if not self._drag_mode or self._drag_idx is None: return
        try:
            lat, lon = self._canvas_to_latlon(event.x, event.y)
        except Exception: return
        # move the live marker to follow the cursor
        if self._drag_marker:
            try: self._drag_marker.delete()
            except: pass
        self._drag_marker = self.map_widget.set_marker(lat, lon,
                                                        text=f"#{self._drag_idx}",
                                                        marker_color_circle=C["red"],
                                                        marker_color_outside=C["accent"])

    def _drag_release(self, event):
        if not self._drag_mode or self._drag_idx is None: return
        try:
            lat, lon = self._canvas_to_latlon(event.x, event.y)
        except Exception:
            self._drag_idx = None; return
        idx = self._drag_idx
        self._drag_idx = None
        # remove live marker
        if self._drag_marker:
            try: self._drag_marker.delete()
            except: pass
            self._drag_marker = None
        # commit — keep timestamp, update coords
        self._push_undo()
        _, __, t = self.points[idx]
        self.points[idx] = (lat, lon, t)
        self._mark_dirty()
        move_msg = f"Point #{idx} moved → ({lat:.7f}, {lon:.7f})"
        self.refresh_map_and_tree()
        self._toggle_drag_mode()   # auto-reset to OFF after each move
        self._set_status(move_msg)

    # ── STATUS ─────────────────────────────────────────────────────────────────
    def _set_status(self, msg):
        self.status_lbl.config(text=msg)
    def _mark_dirty(self):
        self._dirty = True
        self.dirty_lbl.config(text="● unsaved changes")
    def _mark_clean(self):
        self._dirty = False
        self.dirty_lbl.config(text="")

    def _push_undo(self):
        """Snapshot current points onto the undo stack (max 30 levels)."""
        self._undo_stack.append(list(self.points))
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def undo(self, _event=None):
        if not self._undo_stack:
            self._set_status("Nothing to undo."); return
        self.points = self._undo_stack.pop()
        self._mark_dirty()
        self._set_status(f"Undo — {len(self._undo_stack)} level(s) remaining.")
        self.refresh_map_and_tree()

    # ── AUTO-SAVE ──────────────────────────────────────────────────────────────
    def _schedule_autosave(self):
        self._do_autosave_check()

    def _do_autosave_check(self):
        if self._dirty and self.points and self._file_segments:
            elapsed = time.time() - self._last_autosave
            if elapsed >= AUTOSAVE_SECS:
                self._write_temp()
        self.root.after(60_000, self._do_autosave_check)

    def _write_temp(self):
        try:
            stem    = os.path.splitext(self.source_path)[0]
            # remove any previous _temp suffix before adding a fresh one
            if stem.endswith("_temp"):
                stem = stem[:-5]
            tmp_path = stem + "_temp.gpx"
            self._save_to_path(tmp_path)
            self._last_autosave  = time.time()
            self._last_temp_path = tmp_path
            ts = datetime.now().strftime("%H:%M:%S")
            self.autosave_lbl.config(text=f"💾 auto-saved {ts}")
            self._set_status(f"Auto-saved temp → {os.path.basename(tmp_path)}")
        except Exception as e:
            self.autosave_lbl.config(text="⚠ auto-save failed")

    # ── FILE OPS ───────────────────────────────────────────────────────────────
    def select_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("GPX","*.gpx")])
        if not paths: return
        if len(paths) == 1:
            self._load_file(paths[0])
        else:
            self._load_multiple(list(paths))

    def _load_file(self, path):
        """Load a single GPX file by path."""
        try:
            with open(path, "r", encoding="utf-8") as f: gpx = gpxpy.parse(f)
        except Exception as e:
            messagebox.showerror("Load error", f"Failed to parse GPX:\n{e}"); return
        pts = [(p.latitude, p.longitude, p.time)
               for t in gpx.tracks for s in t.segments for p in s.points]
        self._make_backup(path)
        self.points           = pts
        self._file_segments   = [{"path": path, "count": len(pts)}]
        self.source_path      = path
        self.current_filename = os.path.basename(path)
        self.file_lbl.config(text=self.current_filename)
        self._mark_clean(); self._last_autosave = time.time(); self.autosave_lbl.config(text="")
        self._set_status(f"Loaded {len(pts)} points  ·  {self.current_filename}")
        self._pending_center = ("fit",)
        self.refresh_map_and_tree()

    def _load_multiple(self, paths):
        """Load and merge multiple GPX files."""
        all_pts = []; segments = []; errors = []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as f: gpx = gpxpy.parse(f)
                pts = [(p.latitude, p.longitude, p.time)
                       for t in gpx.tracks for s in t.segments for p in s.points]
                self._make_backup(path)
                segments.append({"path": path, "count": len(pts)})
                all_pts.extend(pts)
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
        if errors:
            messagebox.showwarning("Load errors", "\n".join(errors))
        if not all_pts: return
        self.points           = all_pts
        self._file_segments   = segments
        self.source_path      = paths[0]
        names = " + ".join(os.path.basename(p) for p in paths)
        self.current_filename = names
        self.file_lbl.config(text=names, wraplength=240)
        self._mark_clean(); self._last_autosave = time.time(); self.autosave_lbl.config(text="")
        self._set_status(f"Loaded {len(all_pts)} pts from {len(segments)} files")
        self._pending_center = ("fit",)
        self.refresh_map_and_tree()

    def _make_backup(self, path):
        """Create a _backup copy of a file if one doesn't already exist."""
        import shutil
        stem, ext = os.path.splitext(path)
        if stem.endswith("_backup"): return
        backup_path = stem + "_backup" + ext
        if not os.path.exists(backup_path):
            try:
                shutil.copy2(path, backup_path)
            except Exception:
                pass

    def _save_to_path(self, path, pts=None):
        """Write pts (or self.points) to a GPX file."""
        if pts is None: pts = self.points
        gpx = gpxpy.gpx.GPX()
        track = gpxpy.gpx.GPXTrack(); gpx.tracks.append(track)
        seg   = gpxpy.gpx.GPXTrackSegment(); track.segments.append(seg)
        for p in pts:
            seg.points.append(gpxpy.gpx.GPXTrackPoint(p[0], p[1], time=p[2]))
        with open(path, "w", encoding="utf-8") as f: f.write(gpx.to_xml())

    def _write_temp(self):
        """Auto-save: write one _temp.gpx per original file, maintaining segment splits."""
        try:
            saved = []
            offset = 0
            for seg in self._file_segments:
                pts  = self.points[offset:offset + seg["count"]]
                stem = os.path.splitext(seg["path"])[0]
                if stem.endswith("_temp"): stem = stem[:-5]
                tmp  = stem + "_temp.gpx"
                self._save_to_path(tmp, pts)
                saved.append(os.path.basename(tmp))
                offset += seg["count"]
            self._last_autosave  = time.time()
            self._last_temp_path = saved[0] if len(saved) == 1 else ""
            ts = datetime.now().strftime("%H:%M:%S")
            self.autosave_lbl.config(text=f"💾 auto-saved {ts}")
            self._set_status("Auto-saved: " + ", ".join(saved))
        except Exception:
            self.autosave_lbl.config(text="⚠ auto-save failed")

    def export_clean_gpx(self):
        if not self.points: messagebox.showwarning("Empty","No points to save."); return
        multi = len(self._file_segments) > 1

        if multi:
            # Ask: merged or separate
            d = tk.Toplevel(self.root)
            d.title("Save options"); d.configure(bg=C["bg"]); d.resizable(False,False)
            d.grab_set()
            tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")
            tk.Label(d, text="SAVE FORMAT", font=("Consolas",10,"bold"),
                     bg=C["bg"], fg=C["accent"]).pack(padx=20, pady=(14,4), anchor="w")
            tk.Label(d, text=f"{len(self._file_segments)} files loaded — how to save?",
                     font=("Consolas",8), bg=C["bg"], fg=C["muted"]).pack(padx=20, anchor="w", pady=(0,10))
            tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=20)
            mode_var = tk.IntVar(value=1)
            _rkw = dict(bg=C["bg"], fg=C["text"], activebackground=C["bg"],
                        activeforeground=C["accent"], selectcolor=C["accent2"],
                        font=("Consolas",9), anchor="w", relief="flat")
            rf = tk.Frame(d, bg=C["bg"]); rf.pack(fill="x", padx=20, pady=10)
            tk.Radiobutton(rf, text="💾  Single merged file  (default)",
                           variable=mode_var, value=1, **_rkw).pack(fill="x", pady=3)
            tk.Radiobutton(rf, text="📂  Separate files  (original split)",
                           variable=mode_var, value=2, **_rkw).pack(fill="x", pady=3)
            chosen = [None]
            def _ok():   chosen[0] = mode_var.get(); d.destroy()
            def _cancel(): d.destroy()
            tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=20)
            bf = tk.Frame(d, bg=C["bg"]); bf.pack(padx=20, pady=12)
            self._mk_btn(bf, "Save", C["green"], _ok).pack(side="left", padx=(0,8))
            self._mk_btn(bf, "Cancel", C["dim"], _cancel).pack(side="left")
            tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")
            d.bind("<Return>", lambda e: _ok())
            d.bind("<Escape>", lambda e: _cancel())
            self.root.wait_window(d)
            if chosen[0] is None: return
            save_separate = (chosen[0] == 2)
        else:
            save_separate = False

        if save_separate:
            # Save each segment back to a user-chosen name per file
            offset = 0
            saved = []
            for seg in self._file_segments:
                pts  = self.points[offset:offset + seg["count"]]
                stem = os.path.splitext(os.path.basename(seg["path"]))[0]
                def_name = stem + "_ironed.gpx"
                path = filedialog.asksaveasfilename(
                    defaultextension=".gpx", initialfile=def_name,
                    title=f"Save {os.path.basename(seg['path'])}",
                    filetypes=[("GPX","*.gpx")])
                if path:
                    self._save_to_path(path, pts)
                    saved.append(os.path.basename(path))
                offset += seg["count"]
            if saved:
                self._clean_temps()
                self._mark_clean()
                self._set_status("Saved: " + ", ".join(saved))
        else:
            # Single merged file
            stem = os.path.splitext(self.current_filename.split(" + ")[0])[0]
            if len(self._file_segments) > 1:
                stem = stem + "_merged"
            def_name = stem + "_ironed.gpx"
            path = filedialog.asksaveasfilename(
                defaultextension=".gpx", initialfile=def_name,
                filetypes=[("GPX","*.gpx")])
            if not path: return
            self._save_to_path(path)
            self._clean_temps()
            self._mark_clean()
            self._set_status(f"Saved → {os.path.basename(path)}")

    def _clean_temps(self):
        """Delete all _temp.gpx files created by auto-save."""
        for seg in self._file_segments:
            stem = os.path.splitext(seg["path"])[0]
            if stem.endswith("_temp"): stem = stem[:-5]
            tmp = stem + "_temp.gpx"
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except: pass
        if self._last_temp_path and os.path.exists(self._last_temp_path):
            try: os.remove(self._last_temp_path)
            except: pass
        self._last_temp_path = ""
        self.autosave_lbl.config(text="")

    # ── IRONING ────────────────────────────────────────────────────────────────
    def auto_iron(self):
        if not self.points: return
        try: threshold = float(self.max_kph_iron.get())
        except: threshold = 5000.0
        cleaned = list(self.points)
        count   = 0
        for i in range(1, len(cleaned)):
            if speed_kph_between(cleaned[i-1], cleaned[i]) > threshold:
                cleaned[i] = (splice_decimals(cleaned[i-1][0], cleaned[i][0]),
                              splice_decimals(cleaned[i-1][1], cleaned[i][1]),
                              cleaned[i][2])
                count += 1
        self.points = cleaned
        self._push_undo()
        self._mark_dirty()
        self._set_status(f"Auto-iron: {count} point(s) corrected.")
        self.refresh_map_and_tree()

    def bridge_logic(self):
        if len(self.points) < 3: return
        try: threshold = float(self.max_kph_bridge.get())
        except: threshold = 200.0
        new_pts = list(self.points); count = 0
        for i in range(1, len(new_pts)-1):
            s1 = speed_kph_between(new_pts[i-1], new_pts[i])
            s2 = speed_kph_between(new_pts[i],   new_pts[i+1])
            if s1 > threshold and s2 > threshold:
                if speed_kph_between(new_pts[i-1], new_pts[i+1]) < threshold:
                    new_pts[i] = ((new_pts[i-1][0]+new_pts[i+1][0])/2,
                                  (new_pts[i-1][1]+new_pts[i+1][1])/2,
                                  new_pts[i][2])
                    count += 1
        self.points = new_pts
        self._push_undo()
        self._mark_dirty()
        self.refresh_map_and_tree()

    def self_correct(self):
        """Run auto-iron then bridge in sequence, restricted to visible (filtered/focused) points."""
        if not self.points: return
        self._push_undo()

        visible    = self._get_visible_indices()
        visible_s  = set(visible)          # O(1) membership test
        scope_desc = ("filtered/focused section" if (self.filtered_indices is not None
                       or self.focus_range) else "full track")

        # ── iron pass — only correct points that are in scope ─────────────────
        try: iron_t = float(self.max_kph_iron.get())
        except: iron_t = 5000.0
        cleaned = list(self.points); iron_count = 0
        for i in visible:
            if i == 0: continue
            if speed_kph_between(cleaned[i-1], cleaned[i]) > iron_t:
                cleaned[i] = (splice_decimals(cleaned[i-1][0], cleaned[i][0]),
                              splice_decimals(cleaned[i-1][1], cleaned[i][1]),
                              cleaned[i][2])
                iron_count += 1
        self.points = cleaned

        # ── bridge pass — only bridge points that are in scope ────────────────
        try: bridge_t = float(self.max_kph_bridge.get())
        except: bridge_t = 200.0
        new_pts = list(self.points); bridge_count = 0
        for i in visible:
            if i == 0 or i >= len(new_pts) - 1: continue
            if i not in visible_s: continue
            s1 = speed_kph_between(new_pts[i-1], new_pts[i])
            s2 = speed_kph_between(new_pts[i],   new_pts[i+1])
            if s1 > bridge_t and s2 > bridge_t:
                if speed_kph_between(new_pts[i-1], new_pts[i+1]) < bridge_t:
                    new_pts[i] = ((new_pts[i-1][0]+new_pts[i+1][0])/2,
                                  (new_pts[i-1][1]+new_pts[i+1][1])/2,
                                  new_pts[i][2])
                    bridge_count += 1
        self.points = new_pts
        self._mark_dirty()
        self._set_status(
            f"Self-correct ({scope_desc}): {iron_count} ironed, {bridge_count} bridged.")
        self.refresh_map_and_tree()
    def refresh_map_and_tree(self):
        # Sync zoom from widget — catches scroll-wheel zoom that bypasses our buttons
        try:
            actual_zoom = self.map_widget.zoom
            if actual_zoom: self._zoom_level[0] = int(actual_zoom)
        except Exception: pass

        self.tree.delete(*self.tree.get_children())
        visible = self._get_visible_indices()
        try: threshold = float(self.max_kph_iron.get())
        except: threshold = 5000.0

        # build set of boundary start indices for O(1) lookup
        boundary_starts = set()
        if self._file_segments:
            idx = 0
            for seg in self._file_segments[1:]:   # first file's point 0 is not highlighted
                idx += self._file_segments[self._file_segments.index(seg)-1]["count"]
                boundary_starts.add(idx)

        # rebuild boundary_starts properly (cumulative)
        boundary_starts = set()
        cum = 0
        for seg in self._file_segments:
            if cum > 0:
                boundary_starts.add(cum)
            cum += seg["count"]

        for i in visible:
            p = self.points[i]
            d_s = s_s = rogue = dir_str = ""
            rogue = False
            if i > 0:
                d     = haversine(self.points[i-1][0], self.points[i-1][1], p[0], p[1])
                s     = speed_kph_between(self.points[i-1], p)
                d_s   = f"{d:.2f}m"
                s_s   = f"{s:.1f}kph"
                rogue = s > threshold
                dir_str = get_dir_indicator(self.points[i-1], p)
            ts = p[2].strftime("%H:%M:%S") if p[2] else ""
            if i in boundary_starts:
                tag = ("boundary",)
            elif rogue:
                tag = ("rogue",)
            else:
                tag = ()
            self.tree.insert("", "end",
                             values=(i, dir_str, f"{p[0]:.7f}", f"{p[1]:.7f}", d_s, s_s, ts),
                             tags=tag)

        self.pt_count_lbl.config(text=f"{len(visible)} points shown  ·  {len(self.points)} total")

        self.map_widget.delete_all_path()
        self.map_widget.delete_all_marker()
        if self._sel_marker:
            try: self._sel_marker.delete()
            except: pass
            self._sel_marker = None
        if not self.points: return

        draw_idxs = (range(self.focus_range[0], min(self.focus_range[1]+1, len(self.points)))
                     if self.focus_range else range(len(self.points)))
        try: color_n = max(1, int(self.color_interval_var.get()))
        except: color_n = 100

        curr_seg = []
        for i in draw_idxs:
            curr_seg.append((self.points[i][0], self.points[i][1]))
            if len(curr_seg) >= color_n or i == list(draw_idxs)[-1]:
                self.map_widget.set_path(curr_seg,
                                         color=SEGMENT_COLORS[(i//color_n) % len(SEGMENT_COLORS)],
                                         width=3)
                curr_seg = [(self.points[i][0], self.points[i][1])]

        try: mark_f = int(self.marker_freq_var.get())
        except: mark_f = 10

        # Draw labeled pins at the configured frequency
        if mark_f > 0:
            for i in draw_idxs:
                if i % mark_f == 0:
                    self.map_widget.set_marker(self.points[i][0], self.points[i][1], text=str(i))

        # Canvas dots for every visible point — only when enabled (can be slow on large tracks)
        self._draw_point_dots_idxs = list(draw_idxs)
        if self.show_dots_var.get():
            self.root.after(120, self._draw_point_dots)
        else:
            self._erase_point_dots()

        # center map only when explicitly requested via _pending_center;
        # otherwise leave the map exactly where it is (tkintermapview does not
        # auto-refit on set_path / set_marker, so nothing needs restoring)
        if self._pending_center and self.points:
            kind = self._pending_center[0]
            if kind == "fit":
                lats = [p[0] for p in self.points]; lons = [p[1] for p in self.points]
                center = ((min(lats)+max(lats))/2, (min(lons)+max(lons))/2)
                self.map_widget.set_position(*center)
                span = max(max(lats)-min(lats), max(lons)-min(lons))
                z = 7 if span>5 else 9 if span>2 else 10 if span>1 else 12 if span>0.3 else 13 if span>0.1 else 14
                self._zoom_level[0] = z; self.map_widget.set_zoom(z)
            elif kind == "point":
                _, lat, lon, zoom = self._pending_center
                self.map_widget.set_position(lat, lon)
                self._zoom_level[0] = zoom; self.map_widget.set_zoom(zoom)
            self._pending_center = None

    def _get_visible_indices(self):
        base = sorted(list(self.filtered_indices)) if self.filtered_indices is not None \
               else list(range(len(self.points)))
        if self.focus_range:
            return [i for i in base if self.focus_range[0] <= i <= self.focus_range[1]]
        return base

    # ── FILTER / FOCUS ─────────────────────────────────────────────────────────
    def apply_filter(self):
        def fv(e):
            try: return float(e.get()) if e.get().strip() else None
            except: return None
        def iv(e):
            try: return int(e.get()) if e.get().strip() else None
            except: return None
        lmn,lmx,omn,omx = fv(self.lat_min_e),fv(self.lat_max_e),fv(self.lon_min_e),fv(self.lon_max_e)
        imn,imx = iv(self.idx_min_e), iv(self.idx_max_e)
        self.filtered_indices = {
            i for i,p in enumerate(self.points)
            if (lmn is None or p[0]>=lmn) and (lmx is None or p[0]<=lmx)
            and (omn is None or p[1]>=omn) and (omx is None or p[1]<=omx)
            and (imn is None or i>=imn)    and (imx is None or i<=imx)
        }
        self._set_status(f"Filter active: {len(self.filtered_indices)} points match.")
        self.refresh_map_and_tree()

    def clear_filter(self):
        self.filtered_indices = None
        self._set_status("Filter cleared.")
        self.refresh_map_and_tree()

    def apply_focus(self):
        try:
            self.focus_range = (int(self.foc_min_e.get()), int(self.foc_max_e.get()))
            first_idx = self.focus_range[0]
            if 0 <= first_idx < len(self.points):
                p = self.points[first_idx]
                self._pending_center = ("point", p[0], p[1], 15)
            self._set_status(f"Focus: {self.focus_range[0]} → {self.focus_range[1]}")
            self.refresh_map_and_tree()
        except: pass

    def clear_focus(self):
        self.focus_range = None
        self._set_status("Focus cleared.")
        self.refresh_map_and_tree()

    # ── BULK OPS ───────────────────────────────────────────────────────────────
    def bulk_set_integer(self, mode):
        idxs = self._get_visible_indices()
        val  = simpledialog.askinteger("Set integer", f"New integer for {mode.upper()}:")
        if val is None: return
        self._push_undo()
        for i in idxs:
            lat, lon, t = self.points[i]
            coord = lat if mode=="lat" else lon
            frac  = abs(math.modf(coord)[0])
            new   = val + frac if val >= 0 else val - frac
            self.points[i] = (new, lon, t) if mode=="lat" else (lat, new, t)
        self._mark_dirty()
        self.refresh_map_and_tree()

    def average_between(self, mode):
        sel = self.tree.selection()
        if len(sel) != 2:
            messagebox.showinfo("Avg", "Select exactly 2 points in the table."); return
        i0,i1 = sorted([int(self.tree.item(s)["values"][0]) for s in sel])
        pA, pB = self.points[i0], self.points[i1]
        self._push_undo()
        for offset in range(1, i1-i0):
            i, f = i0+offset, offset/(i1-i0)
            lat = pA[0]+f*(pB[0]-pA[0]) if mode in ("both","lat") else self.points[i][0]
            lon = pA[1]+f*(pB[1]-pA[1]) if mode in ("both","lon") else self.points[i][1]
            self.points[i] = (lat, lon, self.points[i][2])
        self._mark_dirty()
        self._set_status(f"Averaged {i1-i0-1} points ({mode}).")
        self.refresh_map_and_tree()

    def bulk_delete_filtered(self):
        idxs = set(self._get_visible_indices())
        if not idxs: return
        if messagebox.askyesno("Delete", f"Delete {len(idxs)} points?"):
            self._push_undo()
            self.points = [p for i,p in enumerate(self.points) if i not in idxs]
            self._mark_dirty()
            self._set_status(f"Deleted {len(idxs)} points. {len(self.points)} remain.")
            self.refresh_map_and_tree()

    def bulk_time_shift(self):
        # find current first timestamp for context
        first_ts = next((p[2] for p in self.points if p[2] is not None), None)
        first_str = first_ts.strftime("%H:%M:%S") if first_ts else "unknown"

        d = tk.Toplevel(self.root)
        d.title("Shift Time")
        d.configure(bg=C["bg"]); d.resizable(False, False)
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")
        tk.Label(d, text="SHIFT TIMESTAMPS",
                 font=("Consolas",9,"bold"), bg=C["bg"], fg=C["accent"]).pack(
                 padx=16, pady=(14,2), anchor="w")
        tk.Label(d, text=f"First point timestamp: {first_str}   ·   Applies to all points.",
                 font=("Consolas",8), bg=C["bg"], fg=C["muted"]).pack(padx=16, anchor="w", pady=(0,10))
        tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=16, pady=(0,10))

        # mode radio buttons
        dir_var = tk.StringVar(value="add")
        df = tk.Frame(d, bg=C["bg"]); df.pack(padx=16, pady=(0,8), fill="x")
        _rkw = dict(bg=C["bg"], fg=C["text"], activebackground=C["bg"],
                    activeforeground=C["accent"], selectcolor=C["accent2"],
                    font=("Consolas",9), anchor="w", relief="flat")
        tk.Radiobutton(df, text="➕  Add time",         variable=dir_var, value="add",    **_rkw).pack(fill="x", pady=2)
        tk.Radiobutton(df, text="➖  Deduct time",       variable=dir_var, value="deduct", **_rkw).pack(fill="x", pady=2)
        tk.Radiobutton(df, text="🕐  Set start time",   variable=dir_var, value="setstart", **_rkw).pack(fill="x", pady=2)

        # entry row — label changes depending on mode
        ef = tk.Frame(d, bg=C["bg"]); ef.pack(padx=16, pady=(4,4))
        entry_lbl = tk.Label(ef, text="Offset (HH:MM:SS):", font=("Consolas",9),
                              bg=C["bg"], fg=C["text"], width=20, anchor="w")
        entry_lbl.pack(side="left", padx=(0,8))
        off_var = tk.StringVar(value="01:00:00")
        off_e = ttk.Entry(ef, textvariable=off_var, width=12, font=("Consolas",10))
        off_e.pack(side="left")
        off_e.select_range(0, "end"); off_e.focus_set()

        preview_lbl = tk.Label(d, text="", font=("Consolas",8), bg=C["bg"], fg=C["muted"])
        preview_lbl.pack(padx=16, anchor="w", pady=(4,10))

        def _update_label(*_):
            mode = dir_var.get()
            if mode == "setstart":
                entry_lbl.config(text="New start (HH:MM:SS):")
            else:
                entry_lbl.config(text="Offset (HH:MM:SS):")
            _preview()

        def _preview(*_):
            mode = dir_var.get()
            raw  = off_var.get().strip()
            try:
                parts = list(map(int, raw.split(":")))
                if len(parts) != 3: raise ValueError
                h, m, s = parts
                if not (0 <= m < 60 and 0 <= s < 60): raise ValueError
                if mode == "add":
                    preview_lbl.config(text=f"→ all timestamps +{h:02d}:{m:02d}:{s:02d}", fg=C["muted"])
                elif mode == "deduct":
                    preview_lbl.config(text=f"→ all timestamps −{h:02d}:{m:02d}:{s:02d}", fg=C["muted"])
                else:  # setstart
                    if first_ts is None:
                        preview_lbl.config(text="no existing timestamps to anchor to", fg=C["red"])
                        return
                    from datetime import datetime as _dt
                    new_start = first_ts.replace(hour=h, minute=m, second=s, microsecond=0)
                    delta_s   = (new_start - first_ts).total_seconds()
                    sign      = "+" if delta_s >= 0 else "−"
                    dh, rem   = divmod(abs(int(delta_s)), 3600)
                    dm, ds    = divmod(rem, 60)
                    preview_lbl.config(
                        text=f"→ start set to {h:02d}:{m:02d}:{s:02d}  "
                             f"(shift {sign}{dh:02d}:{dm:02d}:{ds:02d})", fg=C["muted"])
            except Exception:
                preview_lbl.config(text="invalid — use HH:MM:SS", fg=C["red"])

        off_var.trace_add("write", _preview)
        dir_var.trace_add("write", _update_label)
        _preview()

        def _apply():
            mode = dir_var.get()
            raw  = off_var.get().strip()
            try:
                parts = list(map(int, raw.split(":")))
                if len(parts) != 3: raise ValueError
                h, m, s = parts
                if not (0 <= m < 60 and 0 <= s < 60): raise ValueError
            except Exception:
                messagebox.showerror("Invalid input", "Use HH:MM:SS format.", parent=d)
                return

            if mode == "setstart":
                if first_ts is None:
                    messagebox.showerror("No timestamps", "No existing timestamps to shift from.", parent=d)
                    return
                new_start = first_ts.replace(hour=h, minute=m, second=s, microsecond=0)
                delta = new_start - first_ts
                status_msg = f"Start time set to {h:02d}:{m:02d}:{s:02d}."
            else:
                delta = timedelta(hours=h, minutes=m, seconds=s)
                if mode == "deduct":
                    delta = -delta
                sign = "+" if mode == "add" else "−"
                status_msg = f"Timestamps shifted {sign}{h:02d}:{m:02d}:{s:02d}."

            self._push_undo()
            self.points = [(p[0], p[1], p[2] + delta if p[2] else None) for p in self.points]
            self._mark_dirty()
            self._set_status(status_msg)
            d.destroy()
            self.refresh_map_and_tree()

        tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=16)
        bf = tk.Frame(d, bg=C["bg"]); bf.pack(padx=16, pady=12)
        self._mk_btn(bf, "Apply", C["green"], _apply).pack(side="left", padx=(0,6))
        self._mk_btn(bf, "Cancel", C["dim"], d.destroy).pack(side="left")
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        d.bind("<Return>", lambda e: _apply())
        d.bind("<Escape>", lambda e: d.destroy())
        d.grab_set()

    def edit_gap(self):
        """Set a new time gap between 2 selected contiguous points,
        shifting all subsequent points by the resulting delta."""
        sel = self.tree.selection()
        if len(sel) != 2:
            messagebox.showerror("Edit Gap", "Select exactly 2 points in the table."); return
        i0, i1 = sorted([int(self.tree.item(s)["values"][0]) for s in sel])
        if i1 - i0 != 1:
            messagebox.showerror("Edit Gap",
                f"Points must be contiguous.\n#{i0} and #{i1} are {i1-i0} apart."); return

        t0, t1 = self.points[i0][2], self.points[i1][2]
        if t0 is None or t1 is None:
            messagebox.showerror("Edit Gap", "Both points must have timestamps."); return

        cur_secs = int((t1 - t0).total_seconds())
        cur_m, cur_s = divmod(abs(cur_secs), 60)

        # ── dialog ────────────────────────────────────────────────────────────
        d = tk.Toplevel(self.root)
        d.title(f"Edit gap  #{i0} → #{i1}")
        d.configure(bg=C["bg"]); d.resizable(False, False)
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")

        tk.Label(d, text=f"Gap between point #{i0} and #{i1}",
                 font=("Consolas",9,"bold"), bg=C["bg"], fg=C["accent"]).pack(padx=16, pady=(14,2), anchor="w")
        tk.Label(d, text=f"Current gap: {cur_m}:{cur_s:02d}",
                 font=("Consolas",8), bg=C["bg"], fg=C["muted"]).pack(padx=16, anchor="w", pady=(0,10))

        ef = tk.Frame(d, bg=C["bg"]); ef.pack(padx=16, pady=(0,4))
        tk.Label(ef, text="New gap  (m:ss or mss):", font=("Consolas",9),
                 bg=C["bg"], fg=C["text"]).pack(side="left", padx=(0,8))
        gap_var = tk.StringVar(value=f"{cur_m}:{cur_s:02d}")
        gap_e = ttk.Entry(ef, textvariable=gap_var, width=10, font=("Consolas",10))
        gap_e.pack(side="left")
        gap_e.select_range(0, "end")
        gap_e.focus_set()

        info_lbl = tk.Label(d, text="", font=("Consolas",8), bg=C["bg"], fg=C["muted"])
        info_lbl.pack(padx=16, anchor="w", pady=(2,8))

        def _parse_gap(raw):
            """Return total seconds or raise ValueError."""
            raw = raw.strip().replace(" ", "")
            if ":" in raw:
                parts = raw.split(":")
                if len(parts) != 2: raise ValueError
                mm, ss = int(parts[0]), int(parts[1])
            else:
                # no separator: last 2 digits = seconds, rest = minutes
                if len(raw) == 0: raise ValueError
                raw_i = int(raw)
                ss = raw_i % 100
                mm = raw_i // 100
            if ss < 0 or ss > 59: raise ValueError
            if mm < 0: raise ValueError
            return mm * 60 + ss

        def _preview(*_):
            try:
                new_secs = _parse_gap(gap_var.get())
                new_m, new_s = divmod(new_secs, 60)
                delta_secs = new_secs - cur_secs
                sign = "+" if delta_secs >= 0 else "−"
                dm, ds = divmod(abs(delta_secs), 60)
                info_lbl.config(
                    text=f"→ {new_m}:{new_s:02d}  |  shift tail by {sign}{dm}:{ds:02d}",
                    fg=C["muted"])
            except ValueError:
                info_lbl.config(text="invalid — use m:ss or mss (e.g. 215 = 2:15)", fg=C["red"])

        gap_var.trace_add("write", _preview)
        _preview()

        def _apply():
            try:
                new_secs = _parse_gap(gap_var.get())
            except ValueError:
                messagebox.showerror("Edit Gap", "Invalid format.\nUse m:ss (e.g. 2:15) or mss (e.g. 215).", parent=d)
                return
            self._push_undo()
            delta = timedelta(seconds=(new_secs - cur_secs))
            new_pts = list(self.points)
            for j in range(i1, len(new_pts)):
                lat, lon, t = new_pts[j]
                new_pts[j] = (lat, lon, t + delta if t else None)
            self.points = new_pts
            self._mark_dirty()
            new_m, new_s = divmod(new_secs, 60)
            self._set_status(
                f"Gap #{i0}→#{i1} set to {new_m}:{new_s:02d}  ·  "
                f"{len(self.points)-i1} points shifted.")
            d.destroy()
            self.refresh_map_and_tree()

        bf = tk.Frame(d, bg=C["bg"]); bf.pack(padx=16, pady=(0,14))
        self._mk_btn(bf, "Apply", C["green"], _apply).pack(side="left", padx=(0,6))
        self._mk_btn(bf, "Cancel", C["dim"], d.destroy).pack(side="left")
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        d.bind("<Return>", lambda e: _apply())
        d.bind("<Escape>", lambda e: d.destroy())
        d.grab_set()

    # ── ADD ELEVATION ──────────────────────────────────────────────────────────
    def set_avg_speed(self):
        """Select 2 points; redistribute timestamps between them so the average
        speed equals a user-supplied value, then shift all subsequent points."""
        sel = self.tree.selection()
        if len(sel) != 2:
            messagebox.showerror("Set Avg Speed", "Select exactly 2 points in the table.")
            return
        i0, i1 = sorted([int(self.tree.item(s)["values"][0]) for s in sel])
        if i1 <= i0:
            messagebox.showerror("Set Avg Speed", "Select two different points."); return

        # timestamps must exist on both endpoints
        t0, t1 = self.points[i0][2], self.points[i1][2]
        if t0 is None or t1 is None:
            messagebox.showerror("Set Avg Speed",
                "Both selected points must have timestamps."); return

        # cumulative distances along the track between i0 and i1
        cum_dist = [0.0]
        for k in range(i0, i1):
            d = haversine(self.points[k][0], self.points[k][1],
                          self.points[k+1][0], self.points[k+1][1])
            cum_dist.append(cum_dist[-1] + d)
        total_dist_m = cum_dist[-1]

        if total_dist_m < 1.0:
            messagebox.showerror("Set Avg Speed",
                "Total distance between the two points is too small (< 1 m).")
            return

        cur_secs  = (t1 - t0).total_seconds()
        cur_speed = (total_dist_m / cur_secs * 3.6) if cur_secs > 0 else 0.0

        # ── dialog ────────────────────────────────────────────────────────────
        d = tk.Toplevel(self.root)
        d.title(f"Set avg speed  #{i0} → #{i1}")
        d.configure(bg=C["bg"]); d.resizable(False, False)
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")

        tk.Label(d, text=f"Average speed  #{i0} → #{i1}",
                 font=("Consolas",9,"bold"), bg=C["bg"], fg=C["accent"]).pack(
                 padx=16, pady=(14,2), anchor="w")

        info_lines = [
            f"Points:        {i0} → {i1}  ({i1-i0} segments)",
            f"Distance:      {total_dist_m/1000:.3f} km",
            f"Current time:  {int(cur_secs//3600):02d}:{int(cur_secs%3600//60):02d}:{int(cur_secs%60):02d}",
            f"Current speed: {cur_speed:.1f} kph",
        ]
        for line in info_lines:
            tk.Label(d, text=line, font=("Consolas",8), bg=C["bg"],
                     fg=C["muted"]).pack(padx=16, anchor="w")

        tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=16, pady=(10,8))

        ef = tk.Frame(d, bg=C["bg"]); ef.pack(padx=16, pady=(0,4))
        tk.Label(ef, text="Target speed (kph):", font=("Consolas",9),
                 bg=C["bg"], fg=C["text"]).pack(side="left", padx=(0,8))
        spd_var = tk.StringVar(value=f"{cur_speed:.1f}")
        spd_e = ttk.Entry(ef, textvariable=spd_var, width=10, font=("Consolas",10))
        spd_e.pack(side="left")
        spd_e.select_range(0, "end"); spd_e.focus_set()

        preview_lbl = tk.Label(d, text="", font=("Consolas",8), bg=C["bg"], fg=C["muted"])
        preview_lbl.pack(padx=16, anchor="w", pady=(4,10))

        def _preview(*_):
            try:
                kph = float(spd_var.get())
                if kph <= 0: raise ValueError
                new_secs  = total_dist_m / (kph / 3.6)
                delta_s   = new_secs - cur_secs
                sign      = "+" if delta_s >= 0 else "−"
                dh, rem   = divmod(abs(delta_s), 3600)
                dm, ds    = divmod(rem, 60)
                nh, nrem  = divmod(new_secs, 3600)
                nm, ns_   = divmod(nrem, 60)
                preview_lbl.config(
                    text=(f"→ new duration: {int(nh):02d}:{int(nm):02d}:{int(ns_):02d}"
                          f"  |  tail shift: {sign}{int(dh):02d}:{int(dm):02d}:{int(ds):02d}"),
                    fg=C["muted"])
            except (ValueError, ZeroDivisionError):
                preview_lbl.config(text="enter a positive number (kph)", fg=C["red"])

        spd_var.trace_add("write", _preview)
        _preview()

        def _apply():
            try:
                kph = float(spd_var.get())
                if kph <= 0: raise ValueError
            except ValueError:
                messagebox.showerror("Invalid input", "Enter a positive speed in kph.", parent=d)
                return

            new_total_secs = total_dist_m / (kph / 3.6)
            delta = timedelta(seconds=(new_total_secs - cur_secs))

            self._push_undo()
            new_pts = list(self.points)

            # redistribute intermediate timestamps proportionally by cumulative distance
            for offset in range(1, i1 - i0):
                frac = cum_dist[offset] / total_dist_m
                new_t = t0 + timedelta(seconds=frac * new_total_secs)
                lat, lon, _ = new_pts[i0 + offset]
                new_pts[i0 + offset] = (lat, lon, new_t)

            # shift all points from i1 onwards by the total delta
            for j in range(i1, len(new_pts)):
                lat, lon, t = new_pts[j]
                new_pts[j] = (lat, lon, t + delta if t else None)

            self.points = new_pts
            self._mark_dirty()
            nh, nrem = divmod(new_total_secs, 3600)
            nm, ns_  = divmod(nrem, 60)
            self._set_status(
                f"Avg speed #{i0}→#{i1} set to {kph:.1f} kph  ·  "
                f"new duration {int(nh):02d}:{int(nm):02d}:{int(ns_):02d}  ·  "
                f"{len(self.points)-i1} points tail-shifted.")
            d.destroy()
            self.refresh_map_and_tree()

        bf = tk.Frame(d, bg=C["bg"]); bf.pack(padx=16, pady=(0,14))
        self._mk_btn(bf, "Apply", C["green"], _apply).pack(side="left", padx=(0,6))
        self._mk_btn(bf, "Cancel", C["dim"], d.destroy).pack(side="left")
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        d.bind("<Return>", lambda e: _apply())
        d.bind("<Escape>", lambda e: d.destroy())
        d.grab_set()
    # ── GEOCODER LAUNCH ────────────────────────────────────────────────────────
    def _launch_geocoder_ui(self):
        """Prompt for comment format, then launch GPX_Geocoder.pyw on the loaded file."""
        if not self.source_path or not os.path.isfile(self.source_path):
            messagebox.showwarning("No file", "Load a GPX file first."); return

        candidates = ["GPX_Geocoder.pyw", "GPX_geocoder.pyw",
                      "gpx_geocoder.pyw", "GPX_Geocoder.py"]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        geocoder_path = None
        for name in candidates:
            p = os.path.join(script_dir, name)
            if os.path.exists(p):
                geocoder_path = p; break

        if not geocoder_path:
            messagebox.showwarning("Geocoder not found",
                "GPX_Geocoder.pyw was not found in the same folder.\n"
                f"Looking in: {script_dir}"); return

        # comment format dialog
        d = tk.Toplevel(self.root)
        d.title("Geocoder — comment format")
        d.configure(bg=C["bg"]); d.resizable(False, False)
        d.grab_set()
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")
        tk.Label(d, text="COMMENT FORMAT",
                 font=("Consolas",10,"bold"), bg=C["bg"], fg=C["accent"]).pack(padx=20, pady=(14,4), anchor="w")
        tk.Label(d, text="Choose what the Geocoder will write into each trackpoint:",
                 font=("Consolas",8), bg=C["bg"], fg=C["muted"]).pack(padx=20, anchor="w", pady=(0,10))
        tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=20)

        fmt_var = tk.IntVar(value=2)
        _rkw = dict(bg=C["bg"], fg=C["text"], activebackground=C["bg"],
                    activeforeground=C["accent"], selectcolor=C["accent2"],
                    font=("Consolas",9), anchor="w", relief="flat")
        rf = tk.Frame(d, bg=C["bg"]); rf.pack(fill="x", padx=20, pady=10)
        tk.Radiobutton(rf, text="Road, Town",
                       variable=fmt_var, value=1, **_rkw).pack(fill="x", pady=2)
        tk.Radiobutton(rf, text="Road, Town  (Province)",
                       variable=fmt_var, value=2, **_rkw).pack(fill="x", pady=2)
        tk.Radiobutton(rf, text="Road | Town | Province | Country",
                       variable=fmt_var, value=3, **_rkw).pack(fill="x", pady=2)

        chosen = [None]

        def _ok():   chosen[0] = fmt_var.get(); d.destroy()
        def _cancel(): d.destroy()

        tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=20)
        bf = tk.Frame(d, bg=C["bg"]); bf.pack(padx=20, pady=12)
        self._mk_btn(bf, "▶  Launch Geocoder", C["green"], _ok).pack(side="left", padx=(0,8))
        self._mk_btn(bf, "Cancel",             C["dim"],   _cancel).pack(side="left")
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        d.bind("<Return>", lambda e: _ok())
        d.bind("<Escape>", lambda e: _cancel())
        self.root.wait_window(d)

        if chosen[0] is None: return

        try:
            import subprocess
            _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [sys.executable, geocoder_path, self.source_path, str(chosen[0])],
                cwd=script_dir, creationflags=_NO_WINDOW)
            fmt_names = {1: "Road, Town", 2: "Road, Town (Province)", 3: "Road|Town|Province|Country"}
            self._set_status(
                f"Geocoder launched · {os.path.basename(self.source_path)} · {fmt_names[chosen[0]]}")
        except Exception as e:
            messagebox.showerror("Launch error", f"Could not launch GPX_Geocoder.pyw:\n{e}")

    # ── TREE INTERACTION ───────────────────────────────────────────────────────
    def center_on_selected(self):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0], "values")[0])
        lat, lon = self.points[idx][0], self.points[idx][1]
        self.map_widget.set_position(lat, lon)
        self.map_widget.set_zoom(15); self._zoom_level[0] = 15

    def _on_tree_select(self, event=None):
        """When a row is selected in the tree, center the map and show a highlight pin."""
        sel = self.tree.selection()
        if not sel or not self.points: return
        idx = int(self.tree.item(sel[0], "values")[0])
        if not (0 <= idx < len(self.points)): return
        lat, lon = self.points[idx][0], self.points[idx][1]
        self.map_widget.set_position(lat, lon)
        if self._sel_marker:
            try: self._sel_marker.delete()
            except: pass
        self._sel_marker = self.map_widget.set_marker(
            lat, lon, text=str(idx),
            marker_color_circle=C["accent"],
            marker_color_outside=C["accent2"]
        )

    def _on_map_click(self, coords):
        """Find the closest visible point to the clicked map position,
        select it in the tree and center the map on it."""
        if not self.points or self._drag_mode: return
        click_lat, click_lon = coords
        visible = self._get_visible_indices()
        if not visible: return

        best_idx = min(visible,
                       key=lambda i: haversine(click_lat, click_lon,
                                               self.points[i][0], self.points[i][1]))

        # find and select the matching tree row
        for item in self.tree.get_children():
            if int(self.tree.item(item, "values")[0]) == best_idx:
                self.tree.selection_set(item)
                self.tree.focus(item)
                self.tree.see(item)
                break

        # center map and show highlight pin
        p = self.points[best_idx]
        self.map_widget.set_position(p[0], p[1])
        if self._sel_marker:
            try: self._sel_marker.delete()
            except: pass
        self._sel_marker = self.map_widget.set_marker(
            p[0], p[1], text=str(best_idx),
            marker_color_circle=C["accent"],
            marker_color_outside=C["accent2"]
        )
        self._set_status(f"Closest point: #{best_idx}  ({p[0]:.7f}, {p[1]:.7f})")

    def _on_tree_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item: return
        idx = int(self.tree.item(item, "values")[0])
        lat, lon, t = self.points[idx]

        d = tk.Toplevel(self.root)
        d.title(f"Edit point #{idx}")
        d.configure(bg=C["bg"]); d.resizable(False, False)
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")

        def _row(parent, lbl, val):
            r = tk.Frame(parent, bg=C["bg"]); r.pack(fill="x", padx=16, pady=4)
            tk.Label(r, text=lbl, font=("Consolas",9), bg=C["bg"],
                     fg=C["muted"], width=6, anchor="w").pack(side="left")
            e = ttk.Entry(r, width=22, font=("Consolas",9)); e.insert(0, str(val)); e.pack(side="left")
            return e

        tk.Label(d, text=f"Point  #{idx}", font=("Consolas",10,"bold"),
                 bg=C["bg"], fg=C["accent"]).pack(padx=16, pady=(12,4), anchor="w")
        le  = _row(d, "Lat", lat)
        loe = _row(d, "Lon", lon)

        # ── timestamp section (only when point has no time) ───────────────────
        new_time_result = [None]   # will hold a datetime if user fills it in

        if t is None:
            # find nearest previous point that has a timestamp
            prev_idx = next((k for k in range(idx-1, -1, -1) if self.points[k][2] is not None), None)
            prev_t   = self.points[prev_idx][2] if prev_idx is not None else None
            prev_dist = (haversine(self.points[prev_idx][0], self.points[prev_idx][1], lat, lon)
                         if prev_idx is not None else None)

            tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=16, pady=(6,0))
            tk.Label(d, text="⚠  No timestamp — assign one:",
                     font=("Consolas",8,"bold"), bg=C["bg"], fg=C["orange"]).pack(
                     padx=16, pady=(6,2), anchor="w")

            if prev_t:
                tk.Label(d, text=f"Prev timestamped point: #{prev_idx}  →  {prev_t.strftime('%H:%M:%S')}",
                         font=("Consolas",7), bg=C["bg"], fg=C["dim"]).pack(padx=16, anchor="w", pady=(0,6))
            else:
                tk.Label(d, text="No previous timestamped point found.",
                         font=("Consolas",7), bg=C["bg"], fg=C["dim"]).pack(padx=16, anchor="w", pady=(0,6))

            mode_var = tk.StringVar(value="absolute")
            _rkw = dict(bg=C["bg"], fg=C["text"], activebackground=C["bg"],
                        activeforeground=C["accent"], selectcolor=C["accent2"],
                        font=("Consolas",8), anchor="w", relief="flat")
            mf = tk.Frame(d, bg=C["bg"]); mf.pack(fill="x", padx=16)
            tk.Radiobutton(mf, text="🕐  Absolute time  (HH:MM:SS)",
                           variable=mode_var, value="absolute", **_rkw).pack(fill="x", pady=1)
            rb_offset = tk.Radiobutton(mf, text="⏱  Offset from previous  (MM:SS)",
                           variable=mode_var, value="offset", **_rkw)
            rb_offset.pack(fill="x", pady=1)
            rb_speed  = tk.Radiobutton(mf, text="⚡  Avg speed from previous  (kph)",
                           variable=mode_var, value="speed", **_rkw)
            rb_speed.pack(fill="x", pady=1)

            # disable offset/speed if no previous timestamp
            if prev_t is None:
                rb_offset.config(state="disabled")
                rb_speed.config(state="disabled")

            # entry row below radios
            ef = tk.Frame(d, bg=C["bg"]); ef.pack(fill="x", padx=16, pady=(6,0))
            entry_lbl = tk.Label(ef, text="Time (HH:MM:SS):", font=("Consolas",8),
                                 bg=C["bg"], fg=C["text"], width=24, anchor="w")
            entry_lbl.pack(side="left")
            ts_var = tk.StringVar(value=prev_t.strftime("%H:%M:%S") if prev_t else "00:00:00")
            ts_e   = ttk.Entry(ef, textvariable=ts_var, width=14, font=("Consolas",9))
            ts_e.pack(side="left")

            preview_ts = tk.Label(d, text="", font=("Consolas",7), bg=C["bg"], fg=C["muted"])
            preview_ts.pack(padx=16, anchor="w", pady=(2,6))

            def _update_entry_label(*_):
                mode = mode_var.get()
                if mode == "absolute":
                    entry_lbl.config(text="Time (HH:MM:SS):")
                elif mode == "offset":
                    entry_lbl.config(text="Offset (MM:SS):")
                else:
                    entry_lbl.config(text="Speed (kph):")
                _preview_ts()

            def _preview_ts(*_):
                mode = mode_var.get()
                raw  = ts_var.get().strip()
                try:
                    if mode == "absolute":
                        parts = list(map(int, raw.split(":")))
                        if len(parts) != 3: raise ValueError
                        h, m, s = parts
                        result = (prev_t or datetime.now()).replace(
                            hour=h, minute=m, second=s, microsecond=0)
                        preview_ts.config(text=f"→ {result.strftime('%H:%M:%S')}", fg=C["muted"])
                        new_time_result[0] = result

                    elif mode == "offset":
                        parts = list(map(int, raw.split(":")))
                        if len(parts) != 2: raise ValueError
                        mm, ss = parts
                        if not (0 <= ss < 60): raise ValueError
                        result = prev_t + timedelta(minutes=mm, seconds=ss)
                        preview_ts.config(text=f"→ {result.strftime('%H:%M:%S')}  (+{mm}:{ss:02d} from #{prev_idx})",
                                          fg=C["muted"])
                        new_time_result[0] = result

                    else:  # speed
                        kph = float(raw)
                        if kph <= 0 or prev_dist is None: raise ValueError
                        secs   = prev_dist / (kph / 3.6)
                        result = prev_t + timedelta(seconds=secs)
                        preview_ts.config(
                            text=f"→ {result.strftime('%H:%M:%S')}  "
                                 f"({prev_dist:.0f}m at {kph:.1f}kph = {secs:.0f}s)",
                            fg=C["muted"])
                        new_time_result[0] = result

                except Exception:
                    preview_ts.config(text="invalid input", fg=C["red"])
                    new_time_result[0] = None

            mode_var.trace_add("write", _update_entry_label)
            ts_var.trace_add("write",   _preview_ts)
            _preview_ts()

        # ── save ──────────────────────────────────────────────────────────────
        bf = tk.Frame(d, bg=C["bg"]); bf.pack(padx=16, pady=10)

        def save():
            try:
                new_lat = float(le.get())
                new_lon = float(loe.get())
            except Exception:
                messagebox.showerror("Error", "Invalid lat/lon.", parent=d); return

            # determine final timestamp
            if t is None:
                final_t = new_time_result[0]
                if final_t is None:
                    if not messagebox.askyesno("No timestamp",
                            "No valid timestamp entered.\nSave point without timestamp?", parent=d):
                        return
            else:
                final_t = t   # preserve existing timestamp unchanged

            self._push_undo()
            self.points[idx] = (new_lat, new_lon, final_t)
            self._mark_dirty()
            self.refresh_map_and_tree()
            d.destroy()

        self._mk_btn(bf, "Save", C["green"], save).pack(side="left", padx=(0,6))
        self._mk_btn(bf, "Cancel", C["dim"], d.destroy).pack(side="left")
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        d.bind("<Return>", lambda e: save())
        d.bind("<Escape>", lambda e: d.destroy())
        d.grab_set()

# ──────────────────────────────────────────────────────────────────────────────
# SPLASH  (pure root.after() — no threads, no sp.update(), safe on Windows)
# ──────────────────────────────────────────────────────────────────────────────
def show_splash(root):
    sp = tk.Toplevel(root); sp.overrideredirect(True); sp.configure(bg=C["bg"])
    sw, sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w, h   = 620, 300; sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x")
    body = tk.Frame(sp, bg=C["bg"]); body.pack(expand=True, fill="both", padx=40)
    tk.Label(body, text="GPX IRONER",
             font=("Consolas",22,"bold"), bg=C["bg"], fg=C["accent"]).pack(pady=(28,4))
    tk.Label(body, text=f"{VERSION}  ·  by {AUTHOR}  ·  {datetime.now().year}",
             font=("Consolas",9), bg=C["bg"], fg=C["muted"]).pack()
    tk.Label(body, text="clean, iron and edit GPX trackpoints",
             font=("Consolas",9,"italic"), bg=C["bg"], fg=C["dim"]).pack(pady=(4,16))
    pbv = tk.DoubleVar()
    pb  = ttk.Progressbar(body, variable=pbv, maximum=100, length=540); pb.pack()
    pct = tk.Label(body, text="Loading…", font=("Consolas",8), bg=C["bg"], fg=C["dim"])
    pct.pack(pady=4)
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")
    sp.lift(); sp.attributes("-topmost", True)

    steps      = max(15, SPLASH_SECONDS * 20)
    interval_ms = int(SPLASH_SECONDS * 1000 / steps)

    def _step(i=0):
        if not sp.winfo_exists():          # splash was closed externally
            _finish(); return
        pct_val = i / steps * 100
        pbv.set(pct_val)
        pct.config(text=f"{int(pct_val)}%")
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
    app  = IronApp(root)
    # auto-load if a GPX path was passed as argv[1]
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        root.after(500, lambda: app._load_file(sys.argv[1]))
    root.mainloop()
