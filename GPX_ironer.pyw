#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Ironer  v2.0
Author : Marco Cot
Contact: marcocot1982@gmail.com

Dark cinematic UI. Auto-saves a _temp file every 10 minutes after changes.
"""

import os, math, time
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

        self._sec_hdr(left, "IRON & BRIDGE")
        ib = tk.Frame(left, bg=C["panel"]); ib.pack(fill="x", padx=10, pady=6)
        r1 = tk.Frame(ib, bg=C["panel"]); r1.pack(fill="x", pady=2)
        self._lbl_entry(r1, "Iron KPH",   self.max_kph_iron,   width=6)
        self._lbl_entry(r1, "Bridge KPH", self.max_kph_bridge, width=6)
        # Auto-Iron + Bridge: half width each
        r2 = tk.Frame(ib, bg=C["panel"]); r2.pack(fill="x", pady=4)
        self._mk_btn(r2, "⚙  Auto-Iron", C["orange"], self.auto_iron).pack(side="left", expand=True, fill="x", padx=(0,2))
        self._mk_btn(r2, "🌉  Bridge",   C["blue"],   self.bridge_logic).pack(side="left", expand=True, fill="x", padx=(2,0))

        self._sec_hdr(left, "VISUAL")
        vs = tk.Frame(left, bg=C["panel"]); vs.pack(fill="x", padx=10, pady=6)
        r3 = tk.Frame(vs, bg=C["panel"]); r3.pack(fill="x")
        self._lbl_entry(r3, "Color N",  self.color_interval_var, width=5)
        self._lbl_entry(r3, "Pin Freq", self.marker_freq_var,    width=5)

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
        fl1 = tk.Frame(fl, bg=C["panel"]); fl1.pack(fill="x")
        self.idx_min_e = self._lbl_entry(fl1, "Idx ≥", None, width=6)
        self.idx_max_e = self._lbl_entry(fl1, "Idx ≤", None, width=6)
        fl2 = tk.Frame(fl, bg=C["panel"]); fl2.pack(fill="x", pady=2)
        self.lat_min_e = self._lbl_entry(fl2, "Lat ≥", None, width=8)
        self.lat_max_e = self._lbl_entry(fl2, "Lat ≤", None, width=8)
        fl3 = tk.Frame(fl, bg=C["panel"]); fl3.pack(fill="x", pady=2)
        self.lon_min_e = self._lbl_entry(fl3, "Lon ≥", None, width=8)
        self.lon_max_e = self._lbl_entry(fl3, "Lon ≤", None, width=8)
        # Apply Filter + Clear: half width each
        fl4 = tk.Frame(fl, bg=C["panel"]); fl4.pack(fill="x", pady=(4,0))
        self._mk_btn(fl4, "Apply Filter", C["blue"], self.apply_filter).pack(side="left", expand=True, fill="x", padx=(0,2))
        self._mk_btn(fl4, "Clear",        C["dim"],  self.clear_filter).pack(side="left", expand=True, fill="x", padx=(2,0))

        self._sec_hdr(left, "BULK ACTIONS")
        ba = tk.Frame(left, bg=C["panel"]); ba.pack(fill="x", padx=10, pady=6)
        # Delete Filtered: full width
        ba1 = tk.Frame(ba, bg=C["panel"]); ba1.pack(fill="x", pady=2)
        self._mk_btn(ba1, "🗑  Delete Filtered", C["red"], self.bulk_delete_filtered).pack(fill="x")
        # Set Int Lat + Set Int Lon: half width each
        ba2 = tk.Frame(ba, bg=C["panel"]); ba2.pack(fill="x", pady=2)
        self._mk_btn(ba2, "Set Int Lat", C["orange"], lambda: self.bulk_set_integer("lat")).pack(side="left", expand=True, fill="x", padx=(0,2))
        self._mk_btn(ba2, "Set Int Lon", C["orange"], lambda: self.bulk_set_integer("lon")).pack(side="left", expand=True, fill="x", padx=(2,0))
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

        tsb = ttk.Scrollbar(tree_inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_tree_double_click)

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
    def _zoom_out(self):
        self._zoom_level[0] = max(self._zoom_level[0]-1, 2)
        self.map_widget.set_zoom(self._zoom_level[0])

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
        if self._dirty and self.points and self.source_path:
            elapsed = time.time() - self._last_autosave
            if elapsed >= AUTOSAVE_SECS:
                self._write_temp()
        self.root.after(60_000, self._do_autosave_check)   # check every minute

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
        path = filedialog.askopenfilename(filetypes=[("GPX","*.gpx")])
        if not path: return
        self.source_path      = path
        self.current_filename = os.path.basename(path)
        with open(path,"r") as f: gpx = gpxpy.parse(f)
        self.points = [(p.latitude, p.longitude, p.time)
                       for t in gpx.tracks for s in t.segments for p in s.points]

        # make a backup of the original file (once; don't overwrite existing backup)
        stem, ext = os.path.splitext(path)
        if not stem.endswith("_backup"):
            backup_path = stem + "_backup" + ext
            if not os.path.exists(backup_path):
                try:
                    import shutil; shutil.copy2(path, backup_path)
                    self._set_status(f"Backup saved → {os.path.basename(backup_path)}")
                except Exception as ex:
                    self._set_status(f"Backup failed: {ex}")

        self.file_lbl.config(text=self.current_filename)
        self._mark_clean()
        self._last_autosave = time.time()
        self.autosave_lbl.config(text="")
        self._set_status(f"Loaded {len(self.points)} points  ·  {self.current_filename}")
        self._pending_center = ("fit",)
        self.refresh_map_and_tree()

    def _save_to_path(self, path):
        gpx = gpxpy.gpx.GPX()
        track = gpxpy.gpx.GPXTrack(); gpx.tracks.append(track)
        seg   = gpxpy.gpx.GPXTrackSegment(); track.segments.append(seg)
        for p in self.points:
            seg.points.append(gpxpy.gpx.GPXTrackPoint(p[0], p[1], time=p[2]))
        with open(path,"w") as f: f.write(gpx.to_xml())

    def export_clean_gpx(self):
        if not self.points: messagebox.showwarning("Empty","No points to save."); return
        stem     = os.path.splitext(self.current_filename)[0] if self.current_filename else "track"
        def_name = stem + "_ironed.gpx"
        path     = filedialog.asksaveasfilename(defaultextension=".gpx", initialfile=def_name,
                                                 filetypes=[("GPX","*.gpx")])
        if not path: return
        self._save_to_path(path)
        # delete _temp file if it exists
        if self._last_temp_path and os.path.exists(self._last_temp_path):
            try: os.remove(self._last_temp_path)
            except: pass
            self._last_temp_path = ""
            self.autosave_lbl.config(text="")
        self._mark_clean()
        self._set_status(f"Saved → {os.path.basename(path)}")

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

    # ── VIEW ───────────────────────────────────────────────────────────────────
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
            self.tree.insert("", "end",
                             values=(i, dir_str, f"{p[0]:.7f}", f"{p[1]:.7f}", d_s, s_s, ts),
                             tags=("rogue",) if rogue else ())

        self.pt_count_lbl.config(text=f"{len(visible)} points shown  ·  {len(self.points)} total")

        self.map_widget.delete_all_path()
        self.map_widget.delete_all_marker()
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
        if mark_f > 0:
            for i in draw_idxs:
                if i % mark_f == 0:
                    self.map_widget.set_marker(self.points[i][0], self.points[i][1], text=str(i))

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
        offset = simpledialog.askstring("Time shift", "Offset (HH:MM:SS):", initialvalue="01:00:00")
        if not offset: return
        try:
            h,m,s = map(int, offset.split(":"))
            delta  = timedelta(hours=h, minutes=m, seconds=s)
            self._push_undo()
            self.points = [(p[0], p[1], p[2]+delta if p[2] else None) for p in self.points]
            self._mark_dirty()
            self._set_status(f"Time shifted by {offset}.")
            self.refresh_map_and_tree()
        except: messagebox.showerror("Error","Invalid format. Use HH:MM:SS.")

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

    # ── TREE INTERACTION ───────────────────────────────────────────────────────
    def center_on_selected(self):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0], "values")[0])
        lat, lon = self.points[idx][0], self.points[idx][1]
        self.map_widget.set_position(lat, lon)
        self.map_widget.set_zoom(15); self._zoom_level[0] = 15

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

        # center map on the found point (no refresh — just reposition)
        p = self.points[best_idx]
        self.map_widget.set_position(p[0], p[1])
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

        def _row(lbl, val):
            r = tk.Frame(d, bg=C["bg"]); r.pack(fill="x", padx=16, pady=4)
            tk.Label(r, text=lbl, font=("Consolas",9), bg=C["bg"],
                     fg=C["muted"], width=6, anchor="w").pack(side="left")
            e = ttk.Entry(r, width=22, font=("Consolas",9)); e.insert(0, str(val)); e.pack(side="left")
            return e

        tk.Label(d, text=f"Point  #{idx}", font=("Consolas",10,"bold"),
                 bg=C["bg"], fg=C["accent"]).pack(padx=16, pady=(12,4), anchor="w")
        le  = _row("Lat", lat)
        loe = _row("Lon", lon)

        bf = tk.Frame(d, bg=C["bg"]); bf.pack(padx=16, pady=10)
        def save():
            try:
                self._push_undo()
                self.points[idx] = (float(le.get()), float(loe.get()), t)
                self._mark_dirty(); self.refresh_map_and_tree(); d.destroy()
            except: messagebox.showerror("Error","Invalid lat/lon.", parent=d)
        self._mk_btn(bf, "Save", C["green"], save).pack(side="left", padx=(0,6))
        self._mk_btn(bf, "Cancel", C["dim"], d.destroy).pack(side="left")
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")
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
    root.mainloop()
