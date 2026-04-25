#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Dashcam Suite Launcher  v1.1
Author : Marco Cot
Contact: marcocot1982@gmail.com

Central launcher for all tools in the GPX Dashcam Suite pipeline.
v1.1: added Overlay Compositor (step 6)
"""

import os, sys, subprocess, tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageDraw, ImageTk
from datetime import datetime

VERSION    = "v1.1"
AUTHOR     = "Marco Cot"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

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
    "purple": "#7e57c2",
    "text":   "#e8e8e8",
    "muted":  "#888888",
    "dim":    "#555555",
}

# ── Pipeline tool definitions ─────────────────────────────────────────────────
TOOLS = [
    {
        "step":  1,
        "name":  "Video → GPX",
        "desc":  "Extract GPS coordinates from\ndashcam footage via OCR",
        "files": ["video_to_gpx_v36_0_autosave_60s.pyw",
                  "video_to_gpx.pyw", "Video_to_GPX.pyw"],
        "color": C["blue"],
        "icon":  "📹",
    },
    {
        "step":  2,
        "name":  "GPX Ironer",
        "desc":  "Clean and edit raw GPX tracks\ninteractively on a live map",
        "files": ["GPX_ironer.pyw", "GPX_Ironer.pyw", "gpx_ironer.pyw"],
        "color": C["orange"],
        "icon":  "✏️",
    },
    {
        "step":  3,
        "name":  "GPX Geocoder",
        "desc":  "Reverse-geocode GPS points\nwith road, town and country",
        "files": ["GPX_Geocoder.pyw", "GPX_geocoder.pyw", "gpx_geocoder.pyw"],
        "color": C["green"],
        "icon":  "🌍",
    },
    {
        "step":  4,
        "name":  "Cache Editor",
        "desc":  "Inspect and correct the\ngeocode SQLite cache database",
        "files": ["Cache_Editor.pyw", "cache_editor.pyw", "Cache_editor.pyw"],
        "color": C["teal"],
        "icon":  "🗄️",
    },
    {
        "step":  5,
        "name":  "Towns Video",
        "desc":  "Render geocoded GPX comments\ninto a comment-overlay video",
        "files": ["Towns_video_dx.pyw", "towns_video_dx.pyw", "Towns_video.pyw"],
        "color": C["purple"],
        "icon":  "🎬",
    },
    {
        "step":  6,
        "name":  "Overlay Compositor",
        "desc":  "Composite the comment video\nonto the original dashcam footage",
        "files": ["overlay_compositor.pyw", "Overlay_compositor.pyw",
                  "Overlay_Compositor.pyw"],
        "color": C["accent"],
        "icon":  "🗺️",
    },
]

# ──────────────────────────────────────────────────────────────────────────────
# ICON
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
        imgs    = [_make_icon_image(sz) for sz in (16, 24, 32, 48)]
        tk_imgs = [ImageTk.PhotoImage(im) for im in imgs]
        root._icon_refs = tk_imgs
        root.iconphoto(True, *tk_imgs)
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# LAUNCH HELPER
# ──────────────────────────────────────────────────────────────────────────────
def launch_tool(tool, status_lbl):
    for fname in tool["files"]:
        p = os.path.join(SCRIPT_DIR, fname)
        if os.path.exists(p):
            try:
                subprocess.Popen([sys.executable, p], creationflags=_NO_WINDOW)
                status_lbl.config(
                    text=f"✅  Launched: {tool['name']}  ({fname})",
                    fg=C["green"])
                return
            except Exception as e:
                status_lbl.config(text=f"❌  Error launching {fname}: {e}", fg=C["red"])
                return
    # not found — ask user
    p = filedialog.askopenfilename(
        title=f"Locate {tool['name']}",
        filetypes=[("Python files", "*.py *.pyw")],
        initialdir=SCRIPT_DIR)
    if p:
        try:
            subprocess.Popen([sys.executable, p], creationflags=_NO_WINDOW)
            status_lbl.config(text=f"✅  Launched: {os.path.basename(p)}", fg=C["green"])
        except Exception as e:
            status_lbl.config(text=f"❌  Error: {e}", fg=C["red"])
    else:
        status_lbl.config(
            text=f"⚠  {tool['name']} not found in suite folder.",
            fg=C["orange"])

# ──────────────────────────────────────────────────────────────────────────────
# BUILD UI
# ──────────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("GPX Dashcam Suite")
apply_window_icon(root)
root.configure(bg=C["bg"])
root.resizable(False, False)

sty = ttk.Style(root); sty.theme_use("clam")
sty.configure(".", background=C["bg"], foreground=C["text"])
sty.configure("TLabel", background=C["bg"], foreground=C["text"], font=("Consolas", 9))

# top chrome
tk.Frame(root, bg=C["accent"], height=3).pack(fill="x")
tb = tk.Frame(root, bg=C["bg"]); tb.pack(fill="x", padx=20, pady=10)
tk.Label(tb, text="GPX DASHCAM SUITE",
         font=("Consolas", 18, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
tk.Label(tb, text=f"Launcher {VERSION}  ·  {AUTHOR}",
         font=("Consolas", 8), bg=C["bg"], fg=C["dim"]).pack(side="right", anchor="s")
tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

# pipeline label
tk.Label(root,
         text="  SELECT A TOOL TO LAUNCH  —  run them in order for the full pipeline",
         font=("Consolas", 8, "bold"), bg=C["bg"], fg=C["muted"]).pack(
         anchor="w", padx=20, pady=(10, 4))

# tool cards
cards_frame = tk.Frame(root, bg=C["bg"]); cards_frame.pack(padx=20, pady=4)

status_lbl = tk.Label(root, text="", font=("Consolas", 8),
                       bg=C["bg"], fg=C["muted"], anchor="w")

for i, tool in enumerate(TOOLS):
    col  = tool["color"]
    card = tk.Frame(cards_frame, bg=C["panel"], padx=0, pady=0)
    card.grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky="nsew")
    cards_frame.grid_columnconfigure(i % 3, weight=1)

    # coloured step bar on the left
    bar = tk.Frame(card, bg=col, width=5); bar.pack(side="left", fill="y")

    inner = tk.Frame(card, bg=C["panel"]); inner.pack(side="left", fill="both",
                                                        expand=True, padx=12, pady=10)
    # step badge
    badge_row = tk.Frame(inner, bg=C["panel"]); badge_row.pack(anchor="w")
    tk.Label(badge_row, text=f"STEP {tool['step']}",
             font=("Consolas", 7, "bold"), bg=col, fg="black",
             padx=5, pady=1).pack(side="left")

    # icon + name
    tk.Label(inner, text=f"{tool['icon']}  {tool['name']}",
             font=("Consolas", 11, "bold"), bg=C["panel"],
             fg=C["text"]).pack(anchor="w", pady=(4, 0))

    # description
    tk.Label(inner, text=tool["desc"],
             font=("Consolas", 8), bg=C["panel"], fg=C["muted"],
             justify="left").pack(anchor="w", pady=(2, 6))

    # launch button
    btn = tk.Button(inner,
                    text=f"▶  Launch",
                    bg=col, fg="black",
                    activebackground=col, activeforeground="black",
                    relief="flat", cursor="hand2",
                    font=("Consolas", 8, "bold"), pady=3, padx=10,
                    command=lambda t=tool: launch_tool(t, status_lbl))
    btn.pack(anchor="w")

# pipeline arrow between rows (decorative)
tk.Label(root, text="  ↓  full pipeline runs top-left → bottom-right",
         font=("Consolas", 7), bg=C["bg"], fg=C["dim"]).pack(anchor="w", padx=20, pady=(0, 6))

# status bar
tk.Frame(root, bg=C["border"], height=1).pack(fill="x", padx=0)
status_lbl.pack(fill="x", padx=20, pady=6)

# bottom chrome
tk.Frame(root, bg=C["accent"], height=3).pack(fill="x", side="bottom")

if __name__ == "__main__":
    root.mainloop()
