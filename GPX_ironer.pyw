#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Ironer  v2.0
Author : Marco Cot
Contact: marcocot1982@gmail.com

Dark cinematic UI. Auto-saves a _temp file every 10 minutes after changes.
"""

import os, math, time, threading
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

SEGMENT_COLORS = ["#f5a623","#2196F3","#4caf50","#e53935","#ab47bc",
                  "#00bcd4","#ff7043","#8d6e63","#26a69a","#ffd54f"]

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
# MATHS HELPERS
# ──────────────────────────────────────────────────────────────────────────────
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

        self.points           = []
        self.current_filename = ""
        self.source_path      = ""
        self.filtered_indices = None
        self.focus_range      = None
        self._dirty           = False      # True after any unsaved change
        self._last_autosave   = time.time()
        self._last_temp_path  = ""

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
        self.marker_freq_var    = tk.StringVar(value="10")
        self.color_interval_var = tk.StringVar(value="100")

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

        # ── LEFT SIDEBAR ──────────────────────────────────────────────────────
        left = tk.Frame(body, bg=C["panel"], width=270)
        left.pack(side="left", fill="y", padx=(10,0), pady=10)
        left.pack_propagate(False)

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
            self.tree.column(c, width=widths.get(c,65), anchor="center" if c=="dir" else "w")
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

        map_border = tk.Frame(map_outer, bg=C["accent"], padx=2, pady=2)
        map_border.pack(fill="both", expand=True)
        self.map_widget = tkintermapview.TkinterMapView(map_border, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)
        self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
        self.map_widget.set_position(45.0, 7.0)
        self.map_widget.set_zoom(5)

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

    # ── STATUS ─────────────────────────────────────────────────────────────────
    def _set_status(self, msg):
        self.status_lbl.config(text=msg)
    def _mark_dirty(self):
        self._dirty = True
        self.dirty_lbl.config(text="● unsaved changes")
    def _mark_clean(self):
        self._dirty = False
        self.dirty_lbl.config(text="")

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
        self.file_lbl.config(text=self.current_filename)
        self._mark_clean()
        self._last_autosave = time.time()
        self.autosave_lbl.config(text="")
        self._set_status(f"Loaded {len(self.points)} points  ·  {self.current_filename}")
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
        self._mark_dirty()
        self._set_status(f"Bridge: {count} point(s) bridged.")
        self.refresh_map_and_tree()

    # ── VIEW ───────────────────────────────────────────────────────────────────
    def refresh_map_and_tree(self):
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
                d_s   = f"{d:.1f}"
                s_s   = f"{s:.1f}"
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

        # fit map to track on first load
        if self.points:
            lats = [p[0] for p in self.points]; lons = [p[1] for p in self.points]
            self.map_widget.set_position((min(lats)+max(lats))/2, (min(lons)+max(lons))/2)
            span = max(max(lats)-min(lats), max(lons)-min(lons))
            z = 7 if span>5 else 9 if span>2 else 10 if span>1 else 12 if span>0.3 else 13 if span>0.1 else 14
            self._zoom_level[0] = z
            self.map_widget.set_zoom(z)

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
            self.points = [(p[0], p[1], p[2]+delta if p[2] else None) for p in self.points]
            self._mark_dirty()
            self._set_status(f"Time shifted by {offset}.")
            self.refresh_map_and_tree()
        except: messagebox.showerror("Error","Invalid format. Use HH:MM:SS.")

    # ── TREE INTERACTION ───────────────────────────────────────────────────────
    def center_on_selected(self):
        sel = self.tree.selection()
        if not sel: return
        idx = int(self.tree.item(sel[0], "values")[0])
        self.map_widget.set_position(self.points[idx][0], self.points[idx][1])
        self.map_widget.set_zoom(15); self._zoom_level[0] = 15

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
                self.points[idx] = (float(le.get()), float(loe.get()), t)
                self._mark_dirty(); self.refresh_map_and_tree(); d.destroy()
            except: messagebox.showerror("Error","Invalid lat/lon.", parent=d)
        self._mk_btn(bf, "Save", C["green"], save).pack(side="left", padx=(0,6))
        self._mk_btn(bf, "Cancel", C["dim"], d.destroy).pack(side="left")
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        d.grab_set()

# ──────────────────────────────────────────────────────────────────────────────
# SPLASH
# ──────────────────────────────────────────────────────────────────────────────
def show_splash(root):
    sp = tk.Toplevel(root); sp.overrideredirect(True); sp.configure(bg=C["bg"])
    sw,sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w,h   = 620, 300; sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
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
    pct = tk.Label(body, text="Loading…", font=("Consolas",8), bg=C["bg"], fg=C["dim"]); pct.pack(pady=4)
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")
    def fake():
        steps = max(15, SPLASH_SECONDS*20)
        for i in range(steps+1):
            pbv.set(i/steps*100); pct.config(text=f"{int(i/steps*100)}%"); sp.update()
            time.sleep(SPLASH_SECONDS/steps)
        sp.destroy(); root.deiconify()
        try: root.state("zoomed")
        except: pass
    root.withdraw()
    threading.Thread(target=fake, daemon=True).start()

# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    show_splash(root)
    app  = IronApp(root)
    root.mainloop()
