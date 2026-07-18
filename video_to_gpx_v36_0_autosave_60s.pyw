import os
import re
import time
import threading
import cv2
import numpy as np
import pytesseract
from datetime import datetime, timedelta
from tkinter import Tk, Frame, Label, Button, Entry, StringVar, ttk, scrolledtext, filedialog
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from staticmap import StaticMap, CircleMarker

# ---------------- CONFIG ----------------
VERSION = "v36.0_OCR_AutoStop_DynamicNaming_ProvisionalSave"
ROI_DEFAULT = (0.32, 0.56, 0.90, 1.00)
TESS_CONFIG_BASE = r'-c tessedit_char_whitelist=0123456789NnSsEeWw°.,-'
TESS_PSMS = [7, 6]

FLOAT5_RE      = re.compile(r'(-?\d{1,3}\.\d{5})')
FLOAT_LOOSE_RE = re.compile(r'(-?\d{1,3}\.\d{4,5})')
FLOAT_GENERIC_RE = re.compile(r'(-?\d+\.\d+)')

# ──────────────────────────────────────────────────────────────────────────────
# WINDOW ICON  (GPS pin + film-strip holes, drawn with PIL — no external files)
# ──────────────────────────────────────────────────────────────────────────────
def _make_icon_image(size):
    """Draw a GPS map-pin with film-strip sprocket holes in the app's orange."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    s   = size
    pin_cx    = s // 2
    pin_top   = int(s * 0.04)
    pin_r     = int(s * 0.36)
    circle_bot = pin_top + pin_r * 2
    pin_tip   = int(s * 0.93)
    inner_cy  = pin_top + pin_r

    # Drop shadow
    sc = (120, 60, 0, 140)
    d.ellipse([pin_cx-pin_r+2, pin_top+2, pin_cx+pin_r+2, circle_bot+2], fill=sc)
    d.polygon([(pin_cx-pin_r//2+2, circle_bot+1),
               (pin_cx+pin_r//2+2, circle_bot+1),
               (pin_cx+2,          pin_tip+2)], fill=sc)

    # Pin body — amber orange
    orange = (245, 166, 35, 255)
    d.ellipse([pin_cx-pin_r, pin_top, pin_cx+pin_r, circle_bot], fill=orange)
    d.polygon([(pin_cx-pin_r//2, circle_bot-1),
               (pin_cx+pin_r//2, circle_bot-1),
               (pin_cx,          pin_tip)], fill=orange)
    d.ellipse([pin_cx-pin_r, pin_top, pin_cx+pin_r, circle_bot],
              outline=(180, 110, 0, 255), width=max(1, s // 32))

    # Film-strip sprocket holes (3 pairs inside the circle)
    hole_h  = max(3, int(s * 0.09))
    hole_w  = max(2, int(s * 0.06))
    gap     = max(2, int(s * 0.06))
    strip_w = 3 * hole_w + 2 * gap
    sx      = pin_cx - strip_w // 2
    voff    = max(1, s // 20)
    hc      = (30, 15, 0, 255)
    for i in range(3):
        hx = sx + i * (hole_w + gap)
        d.rectangle([hx, inner_cy - hole_h - voff, hx + hole_w, inner_cy - voff], fill=hc)
        d.rectangle([hx, inner_cy + voff,           hx + hole_w, inner_cy + hole_h + voff], fill=hc)

    # White "you are here" centre dot
    dr = max(2, int(s * 0.11))
    d.ellipse([pin_cx-dr, inner_cy-dr, pin_cx+dr, inner_cy+dr],
              fill=(255, 255, 255, 235))
    return img

def apply_window_icon(root):
    """Attach the programmatically-drawn icon to a Tk window (Windows-safe)."""
    try:
        imgs    = [_make_icon_image(sz) for sz in (16, 24, 32, 48)]
        tk_imgs = [ImageTk.PhotoImage(im) for im in imgs]
        root._icon_refs = tk_imgs   # keep refs alive — GC would blank the icon
        root.iconphoto(True, *tk_imgs)
    except Exception:
        pass   # icon is cosmetic — never crash for it

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE  (shared with GPX Ironer / Geocoder / Cache Editor)
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
def mk_btn(parent, text, bg, cmd, state="normal", width=None, font=("segoe ui", 9, "bold")):
    kw = dict(
        text=text, bg=bg,
        fg="white" if bg not in (C["dim"], C["panel2"]) else C["muted"],
        activebackground=bg, activeforeground="white",
        disabledforeground=C["dim"],
        relief="flat", cursor="hand2", command=cmd,
        font=font, pady=5, padx=8, state=state,
    )
    if width: kw["width"] = width
    return tk.Button(parent, **kw)

def sec_hdr(parent, text):
    f = tk.Frame(parent, bg=C["panel"]); f.pack(fill="x", padx=10, pady=(12, 3))
    tk.Label(f, text=text, font=("segoe ui", 8, "bold"),
             bg=C["panel"], fg=C["accent"]).pack(side="left")
    tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=10)

def mk_entry(parent, textvariable, width=20):
    return tk.Entry(parent, textvariable=textvariable, width=width,
                    bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
                    relief="flat", highlightthickness=1,
                    highlightcolor=C["accent"], highlightbackground=C["border"],
                    font=("segoe ui", 9))

def mk_lbl(parent, text, fg=None, font=None):
    return tk.Label(parent, text=text,
                    bg=C["panel"], fg=fg or C["muted"],
                    font=font or ("segoe ui", 8))

def accent_border(parent):
    """Returns (outer_frame, inner_frame) — put content inside inner_frame."""
    outer = tk.Frame(parent, bg=C["accent"], padx=1, pady=1)
    inner = tk.Frame(outer, bg=C["panel2"])
    inner.pack(fill="both", expand=True)
    return outer, inner

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS (unchanged)
# ──────────────────────────────────────────────────────────────────────────────
def ensure_output_folder():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    outdir  = os.path.join(desktop, "OCR")
    os.makedirs(outdir, exist_ok=True)
    return outdir

def parse_hms_to_seconds(hms_str):
    try:
        parts = list(map(int, hms_str.split(':')))
        if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
        if len(parts) == 2: return parts[0]*60 + parts[1]
        return int(hms_str)
    except: return 0

def format_time_hms(seconds):
    return str(timedelta(seconds=int(seconds))).zfill(8)

def format_time_compact(seconds):
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}{minutes:02d}{seconds:02d}"

def write_gpx_latlon_time(points, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="DashcamToGPX" xmlns="http://www.topografix.com/GPX/1/1">\n')
        f.write('  <trk><n>Extracted track</n><trkseg>\n')
        for t, lat, lon in points:
            timestr = t.isoformat() + "Z" if isinstance(t, datetime) else str(t)
            f.write(f'  <trkpt lat="{float(lat):.6f}" lon="{float(lon):.6f}">\n')
            f.write(f'  <ele>0.0</ele><time>{timestr}</time>\n  </trkpt>\n')
        f.write('  </trkseg></trk>\n</gpx>\n')

def build_map_image_single(lat, lon, size_px=(540, 480)):
    try:
        sm = StaticMap(size_px[0], size_px[1],
                       url_template='https://a.tile.openstreetmap.org/{z}/{x}/{y}.png')
        sm.add_marker(CircleMarker((lon, lat), 'red', 14))
        return sm.render(zoom=16)
    except:
        return Image.new("RGB", size_px, (30, 30, 30))

# --- OCR LOGIC (unchanged) ---
def preprocess_attempts_for_ocr(crop_bgr):
    results = []
    try:
        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        scale = 4 if h < 60 else 3
        gray_big = cv2.resize(gray, (w*scale, h*scale), interpolation=cv2.INTER_CUBIC)
        results.append(gray_big)
        clahe = cv2.createCLAHE(clipLimit=3, tileGridSize=(8, 8))
        results.append(clahe.apply(gray_big))
        eq   = cv2.equalizeHist(gray_big)
        results.append(eq)
        blur = cv2.medianBlur(eq, 3)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        results.append(otsu)
    except: pass
    return [Image.fromarray(cv2.cvtColor(res, cv2.COLOR_GRAY2RGB)) for res in results]

def extract_coords_from_text(text):
    if not text: return None
    filtered_txt = re.sub(r'[^\x20-\x7E\n\r\t°\.,-]', '', text)
    txt    = filtered_txt.replace(',', '.').replace('°', '').replace(' ', '')
    floats = FLOAT5_RE.findall(txt) or FLOAT_LOOSE_RE.findall(txt) or FLOAT_GENERIC_RE.findall(txt)
    if len(floats) < 2: return None
    try:    return float(floats[0]), float(floats[1]), filtered_txt
    except: return None

def extract_ocr_coords_from_frame(frame):
    h, w = frame.shape[:2]
    x1, x2 = int(w * ROI_DEFAULT[0]), int(w * ROI_DEFAULT[1])
    y1, y2 = int(h * ROI_DEFAULT[2]), int(h * ROI_DEFAULT[3])
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0: return None
    pil_images = preprocess_attempts_for_ocr(crop)
    for psm in TESS_PSMS:
        config = f'--psm {psm} {TESS_CONFIG_BASE}'
        for pil in pil_images:
            try:
                txt = pytesseract.image_to_string(pil, config=config)
                res = extract_coords_from_text(txt)
                if res: return res
            except: pass
    return None

# ──────────────────────────────────────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────────────────────────────────────
class App:
    def __init__(self, root):
        self.root = root
        root.title(f"DashcamToGPX  {VERSION}")
        apply_window_icon(root)
        root.configure(bg=C["bg"])
        root.geometry("1400x900")
        root.resizable(True, True)

        self.stop_requested   = False
        self.frame_data_points = []

        # ── ttk style ──────────────────────────────────────────────────────────
        sty = ttk.Style(root); sty.theme_use("clam")
        sty.configure(".",          background=C["bg"],    foreground=C["text"])
        sty.configure("TLabel",     background=C["bg"],    foreground=C["text"], font=("segoe ui", 9))
        sty.configure("TFrame",     background=C["bg"])
        sty.configure("TScrollbar", background=C["panel2"], troughcolor=C["border"],
                                    arrowcolor=C["muted"])
        sty.configure("Horizontal.TProgressbar",
                       background=C["accent"], troughcolor=C["panel2"],
                       bordercolor=C["border"], lightcolor=C["accent"],
                       darkcolor=C["accent2"])

        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Top chrome ────────────────────────────────────────────────────────
        tk.Frame(self.root, bg=C["accent"], height=3).pack(fill="x")
        tb = tk.Frame(self.root, bg=C["bg"]); tb.pack(fill="x", padx=16, pady=5)
        tk.Label(tb, text="DASHCAM  →  GPX",
                 font=("segoe ui", 13, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
        tk.Label(tb, text=f"{VERSION}  ·  Marco Cot  ·  2025–{datetime.now().year}",
                 font=("segoe ui", 8), bg=C["bg"], fg=C["dim"]).pack(side="right")
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=C["bg"]); body.pack(fill="both", expand=True)

        # ════════════════ LEFT SIDEBAR (controls) ═════════════════════════════
        left_sidebar = tk.Frame(body, bg=C["panel"], width=230)
        left_sidebar.pack(side="left", fill="y", padx=(10, 0), pady=10)
        left_sidebar.pack_propagate(False)

        # — File ——————————————————————————————————————————————————————————————
        sec_hdr(left_sidebar, "FILE")
        btn_f = tk.Frame(left_sidebar, bg=C["panel"]); btn_f.pack(fill="x", padx=10, pady=6)
        self.start_btn = mk_btn(btn_f, "📂  Select Video(s) & Start",
                                C["green"], self.select_and_start)
        self.start_btn.pack(fill="x", pady=2)
        self.stop_btn = mk_btn(btn_f, "⏹  Stop & Save Now",
                               C["red"], self.request_stop, state="disabled")
        self.stop_btn.pack(fill="x", pady=2)

        # — Timing ————————————————————————————————————————————————————————————
        sec_hdr(left_sidebar, "TIMING")
        tm = tk.Frame(left_sidebar, bg=C["panel"]); tm.pack(fill="x", padx=10, pady=6)

        mk_lbl(tm, "Video Offset (Start):").pack(anchor="w")
        self.offset_var = StringVar(value="00:00:00")
        mk_entry(tm, self.offset_var).pack(fill="x", pady=(2, 6))

        mk_lbl(tm, "Auto-stop at (HH:MM:SS):").pack(anchor="w")
        self.autostop_var = StringVar(value="23:59:59")
        mk_entry(tm, self.autostop_var).pack(fill="x", pady=(2, 6))

        mk_lbl(tm, "Recalibrate after (sec):").pack(anchor="w")
        self.recal_trigger_var = StringVar(value="60")
        mk_entry(tm, self.recal_trigger_var).pack(fill="x", pady=(2, 6))

        mk_lbl(tm, "Provisional save every (vid sec):").pack(anchor="w")
        self.provisional_interval_var = StringVar(value="60")
        mk_entry(tm, self.provisional_interval_var).pack(fill="x", pady=(2, 0))

        # — Date Source ———————————————————————————————————————————————————————
        sec_hdr(left_sidebar, "DATE SOURCE")
        ds = tk.Frame(left_sidebar, bg=C["panel"]); ds.pack(fill="x", padx=10, pady=6)
        self.use_fname_var = StringVar(value="use")
        _rkw = dict(bg=C["panel"], fg=C["text"],
                    activebackground=C["panel"], activeforeground=C["accent"],
                    selectcolor=C["accent2"], font=("segoe ui", 8),
                    anchor="w", relief="flat")
        tk.Radiobutton(ds, text="Date from Filename",
                        variable=self.use_fname_var, value="use",
                        **_rkw).pack(fill="x", pady=1)
        tk.Radiobutton(ds, text="Manual Date",
                        variable=self.use_fname_var, value="manual",
                        **_rkw).pack(fill="x", pady=1)

        mk_lbl(ds, "Manual Start Date:").pack(anchor="w", pady=(6, 0))
        self.dt_var = StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        mk_entry(ds, self.dt_var).pack(fill="x", pady=(2, 0))

        # ════════════════ MAIN CONTENT AREA ═══════════════════════════════════
        main_area = tk.Frame(body, bg=C["bg"])
        main_area.pack(side="left", fill="both", expand=True, padx=8, pady=10)

        # ── Top row: video | details | map ────────────────────────────────────
        # Details column is a fixed-width centre separator.
        # Video and map each take half of whatever remains, at any window size.
        self._vid_w = 420   # updated live via <Configure>
        self._map_w = 420   # updated live via <Configure>

        top_row = tk.Frame(main_area, bg=C["bg"]); top_row.pack(fill="both", expand=True)
        top_row.grid_columnconfigure(0, weight=1)   # video — equal half
        top_row.grid_columnconfigure(1, weight=0)   # details — fixed separator
        top_row.grid_columnconfigure(2, weight=1)   # map — equal half
        top_row.grid_rowconfigure(0, weight=1)

        # — Video frame ———————————————————————————————————————————————————————
        vid_col = tk.Frame(top_row, bg=C["bg"])
        vid_col.grid(row=0, column=0, sticky="nsew")
        vid_col.pack_propagate(False)   # children cannot push this column wider

        vh = tk.Frame(vid_col, bg=C["bg"]); vh.pack(fill="x", pady=(0, 4))
        tk.Label(vh, text="VIDEO PREVIEW",
                 font=("segoe ui", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

        vid_border = tk.Frame(vid_col, bg=C["accent"], padx=2, pady=2)
        vid_border.pack(fill="both", expand=True)
        vid_inner = tk.Frame(vid_border, bg="black")
        vid_inner.pack(fill="both", expand=True)
        self.frame_label = Label(vid_inner, bg="black")
        self.frame_label.pack(fill="both", expand=True)
        # track real pixel width as window resizes
        vid_inner.bind("<Configure>", lambda e: setattr(self, "_vid_w", max(64, e.width)))

        # — Details (coordinates log) ─────────────────────────────────────────
        det_col = tk.Frame(top_row, bg=C["bg"], width=310)
        det_col.grid(row=0, column=1, sticky="nsew", padx=8)
        det_col.grid_propagate(False)

        dh = tk.Frame(det_col, bg=C["bg"]); dh.pack(fill="x", pady=(0, 4))
        tk.Label(dh, text="REAL TIME  |  VIDEO POS  |  COORDS",
                 font=("segoe ui", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

        det_border = tk.Frame(det_col, bg=C["accent"], padx=1, pady=1)
        det_border.pack(fill="both", expand=True)
        det_inner = tk.Frame(det_border, bg=C["panel2"])
        det_inner.pack(fill="both", expand=True)
        self.details = scrolledtext.ScrolledText(
            det_inner, width=38, bg=C["panel2"], fg=C["text"],
            insertbackground=C["text"], font=("segoe ui", 9),
            state="disabled", relief="flat", borderwidth=0,
            wrap="none",
        )
        self.details.pack(fill="both", expand=True)

        # — Map ———————————————————————————————————————————————————————————————
        map_col = tk.Frame(top_row, bg=C["bg"])
        map_col.grid(row=0, column=2, sticky="nsew")
        map_col.pack_propagate(False)   # children cannot push this column narrower

        mh = tk.Frame(map_col, bg=C["bg"]); mh.pack(fill="x", pady=(0, 4))
        tk.Label(mh, text="LIVE MAP",
                 font=("segoe ui", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

        map_border = tk.Frame(map_col, bg=C["accent"], padx=2, pady=2)
        map_border.pack(fill="both", expand=True)
        map_inner = tk.Frame(map_border, bg=C["panel2"])
        map_inner.pack(fill="both", expand=True)
        self.map_label = Label(map_inner, bg=C["panel2"])
        self.map_label.pack(fill="both", expand=True)
        # track real pixel width as window resizes
        map_inner.bind("<Configure>", lambda e: setattr(self, "_map_w", max(64, e.width)))

        # ── Log panel ─────────────────────────────────────────────────────────
        log_row = tk.Frame(main_area, bg=C["bg"], height=170)
        log_row.pack(fill="x", pady=(8, 0))
        log_row.pack_propagate(False)

        lh = tk.Frame(log_row, bg=C["bg"]); lh.pack(fill="x", pady=(0, 4))
        tk.Label(lh, text="PROCESSING LOG",
                 font=("segoe ui", 8, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

        log_border = tk.Frame(log_row, bg=C["accent"], padx=1, pady=1)
        log_border.pack(fill="both", expand=True)
        log_inner = tk.Frame(log_border, bg=C["panel2"])
        log_inner.pack(fill="both", expand=True)
        self.log = scrolledtext.ScrolledText(
            log_inner, bg=C["panel2"], fg=C["text"],
            insertbackground=C["text"], font=("segoe ui", 9),
            state="disabled", relief="flat", borderwidth=0,
        )
        self.log.pack(fill="both", expand=True)

        # ── Status bar ────────────────────────────────────────────────────────
        sb = tk.Frame(self.root, bg=C["panel"], height=30)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")

        self.progress_label_var = StringVar(value="Ready.")
        tk.Label(sb, textvariable=self.progress_label_var,
                  font=("segoe ui", 8), bg=C["panel"], fg=C["muted"],
                  justify="left", anchor="w").pack(side="left", padx=10, pady=4)
        self.progress = ttk.Progressbar(sb, mode="determinate", length=380)
        self.progress.pack(side="left", padx=8, pady=4)

        self.outdir = ensure_output_folder()

    # ──────────────────────────────────────────────────────────────────────────
    # All methods below are unchanged from original
    # ──────────────────────────────────────────────────────────────────────────

    def request_stop(self):
        self.stop_requested = True
        self.append_log("Stop requested by user. Finalizing file...")

    def append_log(self, txt):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state='normal')
        self.log.insert('1.0', f"[{ts}] {txt}\n")
        self.log.configure(state='disabled')

    def append_detail(self, clock_time, video_pos, lat, lon):
        line = f"{clock_time} | {video_pos} | {lat:.5f}, {lon:.5f}\n"
        self.details.configure(state='normal')
        self.details.insert('1.0', line)
        self.details.configure(state='disabled')

    def update_progress_label(self, fi, total_files, filename, video_sec, duration_s):
        eta_str    = "Calculating..."
        finish_str = ""
        recent_data = [(v_s, s_ms/1000.0) for v_s, s_ms in self.frame_data_points if v_s >= video_sec - 60]
        if len(recent_data) > 1 and video_sec < duration_s:
            v_start, s_start = recent_data[0]
            v_end,   s_end   = recent_data[-1]
            v_diff,  s_diff  = v_end - v_start, s_end - s_start
            if s_diff > 0.1:
                rate = v_diff / s_diff
                if rate > 0:
                    eta_s      = (duration_s - video_sec) / rate
                    eta_str    = format_time_hms(eta_s)
                    fin_time   = datetime.now() + timedelta(seconds=eta_s)
                    finish_str = f"[Finish {fin_time.strftime('%H:%M:%S')}]"
        label_text = (f"File {fi}/{total_files}  ·  {filename}  ·  "
                      f"{format_time_hms(video_sec)} / {format_time_hms(duration_s)}  ·  "
                      f"ETA: {eta_str}  {finish_str}")
        self.progress_label_var.set(label_text)

    def select_and_start(self):
        files = filedialog.askopenfilenames(
            title="Select videos",
            filetypes=[("Video files", "*.mp4;*.avi;*.mov;*.mkv")])
        if not files: return
        self.stop_requested = False
        self.start_btn.config(state="disabled", bg=C["dim"], fg=C["muted"])
        self.stop_btn.config(state="normal",    bg=C["red"], fg="white")
        threading.Thread(target=self.worker, args=(list(files),), daemon=True).start()

    def _save_provisional(self, raw_points, basename, current_sec, prev_provisional_path):
        if not raw_points:
            return prev_provisional_path

        suffix    = format_time_compact(current_sec)
        prov_name = f"{os.path.splitext(basename)[0]}_provisional_{suffix}.gpx"
        prov_path = os.path.join(self.outdir, prov_name)

        write_gpx_latlon_time(raw_points, prov_path)

        if prev_provisional_path and os.path.isfile(prev_provisional_path):
            try:
                os.remove(prev_provisional_path)
                self.root.after(0, lambda old=os.path.basename(prev_provisional_path):
                    self.append_log(f"Deleted old provisional: {old}"))
            except Exception as e:
                self.root.after(0, lambda err=str(e):
                    self.append_log(f"Could not delete old provisional: {err}"))

        self.root.after(0, lambda p=prov_name: self.append_log(f"Provisional saved: {p}"))
        return prov_path

    def worker(self, files):
        total_files   = len(files)
        recal_limit   = parse_hms_to_seconds(self.recal_trigger_var.get()) or 60
        auto_stop_sec = parse_hms_to_seconds(self.autostop_var.get())

        try:    provisional_interval = int(self.provisional_interval_var.get())
        except: provisional_interval = 60

        for fi, path in enumerate(files, start=1):
            if self.stop_requested: break
            basename = os.path.basename(path)
            self.append_log(f"Processing: {basename}")
            self.frame_data_points = []

            start_dt = datetime.now()
            try:
                if self.use_fname_var.get() == "use":
                    m = re.search(r"(\d{4}\.\d{2}\.\d{2})", basename)
                    if m:
                        y, m_val, d = m.group(1).split(".")
                        start_dt = datetime.strptime(
                            f"{y}-{m_val}-{d} 00:00:00", "%Y-%m-%d %H:%M:%S")
                else:
                    start_dt = datetime.strptime(
                        self.dt_var.get().strip(), "%Y-%m-%d %H:%M:%S")
            except: pass

            cap          = cv2.VideoCapture(path)
            fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_s   = int(total_frames / fps)
            offset_s     = parse_hms_to_seconds(self.offset_var.get())

            raw_points             = []
            last_success_sec       = offset_s
            last_vid_sec_processed = offset_s
            last_provisional_path  = None
            last_provisional_sec   = offset_s

            self.root.after(0, lambda: self.progress.configure(maximum=duration_s, value=offset_s))

            for sec in range(offset_s, duration_s):
                if self.stop_requested: break

                if sec >= auto_stop_sec:
                    self.append_log(f"Auto-stop reached at {format_time_hms(sec)}")
                    self.stop_requested = True
                    break

                last_vid_sec_processed = sec
                found_in_second = False

                if (sec - last_success_sec) >= recal_limit:
                    self.append_log(f"Recalibrating (Deep Scan) at {format_time_hms(sec)}...")
                    for sub_f in range(int(3 * fps)):
                        if self.stop_requested: break
                        target_f = int(sec * fps + sub_f)
                        if target_f >= total_frames: break

                        cap.set(cv2.CAP_PROP_POS_FRAMES, target_f)
                        ret, frame = cap.read()
                        if not ret: continue

                        res = extract_ocr_coords_from_frame(frame)
                        if res:
                            lat, lon, txt = res
                            actual_sec    = sec + (sub_f / fps)
                            ts_gpx        = start_dt + timedelta(seconds=actual_sec)
                            raw_points.append((ts_gpx, lat, lon))

                            now_clock = datetime.now().strftime("%H:%M:%S")
                            self.root.after(0, lambda c=now_clock, v=format_time_hms(sec),
                                            la=lat, lo=lon: self.append_detail(c, v, la, lo))
                            self.root.after(0, lambda la=lat, lo=lon: self.update_map_point(la, lo))

                            last_success_sec = sec
                            found_in_second  = True
                            break

                    if not found_in_second:
                        last_success_sec = sec

                else:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps))
                    ret, frame = cap.read()
                    if ret:
                        pil_frame = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                        self.root.after(0, lambda im=pil_frame: self.show_frame(im))

                        res = extract_ocr_coords_from_frame(frame)
                        if res:
                            lat, lon, txt = res
                            ts_gpx        = start_dt + timedelta(seconds=sec)
                            raw_points.append((ts_gpx, lat, lon))

                            now_clock = datetime.now().strftime("%H:%M:%S")
                            self.root.after(0, lambda c=now_clock, v=format_time_hms(sec),
                                            la=lat, lo=lon: self.append_detail(c, v, la, lo))
                            self.root.after(0, lambda la=lat, lo=lon: self.update_map_point(la, lo))
                            last_success_sec = sec

                if (sec - last_provisional_sec) >= provisional_interval and raw_points:
                    last_provisional_path = self._save_provisional(
                        raw_points, basename, sec, last_provisional_path)
                    last_provisional_sec = sec

                self.frame_data_points.append((sec, time.time() * 1000))
                self.root.after(0, lambda s=sec: self.progress.configure(value=s))
                self.root.after(0, lambda s=sec:
                    self.update_progress_label(fi, total_files, basename, s, duration_s))

            cap.release()

            if raw_points:
                suffix   = format_time_compact(last_vid_sec_processed)
                out_name = f"{os.path.splitext(basename)[0]}_extracted_{suffix}.gpx"
                out_path = os.path.join(self.outdir, out_name)
                write_gpx_latlon_time(raw_points, out_path)
                self.root.after(0, lambda p=out_name: self.append_log(f"Saved final: {p}"))

                if last_provisional_path and os.path.isfile(last_provisional_path):
                    try:
                        os.remove(last_provisional_path)
                        self.root.after(0, lambda old=os.path.basename(last_provisional_path):
                            self.append_log(f"Cleaned up last provisional: {old}"))
                    except Exception as e:
                        self.root.after(0, lambda err=str(e):
                            self.append_log(f"Could not clean up last provisional: {err}"))

        self.root.after(0, lambda: [
            self.start_btn.config(state="normal", bg=C["green"], fg="white"),
            self.stop_btn.config(state="disabled", bg=C["dim"],  fg=C["muted"]),
            self.progress_label_var.set("Ready."),
        ])

    def show_frame(self, pil_image):
        w = self._vid_w
        h = max(1, int(w * pil_image.height / pil_image.width))
        img = pil_image.resize((w, h), Image.LANCZOS)
        self.tk_frame = ImageTk.PhotoImage(img)
        self.frame_label.config(image=self.tk_frame)

    def update_map_point(self, lat, lon):
        w = self._map_w
        img = build_map_image_single(lat, lon, size_px=(w, w))
        self.tk_map = ImageTk.PhotoImage(img)
        self.map_label.config(image=self.tk_map)


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = Tk()
    app  = App(root)
    root.mainloop()
