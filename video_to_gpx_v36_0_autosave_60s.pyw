import os
import re
import time
import threading
import cv2
import numpy as np
import pytesseract
from datetime import datetime, timedelta
from tkinter import Tk, Frame, Label, Button, Entry, StringVar, ttk, scrolledtext, filedialog
from PIL import Image, ImageTk
from staticmap import StaticMap, CircleMarker

# ---------------- CONFIG ----------------
VERSION = "v36.0_OCR_AutoStop_DynamicNaming_ProvisionalSave"
ROI_DEFAULT = (0.32, 0.56, 0.90, 1.00)
TESS_CONFIG_BASE = r'-c tessedit_char_whitelist=0123456789NnSsEeWw°.,-'
TESS_PSMS = [7, 6]

FLOAT5_RE = re.compile(r'(-?\d{1,3}\.\d{5})')
FLOAT_LOOSE_RE = re.compile(r'(-?\d{1,3}\.\d{4,5})')
FLOAT_GENERIC_RE = re.compile(r'(-?\d+\.\d+)')

# ---------------- HELPERS ----------------
def ensure_output_folder():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    outdir = os.path.join(desktop, "OCR")
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
    """Converts seconds into HHMMSS for filenames."""
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}{minutes:02d}{seconds:02d}"

def write_gpx_latlon_time(points, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="DashcamToGPX" xmlns="http://www.topografix.com/GPX/1/1">\n')
        f.write('  <trk><name>Extracted track</name><trkseg>\n')
        for t, lat, lon in points:
            timestr = t.isoformat() + "Z" if isinstance(t, datetime) else str(t)
            f.write(f'  <trkpt lat="{float(lat):.6f}" lon="{float(lon):.6f}">\n')
            f.write(f'  <ele>0.0</ele><time>{timestr}</time>\n  </trkpt>\n')
        f.write('  </trkseg></trk>\n</gpx>\n')

def build_map_image_single(lat, lon, size_px=(540,480)):
    try:
        sm = StaticMap(size_px[0], size_px[1], url_template='https://a.tile.openstreetmap.org/{z}/{x}/{y}.png')
        sm.add_marker(CircleMarker((lon, lat), 'red', 14))
        return sm.render(zoom=16)
    except:
        return Image.new("RGB", size_px, (80,80,80))

# --- OCR LOGIC ---
def preprocess_attempts_for_ocr(crop_bgr):
    results = []
    try:
        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        scale = 4 if h < 60 else 3
        gray_big = cv2.resize(gray, (w*scale, h*scale), interpolation=cv2.INTER_CUBIC)
        results.append(gray_big)
        clahe = cv2.createCLAHE(clipLimit=3, tileGridSize=(8,8))
        results.append(clahe.apply(gray_big))
        eq = cv2.equalizeHist(gray_big)
        results.append(eq)
        blur = cv2.medianBlur(eq, 3)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        results.append(otsu)
    except: pass
    return [Image.fromarray(cv2.cvtColor(res, cv2.COLOR_GRAY2RGB)) for res in results]

def extract_coords_from_text(text):
    if not text: return None
    filtered_txt = re.sub(r'[^\x20-\x7E\n\r\t°\.,-]', '', text)
    txt = filtered_txt.replace(',', '.').replace('°', '').replace(' ', '')
    floats = FLOAT5_RE.findall(txt) or FLOAT_LOOSE_RE.findall(txt) or FLOAT_GENERIC_RE.findall(txt)
    if len(floats) < 2: return None
    try: return float(floats[0]), float(floats[1]), filtered_txt
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

# ---------------- GUI ----------------

class App:
    def __init__(self, root):
        self.root = root
        root.title(f"DashcamToGPX {VERSION}")
        root.geometry("1200x880")

        self.stop_requested = False
        self.frame_data_points = []

        # UI LAYOUT
        top = Frame(root); top.pack(side='top', fill='both', expand=True)
        bottom = Frame(root, height=320); bottom.pack(side='bottom', fill='x')

        # Left Preview
        left = Frame(top, bg='black', width=640, height=480); left.pack(side='left', fill='both', expand=True)
        self.frame_label = Label(left); self.frame_label.pack(fill='both', expand=True)

        # Mid Details
        mid = Frame(top, width=320); mid.pack(side='left', fill='y')
        Label(mid, text="Real Time | Video Pos | Coordinates", font=("Arial", 9, "bold")).pack(anchor='nw', padx=6)
        self.details = scrolledtext.ScrolledText(mid, width=42, height=30, state='disabled', font=("Courier", 9))
        self.details.pack(fill='both', expand=True, padx=6, pady=6)

        # Right Map
        right = Frame(top, bg='grey', width=540, height=480); right.pack(side='right', fill='both', expand=True)
        self.map_label = Label(right); self.map_label.pack(fill='both', expand=True)

        # Controls
        ctrl = Frame(bottom); ctrl.pack(side='left', fill='y', padx=8, pady=6)
        self.start_btn = Button(ctrl, text="Select Video(s) & Start", command=self.select_and_start, bg="#e8f5e9", font=("Arial", 9, "bold"))
        self.start_btn.pack(fill='x', pady=2)

        self.stop_btn = Button(ctrl, text="STOP & SAVE NOW", command=self.request_stop, bg="#ffebee", fg="red", state="disabled", font=("Arial", 9, "bold"))
        self.stop_btn.pack(fill='x', pady=2)

        Label(ctrl, text="Video Offset (Start):", fg="blue").pack(anchor='w', pady=(5,0))
        self.offset_var = StringVar(value="00:00:00")
        Entry(ctrl, textvariable=self.offset_var, width=22).pack(pady=2)

        Label(ctrl, text="Auto-stop at (HH:MM:SS):", fg="darkred").pack(anchor='w', pady=(5,0))
        self.autostop_var = StringVar(value="23:59:59")
        Entry(ctrl, textvariable=self.autostop_var, width=22).pack(pady=2)

        Label(ctrl, text="Recalibrate after (sec):", fg="darkgreen").pack(anchor='w', pady=(5,0))
        self.recal_trigger_var = StringVar(value="60")
        Entry(ctrl, textvariable=self.recal_trigger_var, width=22).pack(pady=2)

        # --- NEW: Provisional save interval ---
        Label(ctrl, text="Provisional save every (vid sec):", fg="purple").pack(anchor='w', pady=(5,0))
        self.provisional_interval_var = StringVar(value="60")
        Entry(ctrl, textvariable=self.provisional_interval_var, width=22).pack(pady=2)
        # --- END NEW ---

        Label(ctrl, text="Manual Start Date:").pack(anchor='w', pady=(5,0))
        self.dt_var = StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        Entry(ctrl, textvariable=self.dt_var, width=22).pack(pady=2)

        self.use_fname_var = StringVar(value="use")
        ttk.Radiobutton(ctrl, text="Date from Filename", variable=self.use_fname_var, value="use").pack(anchor='w')
        ttk.Radiobutton(ctrl, text="Manual Date", variable=self.use_fname_var, value="manual").pack(anchor='w')

        # Progress / ETA Section
        self.progress_label_var = StringVar(value="Ready.")
        Label(bottom, textvariable=self.progress_label_var, justify='left', anchor='w').pack(side='top', fill='x', padx=10)
        self.progress = ttk.Progressbar(bottom, mode='determinate', length=400); self.progress.pack(fill='x', padx=10, pady=2)

        self.log = scrolledtext.ScrolledText(bottom, height=8, state='disabled'); self.log.pack(fill='both', expand=True, padx=10, pady=5)

        self.outdir = ensure_output_folder()

    def request_stop(self):
        self.stop_requested = True
        self.append_log("Stop requested by user. Finalizing file...")

    def append_log(self, txt):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state='normal'); self.log.insert('1.0', f"[{ts}] {txt}\n"); self.log.configure(state='disabled')

    def append_detail(self, clock_time, video_pos, lat, lon):
        line = f"{clock_time} | {video_pos} | {lat:.5f}, {lon:.5f}\n"
        self.details.configure(state='normal'); self.details.insert('1.0', line); self.details.configure(state='disabled')

    def update_progress_label(self, fi, total_files, filename, video_sec, duration_s):
        eta_str = "Calculating..."
        finish_str = ""
        recent_data = [(v_s, s_ms/1000.0) for v_s, s_ms in self.frame_data_points if v_s >= video_sec - 60]
        if len(recent_data) > 1 and video_sec < duration_s:
            v_start, s_start = recent_data[0]
            v_end, s_end = recent_data[-1]
            v_diff, s_diff = v_end - v_start, s_end - s_start
            if s_diff > 0.1:
                rate = v_diff / s_diff
                if rate > 0:
                    eta_s = (duration_s - video_sec) / rate
                    eta_str = format_time_hms(eta_s)
                    fin_time = datetime.now() + timedelta(seconds=eta_s)
                    finish_str = f"[Finish at {fin_time.strftime('%H:%M:%S')}]"

        label_text = f"File {fi}/{total_files} | {filename}\nPos: {format_time_hms(video_sec)} / {format_time_hms(duration_s)} | ETA: {eta_str} {finish_str}"
        self.progress_label_var.set(label_text)

    def select_and_start(self):
        files = filedialog.askopenfilenames(title="Select videos", filetypes=[("Video files","*.mp4;*.avi;*.mov;*.mkv")])
        if not files: return
        self.stop_requested = False
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        threading.Thread(target=self.worker, args=(list(files),), daemon=True).start()

    def _save_provisional(self, raw_points, basename, current_sec, prev_provisional_path):
        """
        Saves a provisional GPX for the points collected so far.
        Deletes the previous provisional file if it exists.
        Returns the path of the newly saved provisional file.
        """
        if not raw_points:
            return prev_provisional_path  # nothing to save yet

        suffix = format_time_compact(current_sec)
        prov_name = f"{os.path.splitext(basename)[0]}_provisional_{suffix}.gpx"
        prov_path = os.path.join(self.outdir, prov_name)

        write_gpx_latlon_time(raw_points, prov_path)

        # Delete the previous provisional file
        if prev_provisional_path and os.path.isfile(prev_provisional_path):
            try:
                os.remove(prev_provisional_path)
                self.root.after(0, lambda old=os.path.basename(prev_provisional_path):
                    self.append_log(f"Deleted old provisional: {old}"))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.append_log(f"Could not delete old provisional: {err}"))

        self.root.after(0, lambda p=prov_name: self.append_log(f"Provisional saved: {p}"))
        return prov_path

    def worker(self, files):
        total_files = len(files)
        recal_limit = parse_hms_to_seconds(self.recal_trigger_var.get()) or 60
        auto_stop_sec = parse_hms_to_seconds(self.autostop_var.get())

        try:
            provisional_interval = int(self.provisional_interval_var.get())
        except ValueError:
            provisional_interval = 60

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
                        start_dt = datetime.strptime(f"{y}-{m_val}-{d} 00:00:00", "%Y-%m-%d %H:%M:%S")
                else:
                    start_dt = datetime.strptime(self.dt_var.get().strip(), "%Y-%m-%d %H:%M:%S")
            except: pass

            cap = cv2.VideoCapture(path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_s = int(total_frames / fps)
            offset_s = parse_hms_to_seconds(self.offset_var.get())

            raw_points = []
            last_success_sec = offset_s
            last_vid_sec_processed = offset_s

            # --- Provisional save tracking ---
            last_provisional_path = None
            last_provisional_sec = offset_s  # last video-second at which we saved provisionally
            # ---------------------------------

            self.root.after(0, lambda: self.progress.configure(maximum=duration_s, value=offset_s))

            for sec in range(offset_s, duration_s):
                if self.stop_requested: break

                # CHECK AUTO-STOP
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
                            actual_sec = sec + (sub_f / fps)
                            ts_gpx = start_dt + timedelta(seconds=actual_sec)
                            raw_points.append((ts_gpx, lat, lon))

                            now_clock = datetime.now().strftime("%H:%M:%S")
                            self.root.after(0, lambda c=now_clock, v=format_time_hms(sec), la=lat, lo=lon: self.append_detail(c, v, la, lo))
                            self.root.after(0, lambda la=lat, lo=lon: self.update_map_point(la, lo))

                            last_success_sec = sec
                            found_in_second = True
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
                            ts_gpx = start_dt + timedelta(seconds=sec)
                            raw_points.append((ts_gpx, lat, lon))

                            now_clock = datetime.now().strftime("%H:%M:%S")
                            self.root.after(0, lambda c=now_clock, v=format_time_hms(sec), la=lat, lo=lon: self.append_detail(c, v, la, lo))
                            self.root.after(0, lambda la=lat, lo=lon: self.update_map_point(la, lo))
                            last_success_sec = sec

                # --- PROVISIONAL SAVE CHECK ---
                # Trigger when we've advanced at least provisional_interval video-seconds
                # since the last provisional save, and we have points to save.
                if (sec - last_provisional_sec) >= provisional_interval and raw_points:
                    last_provisional_path = self._save_provisional(
                        raw_points, basename, sec, last_provisional_path
                    )
                    last_provisional_sec = sec
                # --- END PROVISIONAL SAVE CHECK ---

                self.frame_data_points.append((sec, time.time() * 1000))
                self.root.after(0, lambda s=sec: self.progress.configure(value=s))
                self.root.after(0, lambda s=sec: self.update_progress_label(fi, total_files, basename, s, duration_s))

            cap.release()

            if raw_points:
                # FINAL FILE — dynamic name based on last processed second
                suffix = format_time_compact(last_vid_sec_processed)
                out_name = f"{os.path.splitext(basename)[0]}_extracted_{suffix}.gpx"
                out_path = os.path.join(self.outdir, out_name)
                write_gpx_latlon_time(raw_points, out_path)
                self.root.after(0, lambda p=out_name: self.append_log(f"Saved final: {p}"))

                # Clean up the last provisional file now that the final is saved
                if last_provisional_path and os.path.isfile(last_provisional_path):
                    try:
                        os.remove(last_provisional_path)
                        self.root.after(0, lambda old=os.path.basename(last_provisional_path):
                            self.append_log(f"Cleaned up last provisional: {old}"))
                    except Exception as e:
                        self.root.after(0, lambda err=str(e): self.append_log(f"Could not clean up last provisional: {err}"))

        self.root.after(0, lambda: [
            self.start_btn.config(state="normal"),
            self.stop_btn.config(state="disabled"),
            self.progress_label_var.set("Ready.")
        ])

    def show_frame(self, pil_image):
        img = pil_image.resize((640, 360), Image.LANCZOS)
        self.tk_frame = ImageTk.PhotoImage(img)
        self.frame_label.config(image=self.tk_frame)

    def update_map_point(self, lat, lon):
        img = build_map_image_single(lat, lon, size_px=(540,480))
        self.tk_map = ImageTk.PhotoImage(img)
        self.map_label.config(image=self.tk_map)

if __name__ == "__main__":
    root = Tk()
    app = App(root)
    root.mainloop()
