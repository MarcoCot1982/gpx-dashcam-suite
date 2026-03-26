#!/usr/bin/env pythonw
"""
Cache Editor v0.8
- WAL + separate write connections (no more "database is locked")
- Fullscreen on open
- Default folders: Open DB -> Desktop/GeocodeApp, Load GPX -> Desktop/Geocoded
- Marker density default = 5 (changeable from UI)
- Manual start/end indices
- Area selection: 4 clicks to define rectangle
- Re-geocode: deletes <base>_geocoded.gpx and launches GPX_Geocoder.pyw --input <file>

UI restyled to match GPX Ironer dark cinematic theme.
"""

import os
import sqlite3
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime, timezone
import gpxpy
import tkintermapview

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
VERSION            = "v0.8"
AUTHOR             = "Marco Cot"
CACHE_KEY_DECIMALS = 4
DEFAULT_MARKER_DENSITY = 5
DESKTOP            = os.path.join(os.path.expanduser("~"), "Desktop")
DEFAULT_DB_FOLDER  = os.path.join(DESKTOP, "GeocodeApp")
DEFAULT_GPX_FOLDER = os.path.join(DESKTOP, "Geocoded")
DEFAULT_CACHE_NAME = "geocode_cache.db"

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE  (shared with GPX Ironer / GPX Geocoder)
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
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def cache_key(lat, lon):
    return f"{round(lat, CACHE_KEY_DECIMALS)}_{round(lon, CACHE_KEY_DECIMALS)}"

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

def ensure_backup(db_path):
    base = os.path.basename(db_path)
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    dst  = os.path.join(os.path.dirname(db_path), f"{base}.backup.{ts}")
    with open(db_path, "rb") as rf, open(dst, "wb") as wf:
        wf.write(rf.read())
    return dst

def db_write_execute(db_path, sql, params=(), commit=True, timeout=30):
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        cur = conn.cursor()
        cur.execute(sql, params)
        if commit: conn.commit()
        rc = cur.rowcount
        cur.close()
    finally:
        conn.close()
    return rc

def db_read_all(db_path, sql, params=()):
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return rows

# ──────────────────────────────────────────────────────────────────────────────
# UI HELPERS  (matching GPX Ironer)
# ──────────────────────────────────────────────────────────────────────────────
def mk_btn(parent, text, bg, cmd, width=None, font=("Consolas", 9, "bold")):
    kw = dict(
        text=text, bg=bg,
        fg="white" if bg not in (C["dim"], C["panel2"]) else C["muted"],
        activebackground=bg, activeforeground="white",
        relief="flat", cursor="hand2", command=cmd,
        font=font, pady=4, padx=8,
    )
    if width: kw["width"] = width
    return tk.Button(parent, **kw)

def sec_hdr(parent, text):
    f = tk.Frame(parent, bg=C["panel"]); f.pack(fill="x", padx=10, pady=(12, 3))
    tk.Label(f, text=text, font=("Consolas", 8, "bold"),
             bg=C["panel"], fg=C["accent"]).pack(side="left")
    tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=10)

def lbl_entry(parent, label_text, width=8):
    """Label + dark Entry inline, returns the Entry."""
    r = tk.Frame(parent, bg=C["panel"]); r.pack(side="left", padx=(0, 6))
    tk.Label(r, text=label_text, font=("Consolas", 8),
             bg=C["panel"], fg=C["muted"]).pack(side="left", padx=(0, 2))
    e = tk.Entry(r, width=width,
                  bg=C["panel2"], fg=C["text"],
                  insertbackground=C["text"], relief="flat",
                  highlightthickness=1, highlightcolor=C["accent"],
                  highlightbackground=C["border"],
                  font=("Consolas", 9))
    e.pack(side="left")
    return e

