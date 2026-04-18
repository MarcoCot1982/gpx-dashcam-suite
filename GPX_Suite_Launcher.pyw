#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Dashcam Suite — Launcher  v1.1
Author : Marco Cot
Contact: marcocot1982@gmail.com

Single entry-point for all five suite apps.
v1.1: screenshot thumbnails in each card, loaded from a screenshots/ subfolder.
"""

import os
import sys
import subprocess
import threading
import base64
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
VERSION        = "v1.1"
AUTHOR         = "Marco Cot"
CONTACT        = "marcocot1982@gmail.com"
SPLASH_SECONDS = 3

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS_DIR = os.path.join(SCRIPT_DIR, "screenshots")

THUMB_W = 320   # thumbnail width  (px)
THUMB_H = 180   # thumbnail height (px)

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE
# ──────────────────────────────────────────────────────────────────────────────
C = {
    "bg":      "#141414",
    "panel":   "#1e1e1e",
    "panel2":  "#252525",
    "border":  "#333333",
    "accent":  "#f5a623",
    "accent2": "#e8941a",
    "green":   "#4caf50",
    "red":     "#e53935",
    "orange":  "#fb8c00",
    "blue":    "#2196F3",
    "teal":    "#26a69a",
    "purple":  "#ab47bc",
    "text":    "#e8e8e8",
    "muted":   "#888888",
    "dim":     "#555555",
}

# ──────────────────────────────────────────────────────────────────────────────
# APP DEFINITIONS
#   (display_name, script_file, icon_char, accent_color, description, step, screenshot_file)
# ──────────────────────────────────────────────────────────────────────────────
APPS = [
    (
        "Video \u2192 GPX",
        "video_to_gpx_v36_0_autosave_60s.pyw",
        "\U0001f3ac",
        C["blue"],
        "OCR-based GPS extractor\nReads coordinates burned into dashcam footage\nOutputs a raw .gpx track file",
        "STEP  1",
        "Video_to_GPX.png",
    ),
    (
        "GPX Ironer",
        "GPX_ironer.pyw",
        "\u2726",
        C["orange"],
        "Human-in-the-loop track cleaner\nRemove rogue points, bridge gaps, drag & reposition\nUndo stack \u00b7 auto-backup \u00b7 10-min auto-save",
        "STEP  2",
        "Ironer_1.jpg",
    ),
    (
        "GPX Geocoder",
        "GPX_Geocoder.pyw",
        "\u229b",
        C["accent"],
        "Reverse geocoder with SQLite cache\nPhoton + BAN (France) + Nominatim fallback\nNames every trackpoint \u2014 road, town, province",
        "STEP  3",
        "GEOCODER.jpg",
    ),
    (
        "Cache Editor",
        "Cache_Editor.pyw",
        "\u2b21",
        C["teal"],
        "SQLite cache management GUI\nInspect, edit or delete geocode entries by range\nArea-select on map \u00b7 re-geocode individual segments",
        "STEP  3b",
        "Cache_Editor.jpg",
    ),
    (
        "Towns Video",
        "Towns_video_dx.pyw",
        "\u25c8",
        C["purple"],
        "Location annotation video renderer\nOverlays road / town / country on your footage\nOpaque MP4 \u00b7 transparent WebM \u00b7 flag PNGs",
        "STEP  4",
        "Town_annotator.jpg",
    ),
]

# ──────────────────────────────────────────────────────────────────────────────
# ICON  (GPS pin ICO embedded as base64)
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

def _try_remove(path):
    try: os.remove(path)
    except: pass

# ──────────────────────────────────────────────────────────────────────────────
# THUMBNAIL LOADER  (PIL/Pillow)
# ──────────────────────────────────────────────────────────────────────────────
_thumb_cache = {}   # filename → tk.PhotoImage  (keep references alive)

def load_thumbnail(filename):
    """Load, centre-crop and resize a screenshot. Returns tk.PhotoImage or None."""
    if filename in _thumb_cache:
        return _thumb_cache[filename]
    path = os.path.join(SCREENSHOTS_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        from PIL import Image, ImageTk
        img = Image.open(path).convert("RGB")
        iw, ih = img.size
        target_ratio = THUMB_W / THUMB_H
        actual_ratio = iw / ih
        if actual_ratio > target_ratio:
            new_w = int(ih * target_ratio)
            left  = (iw - new_w) // 2
            img   = img.crop((left, 0, left + new_w, ih))
        elif actual_ratio < target_ratio:
            new_h = int(iw / target_ratio)
            top   = (ih - new_h) // 2
            img   = img.crop((0, top, iw, top + new_h))
        img   = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
        tkimg = ImageTk.PhotoImage(img)
        _thumb_cache[filename] = tkimg
        return tkimg
    except Exception:
        return None

# ──────────────────────────────────────────────────────────────────────────────
# LAUNCH
# ──────────────────────────────────────────────────────────────────────────────
def launch_app(filename, status_lbl):
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        messagebox.showerror("File not found",
            f"Cannot find:\n{path}\n\nMake sure all suite files are in the same folder as the launcher.")
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

    status_lbl.config(text=f"Launched  \u00b7  {os.path.splitext(filename)[0]}")
    threading.Thread(target=_run, daemon=True).start()

# ──────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def sec_hdr(parent, text):
    f = tk.Frame(parent, bg=C["panel"]); f.pack(fill="x", padx=16, pady=(14, 4))
    tk.Label(f, text=text, font=("Consolas", 8, "bold"),
             bg=C["panel"], fg=C["accent"]).pack(side="left")
    tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=16)

# ──────────────────────────────────────────────────────────────────────────────
# APP CARD
# ──────────────────────────────────────────────────────────────────────────────
def make_card(parent, name, filename, icon, accent, desc, step, screenshot, status_lbl):
    outer = tk.Frame(parent, bg=C["panel2"], cursor="hand2")
    outer.pack(fill="x", padx=16, pady=6)

    # left accent stripe
    stripe = tk.Frame(outer, bg=accent, width=4); stripe.pack(side="left", fill="y")

    # ── right: screenshot thumbnail ───────────────────────────────────────────
    thumb = load_thumbnail(screenshot)
    if thumb:
        thumb_border = tk.Frame(outer, bg=accent, padx=1, pady=1)
        thumb_border.pack(side="right", padx=(8, 10), pady=10)
        thumb_lbl = tk.Label(thumb_border, image=thumb, bg=C["border"])
        thumb_lbl.image = thumb   # keep reference alive
        thumb_lbl.pack()
    else:
        ph = tk.Frame(outer, bg=C["panel"], width=THUMB_W, height=THUMB_H)
        ph.pack(side="right", padx=(8, 10), pady=10)
        ph.pack_propagate(False)
        tk.Label(ph, text="no preview", font=("Consolas", 8),
                 bg=C["panel"], fg=C["dim"]).place(relx=0.5, rely=0.5, anchor="center")

    # ── centre: text content ─────────────────────────────────────────────────
    body = tk.Frame(outer, bg=C["panel2"]); body.pack(side="left", fill="both", expand=True, padx=14, pady=14)

    top = tk.Frame(body, bg=C["panel2"]); top.pack(fill="x")
    badge = tk.Label(top, text=step, font=("Consolas", 7, "bold"),
                     bg=accent, fg="black", padx=5, pady=1)
    badge.pack(side="left", padx=(0, 10))
    title_lbl = tk.Label(top, text=name, font=("Consolas", 13, "bold"),
                          bg=C["panel2"], fg=C["text"])
    title_lbl.pack(side="left")
    icon_lbl = tk.Label(top, text=icon, font=("Consolas", 20),
                        bg=C["panel2"], fg=accent)
    icon_lbl.pack(side="right", padx=(0, 4))

    desc_lbl = tk.Label(body, text=desc, font=("Consolas", 8),
                         bg=C["panel2"], fg=C["muted"], justify="left", anchor="w")
    desc_lbl.pack(fill="x", pady=(8, 0))

    path   = os.path.join(SCRIPT_DIR, filename)
    avail  = os.path.exists(path)
    file_lbl = tk.Label(body,
                         text=f"  {filename}" if avail else f"  \u26a0  {filename}  (not found)",
                         font=("Consolas", 7, "italic"),
                         bg=C["panel2"], fg=C["dim"] if avail else C["red"], anchor="w")
    file_lbl.pack(fill="x", pady=(4, 0))

    btn = tk.Button(body, text="\u25b6  Launch",
                    font=("Consolas", 9, "bold"),
                    bg=accent, fg="black",
                    activebackground=C["accent2"], activeforeground="black",
                    relief="flat", cursor="hand2", pady=5, padx=14,
                    command=lambda: launch_app(filename, status_lbl))
    btn.pack(anchor="w", pady=(12, 0))
    if not avail:
        btn.config(state="disabled", bg=C["dim"], fg=C["muted"])

    # ── hover: lighten card background ───────────────────────────────────────
    hover_widgets = [outer, body, top, badge, title_lbl, icon_lbl, desc_lbl, file_lbl]

    def _enter(_e):
        for w in hover_widgets:
            try: w.config(bg=C["panel"])
            except: pass

    def _leave(_e):
        for w in hover_widgets:
            try: w.config(bg=C["panel2"])
            except: pass

    for w in [outer, body, top]:
        w.bind("<Enter>", _enter)
        w.bind("<Leave>", _leave)

    return outer

# ──────────────────────────────────────────────────────────────────────────────
# ROOT WINDOW
# ──────────────────────────────────────────────────────────────────────────────
root = tk.Tk()
_apply_icon(root)
root.title(f"GPX Dashcam Suite  {VERSION}")
root.configure(bg=C["bg"])
root.resizable(True, True)

sty = ttk.Style(root); sty.theme_use("clam")
sty.configure(".",      background=C["bg"], foreground=C["text"])
sty.configure("TLabel", background=C["bg"], foreground=C["text"], font=("Consolas", 9))
sty.configure("TFrame", background=C["bg"])
sty.configure("Horizontal.TProgressbar",
               background=C["accent"], troughcolor=C["panel2"],
               bordercolor=C["border"], lightcolor=C["accent"], darkcolor=C["accent2"])

# ──────────────────────────────────────────────────────────────────────────────
# SPLASH
# ──────────────────────────────────────────────────────────────────────────────
def show_splash_then_main():
    sp = tk.Toplevel(root); sp.overrideredirect(True); sp.configure(bg=C["bg"])
    sw, sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w, h = 660, 320; sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x")
    body = tk.Frame(sp, bg=C["bg"]); body.pack(expand=True, fill="both", padx=48)
    tk.Label(body, text="GPX DASHCAM SUITE",
             font=("Consolas", 24, "bold"), bg=C["bg"], fg=C["accent"]).pack(pady=(30, 4))
    tk.Label(body, text=f"{VERSION}  \u00b7  by {AUTHOR}  \u00b7  {datetime.now().year}",
             font=("Consolas", 9), bg=C["bg"], fg=C["muted"]).pack()
    tk.Label(body, text="video  \u2192  gpx  \u2192  iron  \u2192  geocode  \u2192  annotate",
             font=("Consolas", 9, "italic"), bg=C["bg"], fg=C["dim"]).pack(pady=(6, 18))
    pbv = tk.DoubleVar()
    ttk.Progressbar(body, variable=pbv, maximum=100, length=560).pack()
    pct = tk.Label(body, text="0%", font=("Consolas", 8), bg=C["bg"], fg=C["dim"]); pct.pack(pady=4)
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")

    steps = max(15, SPLASH_SECONDS * 20)
    interval_ms = int(SPLASH_SECONDS * 1000 / steps)

    def _step(i):
        if not sp.winfo_exists(): return
        val = int(i / steps * 100); pbv.set(val); pct.config(text=f"{val}%")
        if i < steps:
            root.after(interval_ms, _step, i + 1)
        else:
            sp.destroy(); root.deiconify()
            root.update_idletasks()
            root.minsize(900, 500)
            sw2, sh2 = root.winfo_screenwidth(), root.winfo_screenheight()
            rw, rh = 1140, 860
            root.geometry(f"{rw}x{rh}+{(sw2-rw)//2}+{(sh2-rh)//2}")

    root.withdraw()
    root.after(interval_ms, _step, 1)

show_splash_then_main()

# ──────────────────────────────────────────────────────────────────────────────
# CHROME
# ──────────────────────────────────────────────────────────────────────────────
tk.Frame(root, bg=C["accent"], height=3).pack(fill="x")
tb = tk.Frame(root, bg=C["bg"]); tb.pack(fill="x", padx=20, pady=7)
tk.Label(tb, text="GPX DASHCAM SUITE",
         font=("Consolas", 15, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
tk.Label(tb, text=f"{VERSION}  \u00b7  {AUTHOR}  \u00b7  {datetime.now().year}",
         font=("Consolas", 8), bg=C["bg"], fg=C["dim"]).pack(side="right")
tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

sub = tk.Frame(root, bg=C["bg"]); sub.pack(fill="x", padx=20, pady=(8, 0))
for label, col in [
    ("video", C["blue"]), (" \u2192 ", C["dim"]),
    ("gpx",   C["orange"]), (" \u2192 ", C["dim"]),
    ("iron",  C["accent"]), (" \u2192 ", C["dim"]),
    ("geocode", C["accent"]), (" \u2192 ", C["dim"]),
    ("annotate", C["purple"]),
]:
    tk.Label(sub, text=label, font=("Consolas", 9, "bold"), bg=C["bg"], fg=col).pack(side="left")

# ──────────────────────────────────────────────────────────────────────────────
# STATUS BAR
# ──────────────────────────────────────────────────────────────────────────────
sb = tk.Frame(root, bg=C["panel"], height=26); sb.pack(fill="x", side="bottom")
tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")
status_lbl = tk.Label(sb, text="Select an app to launch.",
                       font=("Consolas", 8), bg=C["panel"], fg=C["muted"])
status_lbl.pack(side="left", padx=12, pady=3)
tk.Label(sb, text=f"Suite dir:  {SCRIPT_DIR}",
         font=("Consolas", 7), bg=C["panel"], fg=C["dim"]).pack(side="right", padx=12, pady=3)

# ──────────────────────────────────────────────────────────────────────────────
# SCROLLABLE CARD AREA
# ──────────────────────────────────────────────────────────────────────────────
canvas_frame = tk.Frame(root, bg=C["bg"]); canvas_frame.pack(fill="both", expand=True, pady=(10, 0))
canvas = tk.Canvas(canvas_frame, bg=C["bg"], highlightthickness=0)
vsb    = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
canvas.configure(yscrollcommand=vsb.set)
vsb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)

inner = tk.Frame(canvas, bg=C["bg"])
_win  = canvas.create_window((0, 0), window=inner, anchor="nw")

inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
canvas.bind("<Configure>", lambda e: canvas.itemconfig(_win, width=e.width))

def _scroll(e):
    units = int(-1 * (e.delta / 120)) if e.delta else (-1 if e.num == 4 else 1)
    canvas.yview_scroll(units, "units")
root.bind("<MouseWheel>", _scroll, add="+")
root.bind("<Button-4>",   _scroll, add="+")
root.bind("<Button-5>",   _scroll, add="+")

# ──────────────────────────────────────────────────────────────────────────────
# CARDS
# ──────────────────────────────────────────────────────────────────────────────
sec_hdr(inner, "PROCESSING PIPELINE")
tk.Label(inner,
         text="Launch any tool independently \u2014 or follow the pipeline from top to bottom.",
         font=("Consolas", 8, "italic"), bg=C["bg"], fg=C["dim"]).pack(padx=16, anchor="w", pady=(0, 6))

for (name, filename, icon, accent, desc, step, screenshot) in APPS:
    make_card(inner, name, filename, icon, accent, desc, step, screenshot, status_lbl)

# ──────────────────────────────────────────────────────────────────────────────
# ABOUT
# ──────────────────────────────────────────────────────────────────────────────
tk.Frame(inner, bg=C["bg"], height=8).pack()
sec_hdr(inner, "ABOUT")
about_f = tk.Frame(inner, bg=C["panel2"]); about_f.pack(fill="x", padx=16, pady=(0, 16))
tk.Frame(about_f, bg=C["accent"], width=4).pack(side="left", fill="y")
ab = tk.Frame(about_f, bg=C["panel2"]); ab.pack(side="left", padx=14, pady=12)
tk.Label(ab, text=f"GPX Dashcam Suite  {VERSION}",
         font=("Consolas", 10, "bold"), bg=C["panel2"], fg=C["accent"]).pack(anchor="w")
tk.Label(ab, text=f"Author: {AUTHOR}  \u00b7  {CONTACT}",
         font=("Consolas", 8), bg=C["panel2"], fg=C["muted"]).pack(anchor="w", pady=(2, 0))
tk.Label(ab,
         text="A complete pipeline to extract, clean, geocode and annotate GPS tracks from dashcam footage.",
         font=("Consolas", 8), bg=C["panel2"], fg=C["dim"], justify="left").pack(anchor="w", pady=(4, 0))
ss_ok  = os.path.isdir(SCREENSHOTS_DIR)
ss_col = C["dim"] if ss_ok else C["red"]
ss_txt = f"Screenshots:  {SCREENSHOTS_DIR}" if ss_ok else f"\u26a0  Screenshots folder not found:  {SCREENSHOTS_DIR}"
tk.Label(ab, text=ss_txt, font=("Consolas", 7, "italic"),
         bg=C["panel2"], fg=ss_col).pack(anchor="w", pady=(6, 0))

# ──────────────────────────────────────────────────────────────────────────────
root.protocol("WM_DELETE_WINDOW", root.destroy)

if __name__ == "__main__":
    root.mainloop()