# ──────────────────────────────────────────────────────────────────────────────
# CACHE EDITOR
# ──────────────────────────────────────────────────────────────────────────────
class CacheEditor:
    def __init__(self, root):
        self.root = root
        root.title(f"Cache Editor  {VERSION}")
        root.configure(bg=C["bg"])
        try:    root.state("zoomed")
        except: root.attributes("-fullscreen", True)

        # ── ttk style ──────────────────────────────────────────────────────────
        sty = ttk.Style(root); sty.theme_use("clam")
        sty.configure(".",          background=C["bg"],    foreground=C["text"])
        sty.configure("TLabel",     background=C["bg"],    foreground=C["text"], font=("Consolas", 9))
        sty.configure("TFrame",     background=C["bg"])
        sty.configure("TScrollbar", background=C["panel2"], troughcolor=C["border"],
                                    arrowcolor=C["muted"])

        # state
        self.db_path             = None
        self.conn                = None
        self.gpx_tracks          = []
        self.current_track_index = None
        self.point_markers       = []
        self.marker_by_index     = {}
        self.selection_start     = None
        self.selection_end       = None
        self.last_clicked_index  = None
        self.area_clicks         = []
        self.area_rect_obj       = None
        self.marker_density      = DEFAULT_MARKER_DENSITY
        self.area_mode           = False

        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────────
    # BUILD UI
    # ──────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Top chrome ────────────────────────────────────────────────────────
        tk.Frame(self.root, bg=C["accent"], height=3).pack(fill="x")
        tb = tk.Frame(self.root, bg=C["bg"]); tb.pack(fill="x", padx=16, pady=5)
        tk.Label(tb, text="CACHE EDITOR",
                 font=("Consolas", 13, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        tk.Label(tb, text=f"{VERSION}  ·  {AUTHOR}  ·  2025–{datetime.now().year}",
                 font=("Consolas", 8), bg=C["bg"], fg=C["dim"]).pack(side="right")
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=C["bg"]); body.pack(fill="both", expand=True)

        # ── LEFT SIDEBAR ──────────────────────────────────────────────────────
        left = tk.Frame(body, bg=C["panel"], width=290)
        left.pack(side="left", fill="y", padx=(10, 0), pady=10)
        left.pack_propagate(False)

        # — Database ——————————————————————————————————————————————————————————
        sec_hdr(left, "DATABASE")
        db_f = tk.Frame(left, bg=C["panel"]); db_f.pack(fill="x", padx=10, pady=6)
        mk_btn(db_f, "📂  Open Cache DB",    C["blue"],   self.open_db).pack(fill="x", pady=2)
        mk_btn(db_f, "💾  Backup DB Now",    C["dim"],    self.backup_db).pack(fill="x", pady=2)
        mk_btn(db_f, "🔄  Reload Stats",     C["dim"],    self.print_cache_stats).pack(fill="x", pady=2)
        self._db_lbl = tk.Label(db_f, text="No database loaded",
                                 font=("Consolas", 7, "italic"), bg=C["panel"],
                                 fg=C["muted"], wraplength=260, anchor="w")
        self._db_lbl.pack(anchor="w", pady=(2, 0))

        # — GPX ———————————————————————————————————————————————————————————————
        sec_hdr(left, "GPX TRACK")
        gpx_f = tk.Frame(left, bg=C["panel"]); gpx_f.pack(fill="x", padx=10, pady=6)
        mk_btn(gpx_f, "📂  Load GPX File(s)", C["blue"], self.load_gpx_files).pack(fill="x", pady=2)

        tk.Label(left, text="TRACKS",
                 font=("Consolas", 7, "bold"), bg=C["panel"],
                 fg=C["muted"]).pack(padx=10, anchor="w", pady=(4, 1))
        lb_border = tk.Frame(left, bg=C["accent"], padx=1, pady=1)
        lb_border.pack(fill="x", padx=10, pady=(0, 4))
        lb_inner = tk.Frame(lb_border, bg=C["panel2"]); lb_inner.pack(fill="both")
        lb_sb = ttk.Scrollbar(lb_inner, orient="vertical")
        lb_sb.pack(side="right", fill="y")
        self.track_listbox = tk.Listbox(lb_inner, width=32, height=7,
                                         bg=C["panel2"], fg=C["text"],
                                         selectbackground=C["accent"],
                                         selectforeground="black",
                                         activestyle="none", relief="flat",
                                         borderwidth=0, font=("Consolas", 8),
                                         yscrollcommand=lb_sb.set)
        self.track_listbox.pack(side="left", fill="both", expand=True)
        lb_sb.config(command=self.track_listbox.yview)
        self.track_listbox.bind("<<ListboxSelect>>", self.on_track_select)

        # — Marker density ————————————————————————————————————————————————————
        sec_hdr(left, "MAP MARKERS")
        md_f = tk.Frame(left, bg=C["panel"]); md_f.pack(fill="x", padx=10, pady=6)
        self.density_btn = mk_btn(md_f,
                                   f"Every {self.marker_density} pts",
                                   C["dim"], self.change_marker_density)
        self.density_btn.pack(fill="x")

        # — Range selection ———————————————————————————————————————————————————
        sec_hdr(left, "RANGE SELECTION")
        rng_f = tk.Frame(left, bg=C["panel"]); rng_f.pack(fill="x", padx=10, pady=6)

        r1 = tk.Frame(rng_f, bg=C["panel"]); r1.pack(fill="x", pady=2)
        mk_btn(r1, "Set Start",   C["orange"], self.set_start_from_click).pack(side="left", expand=True, fill="x", padx=(0, 2))
        mk_btn(r1, "Set End",     C["orange"], self.set_end_from_click).pack(side="left", expand=True, fill="x", padx=(2, 0))

        r2 = tk.Frame(rng_f, bg=C["panel"]); r2.pack(fill="x", pady=2)
        mk_btn(r2, "From Start (0)", C["dim"], self.set_start_from_start).pack(side="left", expand=True, fill="x", padx=(0, 2))
        mk_btn(r2, "To End",         C["dim"], self.set_end_from_end).pack(side="left", expand=True, fill="x", padx=(2, 0))

        # manual indices
        mi = tk.Frame(rng_f, bg=C["panel"]); mi.pack(fill="x", pady=(6, 2))
        self.manual_start_entry = lbl_entry(mi, "Start:", width=7)
        self.manual_end_entry   = lbl_entry(mi, "End:",   width=7)
        mk_btn(rng_f, "Apply Manual Indices", C["blue"], self.apply_manual_indices).pack(fill="x", pady=(2, 0))

        self.range_label = tk.Label(rng_f, text="No selection",
                                     font=("Consolas", 8), bg=C["panel"],
                                     fg=C["muted"])
        self.range_label.pack(anchor="w", pady=(6, 0))

        # — Actions ———————————————————————————————————————————————————————————
        sec_hdr(left, "ACTIONS")
        act_f = tk.Frame(left, bg=C["panel"]); act_f.pack(fill="x", padx=10, pady=6)
        mk_btn(act_f, "🗑  Delete Selected Range", C["red"],    self.delete_selected_range).pack(fill="x", pady=2)
        mk_btn(act_f, "✏  Edit Selected Range",   C["orange"], self.open_edit_dialog).pack(fill="x", pady=2)
        mk_btn(act_f, "⬛  Select Area (4 clicks)", C["teal"],  self.activate_area_selection).pack(fill="x", pady=2)
        mk_btn(act_f, "🔄  Re-geocode GPX",        C["green"],  self.regeocode_gpx).pack(fill="x", pady=2)

        # ── CENTER — PREVIEW ──────────────────────────────────────────────────
        center = tk.Frame(body, bg=C["bg"], width=380)
        center.pack(side="left", fill="y", padx=8, pady=10)
        center.pack_propagate(False)

        ph = tk.Frame(center, bg=C["bg"]); ph.pack(fill="x", pady=(0, 4))
        tk.Label(ph, text="POINT PREVIEW",
                 font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

        prev_border = tk.Frame(center, bg=C["accent"], padx=1, pady=1)
        prev_border.pack(fill="both", expand=True)
        prev_inner = tk.Frame(prev_border, bg=C["panel2"])
        prev_inner.pack(fill="both", expand=True)
        psb = ttk.Scrollbar(prev_inner, orient="vertical")
        psb.pack(side="right", fill="y")
        self.preview = tk.Text(prev_inner, bg=C["panel2"], fg=C["text"],
                                insertbackground=C["text"], font=("Consolas", 9),
                                relief="flat", borderwidth=0, wrap="word",
                                yscrollcommand=psb.set)
        self.preview.pack(side="left", fill="both", expand=True)
        psb.config(command=self.preview.yview)

        # ── RIGHT — MAP ───────────────────────────────────────────────────────
        map_outer = tk.Frame(body, bg=C["bg"])
        map_outer.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=10)

        mh = tk.Frame(map_outer, bg=C["bg"]); mh.pack(fill="x", pady=(0, 4))
        tk.Label(mh, text="TRACK MAP",
                 font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        zf = tk.Frame(mh, bg=C["bg"]); zf.pack(side="right")
        mk_btn(zf, "＋", C["panel2"], self._zoom_in,  font=("Consolas", 11, "bold")).pack(side="left", padx=2)
        mk_btn(zf, "－", C["panel2"], self._zoom_out, font=("Consolas", 11, "bold")).pack(side="left", padx=2)

        map_border = tk.Frame(map_outer, bg=C["accent"], padx=2, pady=2)
        map_border.pack(fill="both", expand=True)
        self.map_widget = tkintermapview.TkinterMapView(map_border, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)
        self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
        try:
            self.map_widget.set_position(43.72, 7.26)
            self.map_widget.set_zoom(12)
        except Exception:
            pass
        self._zoom_level = [12]

        # ── STATUS BAR ────────────────────────────────────────────────────────
        sb = tk.Frame(self.root, bg=C["panel"], height=26)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")
        self._status_label = tk.Label(sb, text="Ready. Open a cache DB to begin.",
                                       font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
        self._status_label.pack(side="left", padx=10, pady=3)

        # map click registration
        self._map_click_registered = False
        self._register_map_click_handler(self._on_map_left_click)

    # ── zoom ──────────────────────────────────────────────────────────────────
    def _zoom_in(self):
        z = min(self._zoom_level[0] + 1, 19)
        self._zoom_level[0] = z; self.map_widget.set_zoom(z)

    def _zoom_out(self):
        z = max(self._zoom_level[0] - 1, 3)
        self._zoom_level[0] = z; self.map_widget.set_zoom(z)

    # ── map click helpers ─────────────────────────────────────────────────────
    def _register_map_click_handler(self, func):
        if self._map_click_registered: return
        try:
            self._left_click_id = self.map_widget.add_left_click_map_command(func)
            self._map_click_registered = True
        except Exception:
            try:
                widget = getattr(self.map_widget, "canvas", self.map_widget)
                widget.bind("<Button-1>", lambda ev: self._on_canvas_click(ev, func))
                self._map_click_registered = True
                self._canvas_bound = True
            except Exception:
                self._map_click_registered = False

    def _unregister_map_click_handler(self):
        if not self._map_click_registered: return
        try:
            if hasattr(self, "_left_click_id"):
                try: self.map_widget.delete_left_click_map_command(self._left_click_id)
                except Exception: pass
            if hasattr(self, "_canvas_bound") and self._canvas_bound:
                widget = getattr(self.map_widget, "canvas", self.map_widget)
                try: widget.unbind("<Button-1>")
                except: pass
        finally:
            self._map_click_registered = False
            self._canvas_bound = False

    def _on_canvas_click(self, event, func):
        try:
            lat, lon = self.map_widget.get_position_from_xy(event.x, event.y)
        except Exception:
            return
        func(lat, lon)

    def _on_map_left_click(self, lat, lon):
        if getattr(self, "area_mode", False):
            self.area_clicks.append((lat, lon))
            self.status_message(f"Area clicks: {len(self.area_clicks)}/4")
            try:
                self.map_widget.set_marker(lat, lon, text=str(len(self.area_clicks)),
                                           marker_color_circle=C["teal"],
                                           marker_color_outside=C["teal"])
            except Exception: pass
            if len(self.area_clicks) >= 4:
                self._finalize_area_selection()
            return
        if self.current_track_index is None: return
        pts = self.gpx_tracks[self.current_track_index]["points"]
        if not pts: return
        best_i, best_d = None, None
        for i, (plat, plon, _) in enumerate(pts):
            d = (plat - lat)**2 + (plon - lon)**2
            if best_d is None or d < best_d:
                best_d = d; best_i = i
        if best_i is not None:
            self.on_point_clicked(best_i)

    # ── GPX loading ───────────────────────────────────────────────────────────
    def load_gpx_files(self):
        start_dir = DEFAULT_GPX_FOLDER if os.path.isdir(DEFAULT_GPX_FOLDER) else DESKTOP
        files = filedialog.askopenfilenames(title="Select GPX files",
                                             filetypes=[("GPX files", "*.gpx")],
                                             initialdir=start_dir)
        if not files: return
        self.gpx_tracks.clear()
        self.track_listbox.delete(0, tk.END)
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    g = gpxpy.parse(fh)
                for ti, trk in enumerate(g.tracks):
                    for si, seg in enumerate(trk.segments):
                        points = [(p.latitude, p.longitude, getattr(p, "time", None))
                                  for p in seg.points]
                        name = trk.name or f"{os.path.basename(fp)} t{ti+1}s{si+1}"
                        self.gpx_tracks.append({"file": fp, "name": name, "points": points})
                        self.track_listbox.insert(tk.END, "  " + name)
            except Exception as e:
                messagebox.showwarning("GPX load error", f"Failed to load {fp}\n{e}")
        if self.gpx_tracks:
            self.track_listbox.selection_set(0)
            self.on_track_select()

    def on_track_select(self, event=None):
        sel = self.track_listbox.curselection()
        if not sel: return
        idx = sel[0]
        self.current_track_index = idx
        trk = self.gpx_tracks[idx]
        pts = trk["points"]
        coords = [(lat, lon) for lat, lon, _ in pts]
        self.clear_markers()
        try:
            if coords:
                self.map_widget.set_path(coords, color=C["blue"], width=3)
                mid = max(0, len(coords) // 2)
                self.map_widget.set_position(coords[mid][0], coords[mid][1])
                z = 13; self.map_widget.set_zoom(z); self._zoom_level[0] = z
        except Exception: pass
        self.marker_by_index.clear()
        for i, (lat, lon, _) in enumerate(pts):
            if i % self.marker_density != 0 and i != 0 and i != len(pts) - 1:
                continue
            try:
                m = self.map_widget.set_marker(lat, lon, text=str(i),
                                               marker_color_circle=C["accent"],
                                               marker_color_outside=C["accent2"])
                try:    m.set_marker_callback(lambda mobj=None, idx=i: self.on_point_clicked(idx))
                except Exception:
                    try: m.command = (lambda idx=i: lambda *a, **k: self.on_point_clicked(idx))()
                    except Exception: pass
                self.point_markers.append(m)
                self.marker_by_index[i] = m
            except Exception: pass
        self._register_map_click_handler(self._on_map_left_click)
        self.selection_start = None
        self.selection_end   = None
        self.area_clicks.clear()
        self._clear_area_rect()
        self.update_range_label()
        self.preview.delete("1.0", tk.END)

    def clear_markers(self):
        for m in self.point_markers:
            try: m.delete()
            except Exception: pass
        self.point_markers.clear()
        self.marker_by_index.clear()

    # ── point preview ─────────────────────────────────────────────────────────
    def on_point_clicked(self, index):
        if self.current_track_index is None: return
        pts = self.gpx_tracks[self.current_track_index]["points"]
        if index < 0 or index >= len(pts): return
        lat, lon, t = pts[index]
        cache_txt = "(no DB loaded)"
        if self.db_path and os.path.exists(self.db_path):
            try:
                rows = db_read_all(self.db_path,
                    "SELECT road, town, province, country3, country2, source, timestamp "
                    "FROM geocode_cache WHERE key=?", (cache_key(lat, lon),))
                if rows:
                    road, town, prov, c3, c2, src, ts = rows[0]
                    cache_txt = (f"Road:     {road}\nTown:     {town}\n"
                                 f"Province: {prov}\nCountry:  {c3}\n"
                                 f"Source:   {src}\nCached:   {ts}")
                else:
                    cache_txt = "(no cache entry)"
            except Exception:
                cache_txt = "(db read error)"
        self.preview.delete("1.0", tk.END)
        self.preview.insert(tk.END,
            f"Index : {index}\nLat   : {lat}\nLon   : {lon}\nTime  : {t}\n\n{cache_txt}\n")
        self.last_clicked_index = index

    # ── selection helpers ─────────────────────────────────────────────────────
    def set_start_from_click(self):
        if self.last_clicked_index is None:
            messagebox.showwarning("No point clicked", "Click a point on the map first.")
            return
        self.selection_start = self.last_clicked_index
        self.update_range_label()

    def set_end_from_click(self):
        if self.last_clicked_index is None:
            messagebox.showwarning("No point clicked", "Click a point on the map first.")
            return
        self.selection_end = self.last_clicked_index
        self.update_range_label()

    def set_start_from_start(self):
        if self.current_track_index is None: return
        self.selection_start = 0
        self.update_range_label()

    def set_end_from_end(self):
        if self.current_track_index is None: return
        pts = self.gpx_tracks[self.current_track_index]["points"]
        self.selection_end = len(pts) - 1
        self.update_range_label()

    def apply_manual_indices(self):
        if self.current_track_index is None: return
        pts = self.gpx_tracks[self.current_track_index]["points"]
        try:
            s_val = self.manual_start_entry.get().strip()
            e_val = self.manual_end_entry.get().strip()
            if s_val == "" or e_val == "":
                messagebox.showwarning("Manual indices", "Both start and end indices are required.")
                return
            s, e = int(s_val), int(e_val)
            if s < 0 or e < 0 or s >= len(pts) or e >= len(pts):
                messagebox.showwarning("Invalid indices",
                                        f"Indices must be between 0 and {len(pts)-1}")
                return
            self.selection_start = s
            self.selection_end   = e
            self.update_range_label()
            self.status_message(f"Manual indices applied: {s} → {e}")
        except ValueError:
            messagebox.showwarning("Invalid input", "Enter valid integer indices.")

    def update_range_label(self):
        if self.selection_start is None and self.selection_end is None:
            self.range_label.config(text="No selection", fg=C["muted"])
        else:
            s = self.selection_start if self.selection_start is not None else "?"
            e = self.selection_end   if self.selection_end   is not None else "?"
            self.range_label.config(text=f"Range:  {s}  →  {e}", fg=C["accent"])

    # ── Delete / Edit ─────────────────────────────────────────────────────────
    def delete_selected_range(self):
        if self.db_path is None:
            messagebox.showwarning("No DB", "Open a cache DB first."); return
        if self.current_track_index is None:
            messagebox.showwarning("No track", "Load a GPX track first."); return
        if self.selection_start is None or self.selection_end is None:
            messagebox.showwarning("No range", "Set start and end first."); return
        s, e = sorted([self.selection_start, self.selection_end])
        pts  = self.gpx_tracks[self.current_track_index]["points"][s:e+1]
        if not pts:
            messagebox.showinfo("No points", "No points found in selection."); return
        if not messagebox.askyesno("Confirm delete",
            f"This WILL delete cache entries for {len(pts)} points.\nBackup recommended.\nProceed?"):
            return
        bpath   = ensure_backup(self.db_path)
        deleted = 0
        for lat, lon, _ in pts:
            try:
                rc = db_write_execute(self.db_path,
                     "DELETE FROM geocode_cache WHERE key=?", (cache_key(lat, lon),))
                deleted += rc
            except Exception as ex:
                print("delete error:", ex)
        messagebox.showinfo("Done", f"Deleted approx {deleted} rows.\nBackup saved at:\n{bpath}")
        self.print_cache_stats()

    def open_edit_dialog(self):
        if self.current_track_index is None:
            messagebox.showwarning("No track", "Load a GPX track first."); return
        if self.selection_start is None or self.selection_end is None:
            messagebox.showwarning("No range", "Set start and end first."); return

        d = tk.Toplevel(self.root)
        d.title("Edit Selected Range")
        d.configure(bg=C["bg"])
        d.resizable(False, False)
        d.grab_set()

        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")
        tk.Label(d, text="EDIT SELECTED RANGE",
                 font=("Consolas", 10, "bold"), bg=C["bg"], fg=C["accent"]).pack(
                 padx=16, pady=(12, 4), anchor="w")
        tk.Label(d, text="Check 'Keep' to leave a field unchanged:",
                 font=("Consolas", 8), bg=C["bg"], fg=C["muted"]).pack(padx=16, anchor="w")
        tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=16, pady=8)

        frm = tk.Frame(d, bg=C["bg"]); frm.pack(fill="x", padx=16, pady=(0, 8))
        _ck = dict(bg=C["bg"], fg=C["text"], activebackground=C["bg"],
                   activeforeground=C["accent"], selectcolor=C["accent2"],
                   font=("Consolas", 9), relief="flat")

        self.keep_road = tk.BooleanVar(value=False)
        tk.Checkbutton(frm, text="Keep road (leave unchanged)",
                        variable=self.keep_road, **_ck).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(frm, text="Road:", font=("Consolas", 9),
                  bg=C["bg"], fg=C["muted"]).grid(row=1, column=0, sticky="e", padx=(0, 6), pady=4)
        self.road_entry = tk.Entry(frm, width=42,
                                    bg=C["panel2"], fg=C["text"],
                                    insertbackground=C["text"], relief="flat",
                                    highlightthickness=1, highlightcolor=C["accent"],
                                    highlightbackground=C["border"],
                                    font=("Consolas", 9))
        self.road_entry.grid(row=1, column=1, pady=4)

        self.keep_town = tk.BooleanVar(value=False)
        tk.Checkbutton(frm, text="Keep town (leave unchanged)",
                        variable=self.keep_town, **_ck).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tk.Label(frm, text="Town:", font=("Consolas", 9),
                  bg=C["bg"], fg=C["muted"]).grid(row=3, column=0, sticky="e", padx=(0, 6), pady=4)
        self.town_entry = tk.Entry(frm, width=42,
                                    bg=C["panel2"], fg=C["text"],
                                    insertbackground=C["text"], relief="flat",
                                    highlightthickness=1, highlightcolor=C["accent"],
                                    highlightbackground=C["border"],
                                    font=("Consolas", 9))
        self.town_entry.grid(row=3, column=1, pady=4)

        tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=16, pady=(4, 8))
        bf = tk.Frame(d, bg=C["bg"]); bf.pack(padx=16, pady=(0, 14))
        mk_btn(bf, "✅  Apply Edits", C["green"],  lambda: self.apply_edits(d)).pack(side="left", padx=(0, 6))
        mk_btn(bf, "Cancel",          C["dim"],    d.destroy).pack(side="left")
        tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")

    def apply_edits(self, edit_window):
        new_road  = self.road_entry.get().strip()
        new_town  = self.town_entry.get().strip()
        keep_road = self.keep_road.get()
        keep_town = self.keep_town.get()
        if keep_road and keep_town:
            messagebox.showinfo("Nothing to do", "Both fields set to KEEP. No changes made.")
            return
        s, e = sorted([self.selection_start, self.selection_end])
        pts  = self.gpx_tracks[self.current_track_index]["points"][s:e+1]
        if not pts:
            messagebox.showinfo("No points", "No points in selection."); return
        if not messagebox.askyesno("Confirm edit",
            f"Overwrite cache for {len(pts)} points?\n"
            f"Road: {'(unchanged)' if keep_road else new_road}\n"
            f"Town: {'(unchanged)' if keep_town else new_town}"):
            return
        bpath   = ensure_backup(self.db_path)
        updated = 0
        for lat, lon, _ in pts:
            k = cache_key(lat, lon)
            rows = db_read_all(self.db_path,
                   "SELECT key FROM geocode_cache WHERE key=?", (k,))
            if not rows: continue
            try:
                if not keep_road and not keep_town:
                    sql    = "UPDATE geocode_cache SET road=?, town=?, source='manual', timestamp=? WHERE key=?"
                    params = (new_road, new_town, now_utc_iso(), k)
                elif not keep_road:
                    sql    = "UPDATE geocode_cache SET road=?, source='manual', timestamp=? WHERE key=?"
                    params = (new_road, now_utc_iso(), k)
                elif not keep_town:
                    sql    = "UPDATE geocode_cache SET town=?, source='manual', timestamp=? WHERE key=?"
                    params = (new_town, now_utc_iso(), k)
                else:
                    continue
                rc = db_write_execute(self.db_path, sql, params)
                updated += rc
            except Exception as ex:
                print("update error:", ex)
        messagebox.showinfo("Done", f"Updated {updated} rows.\nBackup at:\n{bpath}")
        edit_window.destroy()
        self._clear_area_rect()
        self.area_clicks.clear()
        self.selection_start = None
        self.selection_end   = None
        self.update_range_label()
        self.print_cache_stats()

    # ── Area selection ────────────────────────────────────────────────────────
    def activate_area_selection(self):
        if self.current_track_index is None:
            messagebox.showwarning("No track", "Load a GPX track first."); return
        self.area_clicks = []
        self.status_message("Area selection: click 4 corners on the map")
        self.area_mode = True

    def _finalize_area_selection(self):
        if len(self.area_clicks) < 4:
            messagebox.showwarning("Area selection", "Need 4 points to define rectangle.")
            self.area_mode = False; return
        lats = [p[0] for p in self.area_clicks]
        lons = [p[1] for p in self.area_clicks]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        if self.current_track_index is None:
            messagebox.showwarning("No track", "Load a GPX track first.")
            self.area_mode = False; return
        pts    = self.gpx_tracks[self.current_track_index]["points"]
        inside = [i for i, (lat, lon, _) in enumerate(pts)
                  if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon]
        if not inside:
            messagebox.showinfo("No points", "No GPX points inside selected area.")
            self.area_mode = False; self.area_clicks = []; return
        self.selection_start = min(inside)
        self.selection_end   = max(inside)
        self.update_range_label()
        self.status_message(f"Area selected: {len(inside)} pts → {self.selection_start}..{self.selection_end}")
        try:
            rect_coords = [(max_lat, min_lon), (max_lat, max_lon),
                           (min_lat, max_lon), (min_lat, min_lon), (max_lat, min_lon)]
            self._clear_area_rect()
            self.area_rect_obj = self.map_widget.set_path(rect_coords,
                                                           color=C["teal"], width=2)
        except Exception: pass
        self.area_mode  = False
        self.area_clicks = []

    def _clear_area_rect(self):
        if self.area_rect_obj:
            try:    self.area_rect_obj.delete()
            except: pass
            self.area_rect_obj = None

    # ── Marker density ────────────────────────────────────────────────────────
    def change_marker_density(self):
        val = simpledialog.askinteger("Marker Density",
                                       "Show a marker every N points (1–50):",
                                       initialvalue=self.marker_density,
                                       minvalue=1, maxvalue=50)
        if val is None: return
        self.marker_density = val
        self.density_btn.config(text=f"Every {self.marker_density} pts")
        if self.current_track_index is not None:
            self.on_track_select()

    # ── Re-geocode ────────────────────────────────────────────────────────────
    def regeocode_gpx(self):
        if self.current_track_index is None:
            messagebox.showwarning("No track", "Load a GPX track first."); return
        trk      = self.gpx_tracks[self.current_track_index]
        gpx_path = trk["file"]
        if not os.path.exists(gpx_path):
            messagebox.showerror("File not found", f"Original GPX not found:\n{gpx_path}"); return
        if not messagebox.askyesno("Re-geocode",
            f"This will delete the geocoded GPX (if it exists) and relaunch the geocoder for:\n"
            f"{os.path.basename(gpx_path)}\nProceed?"):
            return
        base, ext = os.path.splitext(gpx_path)
        geocoded  = f"{base}_geocoded{ext}"
        try:
            if os.path.exists(geocoded):
                os.remove(geocoded)
                self.status_message(f"Deleted: {os.path.basename(geocoded)}")
        except Exception as ex:
            messagebox.showwarning("Delete error", f"Failed to delete {geocoded}\n{ex}"); return
        geocoder_script = os.path.join(os.path.dirname(__file__), "GPX_Geocoder.pyw")
        if not os.path.exists(geocoder_script):
            messagebox.showerror("Missing script",
                                  f"Cannot find GPX_Geocoder.pyw:\n{geocoder_script}"); return
        try:
            python_exe = sys.executable or "pythonw"
            subprocess.Popen([python_exe, geocoder_script, "--input", gpx_path],
                             cwd=os.path.dirname(__file__))
            messagebox.showinfo("Launched",
                                 f"GPX_Geocoder launched for:\n{os.path.basename(gpx_path)}")
            self.status_message("Launched re-geocoding process.")
        except Exception as ex:
            messagebox.showerror("Launch error", f"Failed to launch GPX_Geocoder.pyw:\n{ex}")

    # ── Utilities ─────────────────────────────────────────────────────────────
    def print_cache_stats(self):
        if not self.db_path or not os.path.exists(self.db_path):
            self.status_message("No DB loaded."); return
        try:
            rows  = db_read_all(self.db_path, "SELECT COUNT(*) FROM geocode_cache")
            total = rows[0][0] if rows else 0
            self.status_message(f"Cache: {total:,} rows  ·  {os.path.basename(self.db_path)}")
        except Exception as ex:
            self.status_message(f"Cache stats error: {ex}")

    def open_db(self):
        start_dir = DEFAULT_DB_FOLDER if os.path.isdir(DEFAULT_DB_FOLDER) else DESKTOP
        p = filedialog.askopenfilename(
            title="Select cache DB",
            filetypes=[("SQLite", "*.db *.sqlite"), ("All files", "*.*")],
            initialdir=start_dir)
        if not p: return
        self.db_path = p
        try:
            if self.conn:
                try: self.conn.close()
                except: pass
            self.conn = sqlite3.connect(self.db_path, timeout=5)
            try:
                self.conn.execute("PRAGMA journal_mode=WAL;")
                self.conn.execute("PRAGMA busy_timeout=5000;")
            except Exception: pass
            self._db_lbl.config(text=os.path.basename(p))
            self.status_message(f"DB opened: {os.path.basename(p)}")
            self.print_cache_stats()
        except Exception as ex:
            messagebox.showerror("DB open error", f"Failed to open DB:\n{ex}")

    def backup_db(self):
        if not self.db_path:
            messagebox.showwarning("No DB", "Open a cache DB first."); return
        try:
            dst = ensure_backup(self.db_path)
            messagebox.showinfo("Backup created", f"Backup written to:\n{dst}")
        except Exception as ex:
            messagebox.showerror("Backup error", f"Failed to create backup:\n{ex}")

    def status_message(self, text):
        try:
            self._status_label.config(text=text)
        except Exception: pass


# ──────────────────────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()
    app  = CacheEditor(root)
    root.mainloop()

if __name__ == "__main__":
    main()
