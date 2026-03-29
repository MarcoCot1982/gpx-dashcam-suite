#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Comment Video Generator  v1.1
Author : Marco Cot
Contact: marcocot1982@gmail.com
v1.1: live map showing full track + current-point marker
"""

import os, sys, time, threading, queue, subprocess, tempfile, shutil
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import gpxpy, gpxpy.gpx
import tkintermapview
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from moviepy.editor import VideoClip
from moviepy.video.io.bindings import mplfig_to_npimage
from PIL import Image, ImageTk

VERSION="v1.1"; AUTHOR="Marco Cot"; CONTACT="marcocot1982@gmail.com"; SPLASH_SECONDS=4

# Suppress the ffmpeg console window on Windows; no-op on Linux/Mac
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

RESOLUTIONS={"854 × 480  (480p)":(854,480),"1280 × 720  (720p)":(1280,720),"1920 × 1080 (1080p)":(1920,1080)}
FPS_OPTIONS=[24,30,60]

C={"bg":"#141414","panel":"#1e1e1e","panel2":"#252525","border":"#333333",
   "accent":"#f5a623","accent2":"#e8941a","green":"#4caf50","red":"#e53935",
   "orange":"#fb8c00","blue":"#2196F3","text":"#e8e8e8","muted":"#888888","dim":"#555555"}

# ── Country code → PNG ─────────────────────────────────────────────────
ALPHA3_TO_ALPHA2={
    'ITA':'IT','FRA':'FR','MCO':'MC','ESP':'ES','PRT':'PT','DEU':'DE',
    'CHE':'CH','AUT':'AT','BEL':'BE','NLD':'NL','GBR':'GB','GRC':'GR',
    'HRV':'HR','SVN':'SI','AND':'AD','LUX':'LU','SMR':'SM','MLT':'MT',
    'USA':'US','CAN':'CA','AUS':'AU','JPN':'JP','BRA':'BR','ARG':'AR',
    'POL':'PL','CZE':'CZ','SVK':'SK','HUN':'HU','ROU':'RO','BGR':'BG',
    'SRB':'RS','ALB':'AL','MKD':'MK','MNE':'ME','BIH':'BA','TUR':'TR',
    'MAR':'MA','TUN':'TN','DZA':'DZ','EGY':'EG','ISR':'IL','JOR':'JO',
}

def alpha3_to_flag(code3):
    a2=ALPHA3_TO_ALPHA2.get(code3.upper().strip(),'')
    if not a2: return code3
    return ''.join(chr(0x1F1E6+ord(c)-ord('A')) for c in a2.upper())

FLAG_FOLDER = os.path.join(os.path.dirname(__file__), "flags")
flag_cache = {}       # tkinter PhotoImage cache (for UI preview)
flag_arr_cache = {}   # numpy RGBA array cache (for video frames)

def get_flag_image(alpha3):
    """Return Tk image for a country code, or None if not found."""
    a2 = ALPHA3_TO_ALPHA2.get(alpha3.upper().strip(), "")
    if not a2:
        return None

    key = a2.lower()
    if key in flag_cache:
        return flag_cache[key]

    path = os.path.join(FLAG_FOLDER, f"{key}.png")
    if not os.path.exists(path):
        return None

    try:
        img = Image.open(path).resize((24, 16), Image.LANCZOS)
        tk_img = ImageTk.PhotoImage(img)
        flag_cache[key] = tk_img
        return tk_img
    except:
        return None

def get_flag_array(alpha3):
    """Return numpy RGBA array for a country flag (for matplotlib video frames), or None."""
    key = alpha3.upper().strip()
    if key in flag_arr_cache:
        return flag_arr_cache[key]

    a2 = ALPHA3_TO_ALPHA2.get(key, '')
    if not a2:
        flag_arr_cache[key] = None
        return None

    path = os.path.join(FLAG_FOLDER, f"{a2.lower()}.png")
    if not os.path.exists(path):
        flag_arr_cache[key] = None
        return None

    try:
        arr = np.array(Image.open(path).convert("RGBA"))
        flag_arr_cache[key] = arr
        return arr
    except:
        flag_arr_cache[key] = None
        return None

def apply_flag_to_comment(cmt):
    """Replace trailing 3-letter country code with flag emoji if it looks like one."""
    if ' | ' not in cmt: return cmt
    parts=cmt.split(' | ')
    last=parts[-1].strip()
    if len(last)==3 and last.isalpha():
        parts[-1]=alpha3_to_flag(last)
    return ' | '.join(parts)

def extract_comments(f):
    with open(f,"r",encoding="utf-8") as fh: g=gpxpy.parse(fh)
    return [(p.time,p.comment) for t in g.tracks for s in t.segments for p in s.points if p.comment and p.time]

def extract_all_coords(f):
    with open(f,"r",encoding="utf-8") as fh: g=gpxpy.parse(fh)
    return [(p.latitude,p.longitude) for t in g.tracks for s in t.segments for p in s.points]

def calculate_durations(comments):
    d=[]
    for i,_ in enumerate(comments):
        d.append(0 if i==0 else max((comments[i][0]-comments[i-1][0]).total_seconds(),0))
    return d

AUTOSAVE_EVERY = 100   # points per chunk / partial save

def _ffmpeg_concat(chunk_files, output_path):
    """Concatenate video files using ffmpeg stream-copy (no re-encode). Fast."""
    fd, list_path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w") as f:
            for fp in chunk_files:
                # ffmpeg concat list needs forward slashes even on Windows
                f.write(f"file '{fp.replace(chr(92), '/')}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_path, "-c", "copy", output_path],
            check=True, capture_output=True,
            creationflags=_NO_WINDOW
        )
    finally:
        try: os.unlink(list_path)
        except: pass

def _write_chunk_transparent(make_frame_rgba, duration, fps, w, h, output_path):
    """Write RGBA frames to a WebM VP9 file via ffmpeg stdin pipe.
    This bypasses moviepy entirely since moviepy only supports RGB frames.
    VP9 + yuva420p is the standard cross-platform alpha video format."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{w}x{h}",
        "-pix_fmt", "rgba",
        "-r", str(fps),
        "-i", "pipe:",
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p",
        "-auto-alt-ref", "0",
        "-b:v", "0", "-crf", "10",
        output_path
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=_NO_WINDOW)
    try:
        n_frames = max(1, int(duration * fps))
        for fi in range(n_frames):
            t = fi / fps
            frame = make_frame_rgba(t)   # H x W x 4 uint8
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        proc.wait()
    except Exception:
        try: proc.kill()
        except: pass
        raise


def _render_chunk(comments, cum_times, chunk_start, chunk_end, n_pts,
                  settings, pause_event, stop_event,
                  frames_before, total_frames_all, wall_start,
                  progress_cb, use_flags, transparent, stopped, last_pt):
    """Render points [chunk_start, chunk_end). Returns (clip_or_None, duration).
    When transparent=True, clip is None and make_frame_rgba is used instead via
    _write_chunk_transparent — caller must use that path."""
    w,h    = settings["resolution"]; fig_w,fig_h = w/100, h/100
    fps    = settings["fps"];        bg = settings["bg_color"]
    tc     = settings["text_color"]; cs = settings["cmt_fontsize"]
    ts_sz  = settings["time_fontsize"]; align = settings["text_align"]
    xp_base = {"right":0.97,"center":0.5,"left":0.03}[align]

    

    # reserve space for flag (only if used and right-aligned)
    flag_space = 0.06 if (use_flags and align == "right") else 0
    xp = xp_base - flag_space

    ha = align

    t_from = cum_times[chunk_start]
    t_to   = cum_times[chunk_end] if chunk_end < n_pts else cum_times[-1]
    chunk_dur = t_to - t_from
    if chunk_dur <= 0:
        return None, chunk_dur

    def make_frame(t):
        # pause / stop
        while not pause_event.is_set():
            if stop_event.is_set():
                stopped[0] = True
                f2,a2 = plt.subplots(figsize=(fig_w,fig_h))
                f2.patch.set_facecolor("black"); a2.set_axis_off()
                img = mplfig_to_npimage(f2); plt.close(f2); return img
            time.sleep(0.05)
        if stop_event.is_set(): stopped[0] = True

        # which point are we on? (stay on point i until i+1 is reached)
        actual_t = t + t_from
        ci = chunk_start
        for i in range(chunk_start, min(chunk_end, n_pts)):
            if cum_times[i] <= actual_t: ci = i
            else: break
        last_pt[0] = ci

        cc     = comments[ci][1]
        ct_str = comments[ci][0].strftime("%Y-%m-%d  %H:%M:%S")

        # ── flag handling for video ───────────────────────────────────────
        # Use PNG image overlay — NOT emoji strings (emoji don't render on Windows).
        # Strip the country code from the text; draw the flag as an image instead.
        flag_np  = None
        cc_text  = cc
        if use_flags and ' | ' in cc:
            parts = cc.split(' | ')
            last  = parts[-1].strip()
            if len(last) == 3 and last.isalpha():
                flag_np = get_flag_array(last)
                if flag_np is not None:
                    cc_text = ' | '.join(parts[:-1])   # drop the country code from text

        cf_total = frames_before + min(int(t*fps), int(chunk_dur*fps))
        el    = time.time()-wall_start
        ratio = cf_total/total_frames_all if total_frames_all>0 else 0
        eta   = max(0,(el/ratio if ratio>0 else 0)-el)
        eta_s = time.strftime("%H:%M:%S", time.gmtime(eta))
        progress_cb(cf_total, total_frames_all, eta_s, ci, n_pts, cc, ct_str, use_flags)

        fig,ax = plt.subplots(figsize=(fig_w,fig_h))
        if transparent:
            fig.patch.set_facecolor("none"); ax.set_facecolor("none")
        else:
            fig.patch.set_facecolor(bg); ax.set_facecolor(bg)
        fig.subplots_adjust(left=0,right=1,top=1,bottom=0); ax.set_axis_off()
        ax.axhline(y=0.22,color=tc,linewidth=0.4,alpha=0.25)
        ax.text(xp, 0.18, cc_text, color=tc, fontsize=cs, ha=ha, va="top",
                transform=ax.transAxes, fontfamily="monospace")
        ax.text(xp, 0.05, ct_str, color=tc, fontsize=ts_sz, ha=ha, va="top",
                transform=ax.transAxes, alpha=0.65)

        # overlay flag PNG if available
        # overlay flag PNG if available
        # overlay flag PNG if available
        if flag_np is not None:
            # half previous size
            target_h_px = h * 0.03
            zoom = target_h_px / flag_np.shape[0]
            imagebox = OffsetImage(flag_np, zoom=zoom)

            if align == "right":
                x_flag = xp_base - 0.005   # sits in reserved space
                box_align = (1, 0.5)   
            elif align == "left":
                x_flag = xp + 0.01
                box_align = (0, 0.5)
            else:  # center
                x_flag = xp + 0.01
                box_align = (0, 0.5)

            ab = AnnotationBbox(
                imagebox,
                (x_flag, 0.165),
                frameon=False,
                xycoords='axes fraction',
                box_alignment=box_align
            )
            ax.add_artist(ab)

        fig.canvas.draw()
        if transparent:
            # RGBA extraction: preserves alpha for VP9 WebM output
            w_px = int(fig.get_figwidth() * fig.dpi)
            h_px = int(fig.get_figheight() * fig.dpi)
            img = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8).reshape(h_px, w_px, 4).copy()
        else:
            img = mplfig_to_npimage(fig)
        plt.close(fig)
        return img

    if transparent:
        # Return None clip; caller uses make_frame directly via _write_chunk_transparent
        return None, chunk_dur, make_frame
    clip = VideoClip(make_frame, duration=chunk_dur).set_fps(fps)
    return clip, chunk_dur, None

def generate_video(comments, durations, output_path, settings,
                   pause_event, stop_event, progress_cb, log_cb, start_point=0):
    cum_times = [0.0]
    for i in range(1, len(comments)):
        cum_times.append(cum_times[-1] + max(durations[i], 0))

    n_pts        = len(comments)
    t_offset     = cum_times[start_point] if start_point < n_pts else 0.0
    eff_duration = cum_times[-1] - t_offset
    if eff_duration <= 0:
        log_cb("⚠  No duration — skipped."); return False, start_point

    fps         = settings["fps"]
    use_flags   = settings.get("use_flags", False)
    transparent = settings.get("transparent", False)
    w, h        = settings["resolution"]

    # Transparent output uses WebM/VP9 (supports alpha); opaque uses mp4/H.264
    ext     = ".webm" if transparent else ".mp4"
    chunk_codec = "webm"   # used only for stray-file cleanup pattern

    total_frames_all = int(eff_duration * fps)
    wall_start       = time.time()
    stopped          = [False]
    last_pt          = [start_point]

    out_dir = os.path.dirname(output_path) or "."
    stem    = os.path.splitext(os.path.basename(output_path))[0]
    pid     = os.getpid()

    current_partial = [None]
    chunk_idx       = [0]
    frames_before   = 0

    def _del(*paths):
        for p in paths:
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass

    mode_str = "transparent WebM" if transparent else "opaque MP4"
    log_cb(f"🎬  Rendering {n_pts - start_point} points in chunks of {AUTOSAVE_EVERY} [{mode_str}]")

    pt = start_point
    try:
        while pt < n_pts:
            if stop_event.is_set(): stopped[0] = True; break

            chunk_start = pt
            chunk_end   = min(pt + AUTOSAVE_EVERY, n_pts)
            chunk_file  = os.path.join(out_dir, f"_chunk_{stem}_{pid}_{chunk_idx[0]:04d}{ext}")
            chunk_idx[0] += 1

            clip, chunk_dur, make_frame_rgba = _render_chunk(
                comments, cum_times, chunk_start, chunk_end, n_pts,
                settings, pause_event, stop_event,
                frames_before, total_frames_all,
                wall_start, progress_cb, use_flags, transparent, stopped, last_pt
            )

            # chunk_dur==0 means this chunk had no timeline span — skip
            if chunk_dur <= 0:
                pt = chunk_end; continue

            # stopped mid-chunk before any frame was rendered
            if stopped[0] and clip is None and make_frame_rgba is None:
                break

            try:
                if transparent:
                    # Write RGBA frames directly to ffmpeg → VP9 WebM with alpha
                    _write_chunk_transparent(make_frame_rgba, chunk_dur, fps, w, h, chunk_file)
                else:
                    clip.write_videofile(chunk_file, codec="libx264", fps=fps,
                                         verbose=False, logger=None)

                frames_before += int(chunk_dur * fps)

                n_done       = min(chunk_end, n_pts)
                partial_name = f"{stem}_{n_done:04d}{ext}"
                partial_path = os.path.join(out_dir, partial_name)
                prev_partial = current_partial[0]

                if prev_partial and os.path.exists(prev_partial):
                    _ffmpeg_concat([prev_partial, chunk_file], partial_path)
                    _del(prev_partial, chunk_file)
                else:
                    shutil.move(chunk_file, partial_path)

                current_partial[0] = partial_path
                log_cb(f"💾  Partial → {partial_name}")

            except Exception as e:
                _del(chunk_file)
                log_cb(f"⚠  Chunk {chunk_idx[0]-1} failed: {e}", "err")

            if stopped[0] or stop_event.is_set():
                stopped[0] = True; break
            pt = chunk_end

    finally:
        # Remove any stray chunk temps for this render
        for f in os.listdir(out_dir):
            if f.startswith(f"_chunk_{stem}_{pid}_"):
                _del(os.path.join(out_dir, f))

    # ── finalise ──────────────────────────────────────────────────────────────
    ok = not stopped[0]
    if ok and current_partial[0] and os.path.exists(current_partial[0]):
        try:
            if os.path.exists(output_path): os.remove(output_path)
            os.rename(current_partial[0], output_path)
            current_partial[0] = None
        except Exception as e:
            log_cb(f"⚠  Could not rename to final: {e}", "err")

    if not ok and current_partial[0]:
        log_cb(f"⏹  Partial kept → {os.path.basename(current_partial[0])}")

    return ok, last_pt[0]

root=tk.Tk(); root.title(f"GPX Comment Video Generator  {VERSION}"); root.configure(bg=C["bg"])
try: root.state("zoomed")
except: root.geometry("1440x860")
root.resizable(True,True)

sty=ttk.Style(root); sty.theme_use("clam")
sty.configure(".",background=C["bg"],foreground=C["text"])
sty.configure("TLabel",background=C["bg"],foreground=C["text"],font=("Consolas",9))
sty.configure("TFrame",background=C["bg"])
sty.configure("TProgressbar",troughcolor=C["border"],background=C["accent"],bordercolor=C["border"],lightcolor=C["accent"],darkcolor=C["accent2"])
sty.configure("TRadiobutton",background=C["bg"],foreground=C["text"],font=("Consolas",9))
sty.configure("TCombobox",fieldbackground=C["panel2"],background=C["panel2"],foreground=C["text"],selectbackground=C["accent"],selectforeground="black")
sty.map("TCombobox",fieldbackground=[("readonly",C["panel2"])],foreground=[("readonly",C["text"])])
sty.configure("TSpinbox",fieldbackground=C["panel2"],background=C["panel2"],foreground=C["text"])

def mk_btn(p,text,bg,cmd,width=None,font=("Consolas",9,"bold")):
    kw=dict(text=text,bg=bg,fg="white" if bg!=C["dim"] else C["muted"],activebackground=bg,
            activeforeground="white",relief="flat",cursor="hand2",command=cmd,font=font,pady=5,padx=10)
    if width: kw["width"]=width
    return tk.Button(p,**kw)

def sec_hdr(parent,text,bg=None):
    bg=bg or C["panel"]; f=tk.Frame(parent,bg=bg); f.pack(fill="x",padx=12,pady=(14,4))
    tk.Label(f,text=text,font=("Consolas",8,"bold"),bg=bg,fg=C["accent"]).pack(side="left")
    tk.Frame(parent,bg=C["border"],height=1).pack(fill="x",padx=12)

file_list=[]; file_status={}
processing_state={"running":False,"thread":None}
pause_event=threading.Event(); pause_event.set()
stop_event=threading.Event(); ui_queue=queue.Queue(); pause_btn_ref=[None]
map_path_obj=[None]; map_marker_obj=[None]; map_all_coords=[]; _last_pt=[- 1]
current_zoom=[12]

res_var=tk.StringVar(value="1280 × 720  (720p)"); fps_var=tk.IntVar(value=24)
bg_color_var=tk.StringVar(value="#000000"); txt_color_var=tk.StringVar(value="#ffffff")
cmt_size_var=tk.IntVar(value=20); ts_size_var=tk.IntVar(value=13)
align_var=tk.StringVar(value="right"); dest_var=tk.IntVar(value=2); custom_dest=tk.StringVar(value="")
use_flags_var=tk.BooleanVar(value=True)
transparent_var=tk.BooleanVar(value=False)
start_point_var=tk.StringVar(value="")

def show_splash():
    sp=tk.Toplevel(root); sp.overrideredirect(True); sp.configure(bg=C["bg"])
    sw,sh=sp.winfo_screenwidth(),sp.winfo_screenheight(); w,h=660,320
    sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    tk.Frame(sp,bg=C["accent"],height=3).pack(fill="x")
    body=tk.Frame(sp,bg=C["bg"]); body.pack(expand=True,fill="both",padx=40)
    tk.Label(body,text="GPX COMMENT VIDEO GENERATOR",font=("Consolas",18,"bold"),bg=C["bg"],fg=C["accent"]).pack(pady=(26,4))
    tk.Label(body,text=f"{VERSION}  ·  by {AUTHOR}  ·  {datetime.now().year}",font=("Consolas",9),bg=C["bg"],fg=C["muted"]).pack()
    tk.Label(body,text="reads geocoded GPX  →  renders comment-overlay video",font=("Consolas",9,"italic"),bg=C["bg"],fg=C["dim"]).pack(pady=(4,16))
    pbv=tk.DoubleVar(); pb=ttk.Progressbar(body,variable=pbv,maximum=100,length=580); pb.pack()
    pct=tk.Label(body,text="Loading…",font=("Consolas",8),bg=C["bg"],fg=C["dim"]); pct.pack(pady=4)
    tk.Frame(sp,bg=C["accent"],height=3).pack(fill="x",side="bottom")
    steps=max(20,SPLASH_SECONDS*25)
    interval_ms=max(1,int(SPLASH_SECONDS/steps*1000))
    def step(i=0):
        if i>steps:
            sp.destroy(); root.deiconify()
            try: root.state("zoomed")
            except: pass
            return
        pbv.set(i/steps*100); pct.config(text=f"{int(i/steps*100)}%")
        root.after(interval_ms, step, i+1)
    root.withdraw(); root.after(10, step)

show_splash()

mb=tk.Menu(root,bg=C["panel"],fg=C["text"],activebackground=C["accent"],activeforeground="black",relief="flat")
fm=tk.Menu(mb,tearoff=0,bg=C["panel"],fg=C["text"],activebackground=C["accent"],activeforeground="black")
fm.add_command(label="Add GPX Files…",command=lambda:add_files())
fm.add_command(label="Clear Queue",command=lambda:clear_queue())
fm.add_separator(); fm.add_command(label="Exit",command=root.destroy)
mb.add_cascade(label="File",menu=fm)
hm=tk.Menu(mb,tearoff=0,bg=C["panel"],fg=C["text"],activebackground=C["accent"],activeforeground="black")
hm.add_command(label="About",command=lambda:messagebox.showinfo("About",f"GPX Comment Video Generator\n{VERSION}\n{AUTHOR}\n{CONTACT}"))
mb.add_cascade(label="Help",menu=hm); root.config(menu=mb)

tk.Frame(root,bg=C["accent"],height=3).pack(fill="x")
tb=tk.Frame(root,bg=C["bg"]); tb.pack(fill="x",padx=20,pady=6)
tk.Label(tb,text="GPX COMMENT VIDEO GENERATOR",font=("Consolas",13,"bold"),bg=C["bg"],fg=C["accent"]).pack(side="left")
tk.Label(tb,text=f"{VERSION}  ·  {AUTHOR}  ·  2025–{datetime.now().year}",font=("Consolas",8),bg=C["bg"],fg=C["dim"]).pack(side="right",pady=2)
tk.Frame(root,bg=C["border"],height=1).pack(fill="x")

content=tk.Frame(root,bg=C["bg"]); content.pack(fill="both",expand=True)

# ── LEFT ──────────────────────────────────────────────────────────────────────
left=tk.Frame(content,bg=C["panel"],width=310); left.pack(side="left",fill="y",padx=(10,0),pady=10); left.pack_propagate(False)

sec_hdr(left,"FILE QUEUE")
br=tk.Frame(left,bg=C["panel"]); br.pack(fill="x",padx=12,pady=6)
mk_btn(br,"+ Add",C["green"],lambda:add_files()).pack(side="left",padx=(0,3))
mk_btn(br,"✕ Remove",C["red"],lambda:remove_selected()).pack(side="left",padx=3)
mk_btn(br,"⬜ Clear",C["dim"],lambda:clear_queue()).pack(side="left",padx=3)
lbf=tk.Frame(left,bg=C["border"],padx=1,pady=1); lbf.pack(fill="both",expand=True,padx=12,pady=(0,4))
lbsb=tk.Scrollbar(lbf,bg=C["panel2"]); lbsb.pack(side="right",fill="y")
file_listbox=tk.Listbox(lbf,bg=C["panel2"],fg=C["text"],selectbackground=C["accent"],selectforeground="black",
                         font=("Consolas",9),borderwidth=0,highlightthickness=0,relief="flat",yscrollcommand=lbsb.set,activestyle="none")
file_listbox.pack(fill="both",expand=True); lbsb.config(command=file_listbox.yview)
queue_count_lbl=tk.Label(left,text="0 files queued",font=("Consolas",8),bg=C["panel"],fg=C["muted"]); queue_count_lbl.pack(padx=12,anchor="w",pady=(0,4))

sec_hdr(left,"OUTPUT DESTINATION")
df=tk.Frame(left,bg=C["panel"]); df.pack(fill="x",padx=12,pady=6)
for val,txt in [(1,"Same folder as source"),(2,"Desktop / Videos"),(3,"Choose folder…")]:
    ttk.Radiobutton(df,text=txt,variable=dest_var,value=val).pack(anchor="w",pady=1)
tk.Label(df,textvariable=custom_dest,font=("Consolas",8),bg=C["panel"],fg=C["muted"],wraplength=270,anchor="w").pack(fill="x",pady=2)

sec_hdr(left,"VIDEO SETTINGS")
vs=tk.Frame(left,bg=C["panel"]); vs.pack(fill="x",padx=12,pady=6)

def vr(lbl,wfn):
    r=tk.Frame(vs,bg=C["panel"]); r.pack(fill="x",pady=2)
    tk.Label(r,text=lbl,font=("Consolas",8),bg=C["panel"],fg=C["muted"],width=15,anchor="w").pack(side="left")
    wfn(r)

def swatch(p,var):
    btn=[None]
    def pick():
        res=colorchooser.askcolor(color=var.get(),title="Pick colour")
        if res and res[1]: var.set(res[1]); btn[0].config(bg=res[1])
    b=tk.Button(p,bg=var.get(),width=5,relief="flat",cursor="hand2",command=pick); b.pack(side="left"); btn[0]=b

vr("Resolution",   lambda p:ttk.Combobox(p,textvariable=res_var,values=list(RESOLUTIONS.keys()),state="readonly",width=20).pack(side="left"))
vr("FPS",          lambda p:ttk.Spinbox(p,textvariable=fps_var,values=FPS_OPTIONS,width=6).pack(side="left"))
vr("Cmt font sz",  lambda p:ttk.Spinbox(p,textvariable=cmt_size_var,from_=8,to=72,width=6).pack(side="left"))
vr("Time font sz", lambda p:ttk.Spinbox(p,textvariable=ts_size_var,from_=6,to=48,width=6).pack(side="left"))
vr("BG colour",    lambda p:swatch(p,bg_color_var))
vr("Text colour",  lambda p:swatch(p,txt_color_var))
vr("Text align",   lambda p:ttk.Combobox(p,textvariable=align_var,values=["right","center","left"],state="readonly",width=10).pack(side="left"))

# ── CENTER MAP ────────────────────────────────────────────────────────────────
map_outer=tk.Frame(content,bg=C["bg"]); map_outer.pack(side="left",fill="both",expand=True,padx=8,pady=10)

# header row with title + zoom buttons
mh=tk.Frame(map_outer,bg=C["bg"]); mh.pack(fill="x",pady=(0,4))
tk.Label(mh,text="LIVE TRACK MAP",font=("Consolas",8,"bold"),bg=C["bg"],fg=C["accent"]).pack(side="left")
zf=tk.Frame(mh,bg=C["bg"]); zf.pack(side="right")

def zoom_in():
    current_zoom[0]=min(current_zoom[0]+1,19); map_widget.set_zoom(current_zoom[0])
def zoom_out():
    current_zoom[0]=max(current_zoom[0]-1,2); map_widget.set_zoom(current_zoom[0])

mk_btn(zf,"＋",C["panel2"],zoom_in,font=("Consolas",11,"bold")).pack(side="left",padx=2)
mk_btn(zf,"－",C["panel2"],zoom_out,font=("Consolas",11,"bold")).pack(side="left",padx=2)

# amber-bordered map
map_border=tk.Frame(map_outer,bg=C["accent"],padx=2,pady=2); map_border.pack(fill="both",expand=True)
map_widget=tkintermapview.TkinterMapView(map_border,corner_radius=0)
map_widget.pack(fill="both",expand=True)
map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
map_widget.set_position(45.0,7.0); map_widget.set_zoom(5)

# info bar below map
ib=tk.Frame(map_outer,bg=C["panel"],pady=8); ib.pack(fill="x",pady=(4,0))
info_left = tk.Frame(ib, bg=C["panel"])
info_left.pack(side="left", padx=14, fill="x", expand=True)

flag_label = tk.Label(info_left, bg=C["panel"])
flag_label.pack(side="left", padx=(0,8))

pt_cmt_lbl = tk.Label(
    info_left,
    text="—",
    font=("Consolas",13,"bold"),
    bg=C["panel"],
    fg=C["text"],
    anchor="w",
    wraplength=820,
    justify="left"
)

pt_cmt_lbl.pack(side="left",padx=14,fill="x",expand=True)
pt_time_lbl=tk.Label(ib,text="",font=("Consolas",10),bg=C["panel"],fg=C["muted"])
pt_time_lbl.pack(side="right",padx=14)

# ── RIGHT SIDEBAR ─────────────────────────────────────────────────────────────
right=tk.Frame(content,bg=C["panel"],width=270); right.pack(side="left",fill="y",padx=(0,10),pady=10); right.pack_propagate(False)

sec_hdr(right,"CONTROLS")
cr=tk.Frame(right,bg=C["panel"]); cr.pack(fill="x",padx=12,pady=8)
mk_btn(cr,"▶  Start Render",C["green"],lambda:start_rendering(),font=("Consolas",9,"bold")).pack(fill="x",pady=3)
_pb2=mk_btn(cr,"⏸  Pause",C["orange"],lambda:toggle_pause(),font=("Consolas",9,"bold")); _pb2.pack(fill="x",pady=3); pause_btn_ref[0]=_pb2
mk_btn(cr,"⏹  Stop",C["red"],lambda:request_stop(),font=("Consolas",9,"bold")).pack(fill="x",pady=3)

# ── Start from point ──────────────────────────────────────────────────────────
sp_row=tk.Frame(cr,bg=C["panel"]); sp_row.pack(fill="x",pady=(6,0))
tk.Label(sp_row,text="Start from pt:",font=("Consolas",8),bg=C["panel"],fg=C["muted"]).pack(side="left")
ttk.Entry(sp_row,textvariable=start_point_var,width=7,font=("Consolas",9)).pack(side="left",padx=6)
tk.Label(sp_row,text="(blank=0)",font=("Consolas",7),bg=C["panel"],fg=C["dim"]).pack(side="left")

# ── Flag toggle ───────────────────────────────────────────────────────────────
flag_btn=[None]
def toggle_flags():
    use_flags_var.set(not use_flags_var.get())
    if use_flags_var.get():
        flag_btn[0].config(text="🏳  Flags ON",bg=C["blue"])
    else:
        flag_btn[0].config(text="ABC  Country Code",bg=C["dim"])
# initial state matches default (True)
fb=mk_btn(cr,"\U0001f3f3  Flags ON",C["blue"],toggle_flags,font=("Consolas",8,"bold"))
fb.pack(fill="x",pady=(4,0)); flag_btn[0]=fb
tk.Label(cr,text="flags shown as PNG (Windows-safe)",
         font=("Consolas",7),bg=C["panel"],fg=C["dim"],justify="left").pack(anchor="w",pady=(2,0))

# ── Transparent background toggle ────────────────────────────────────────────
transp_btn=[None]
def toggle_transparent():
    transparent_var.set(not transparent_var.get())
    if transparent_var.get():
        transp_btn[0].config(text="\u25a1  Transparent ON",bg=C["blue"])
    else:
        transp_btn[0].config(text="\u25a0  Opaque BG",bg=C["dim"])
tb2=mk_btn(cr,"\u25a0  Opaque BG",C["dim"],toggle_transparent,font=("Consolas",8,"bold"))
tb2.pack(fill="x",pady=(4,0)); transp_btn[0]=tb2
tk.Label(cr,text="transparent → saves as .webm (VP9 alpha)",
         font=("Consolas",7),bg=C["panel"],fg=C["dim"],justify="left").pack(anchor="w",pady=(2,0))

sec_hdr(right,"PROGRESS")
pf=tk.Frame(right,bg=C["panel"]); pf.pack(fill="x",padx=12,pady=6)

def prog_row(p,lbl):
    r=tk.Frame(p,bg=C["panel"]); r.pack(fill="x",pady=2)
    tk.Label(r,text=lbl,font=("Consolas",7),bg=C["panel"],fg=C["muted"],width=10,anchor="w").pack(side="left")
    pb=ttk.Progressbar(r,maximum=100,length=1,mode="determinate"); pb.pack(side="left",fill="x",expand=True)
    pct=tk.Label(r,text=" 0%",font=("Consolas",7),bg=C["panel"],fg=C["accent"],width=4); pct.pack(side="left")
    return pb,pct

overall_pb,overall_pct=prog_row(pf,"Overall")
current_pb,current_pct=prog_row(pf,"Current")
file_info_lbl=tk.Label(pf,text="",font=("Consolas",8,"bold"),bg=C["panel"],fg=C["text"],wraplength=240,anchor="w"); file_info_lbl.pack(fill="x",pady=(6,0))
eta_lbl=tk.Label(pf,text="",font=("Consolas",14,"bold"),bg=C["panel"],fg=C["accent"]); eta_lbl.pack(anchor="w",pady=(4,2))
point_lbl=tk.Label(pf,text="",font=("Consolas",8),bg=C["panel"],fg=C["muted"]); point_lbl.pack(anchor="w")

sec_hdr(right,"RENDER LOG")
lf2=tk.Frame(right,bg=C["border"],padx=1,pady=1); lf2.pack(fill="both",expand=True,padx=12,pady=(4,4))
lgsb=tk.Scrollbar(lf2,bg=C["panel2"]); lgsb.pack(side="right",fill="y")
log_text=tk.Text(lf2,bg=C["panel2"],fg=C["text"],font=("Consolas",8),relief="flat",borderwidth=0,
                  highlightthickness=0,yscrollcommand=lgsb.set,state="disabled",wrap="word")
log_text.pack(fill="both",expand=True); lgsb.config(command=log_text.yview)
log_text.tag_config("ok",foreground=C["green"]); log_text.tag_config("err",foreground=C["red"]); log_text.tag_config("info",foreground=C["accent"])
mk_btn(right,"⬜ Clear log",C["dim"],lambda:log_text.delete("1.0",tk.END),font=("Consolas",8)).pack(padx=12,pady=(0,8),fill="x")

# ── STATUS BAR ────────────────────────────────────────────────────────────────
sb=tk.Frame(root,bg=C["panel"],height=26); sb.pack(fill="x",side="bottom")
tk.Frame(sb,bg=C["accent"],height=2).pack(fill="x",side="bottom")
status_lbl=tk.Label(sb,text="Ready.",font=("Consolas",8),bg=C["panel"],fg=C["muted"]); status_lbl.pack(side="left",padx=10,pady=3)

STATUS_ICON={"pending":("⏳ ",C["muted"]),"rendering":("🎬 ",C["accent"]),"done":("✅ ",C["green"]),"error":("❌ ",C["red"]),"skipped":("⏭ ",C["dim"])}

def clear_map():
    if map_path_obj[0]:
        try: map_path_obj[0].delete()
        except: pass
        map_path_obj[0]=None
    if map_marker_obj[0]:
        try: map_marker_obj[0].delete()
        except: pass
        map_marker_obj[0]=None
    map_all_coords.clear(); _last_pt[0]=-1

def draw_full_track(coords):
    clear_map(); map_all_coords.extend(coords)
    if len(coords)>1:
        try: map_path_obj[0]=map_widget.set_path(coords,color="#e53935",width=2)
        except: pass
    if coords:
        lats=[c[0] for c in coords]; lons=[c[1] for c in coords]
        clat=(min(lats)+max(lats))/2; clon=(min(lons)+max(lons))/2
        span=max(max(lats)-min(lats),max(lons)-min(lons))
        z=7 if span>5 else 9 if span>2 else 10 if span>1 else 12 if span>0.3 else 13 if span>0.1 else 14
        current_zoom[0]=z; map_widget.set_position(clat,clon); map_widget.set_zoom(z)

def update_marker(lat,lon):
    if map_marker_obj[0]:
        try: map_marker_obj[0].delete()
        except: pass
        map_marker_obj[0]=None
    try: map_marker_obj[0]=map_widget.set_marker(lat,lon,marker_color_circle="#ff3333",marker_color_outside="#ff3333")
    except: pass
    try: map_widget.set_position(lat,lon); map_widget.set_zoom(current_zoom[0])
    except: pass

def refresh_listbox():
    file_listbox.delete(0,tk.END)
    for fp in file_list:
        st=file_status.get(fp,"pending"); icon,col=STATUS_ICON[st]
        file_listbox.insert(tk.END,f"  {icon}{os.path.basename(fp)}"); file_listbox.itemconfig(tk.END,fg=col)
    queue_count_lbl.config(text=f"{len(file_list)} file(s) queued")

def log(msg,tag=""):
    log_text.config(state="normal"); ts=datetime.now().strftime("%H:%M:%S")
    log_text.insert(tk.END,f"[{ts}]  {msg}\n",tag); log_text.see(tk.END); log_text.config(state="disabled")

def set_status(msg): status_lbl.config(text=msg)

def add_files():
    paths=filedialog.askopenfilenames(title="Select geocoded GPX file(s)",filetypes=[("GPX files","*.gpx")])
    for p in paths:
        if p not in file_list: file_list.append(p); file_status[p]="pending"
    refresh_listbox()

def remove_selected():
    sel=file_listbox.curselection()
    if not sel: return
    fp=file_list[sel[0]]
    if file_status.get(fp)=="rendering": messagebox.showwarning("Busy","Cannot remove a file that is currently rendering."); return
    file_list.pop(sel[0]); file_status.pop(fp,None); refresh_listbox()

def clear_queue():
    if processing_state["running"]: messagebox.showwarning("Busy","Stop the render before clearing the queue."); return
    file_list.clear(); file_status.clear(); refresh_listbox(); clear_map()

def resolve_output_folder(fp):
    ch=dest_var.get()
    if ch==1: return os.path.dirname(fp)
    if ch==2:
        b=os.path.join(os.path.expanduser("~"),"Desktop","Videos"); os.makedirs(b,exist_ok=True); return b
    folder=custom_dest.get()
    if not folder or not os.path.isdir(folder):
        folder=filedialog.askdirectory(title="Select output folder")
        if not folder: return None
        custom_dest.set(folder)
    return folder

def toggle_pause():
    if not processing_state["running"]: messagebox.showinfo("Pause/Resume","No active render."); return
    if pause_event.is_set():
        pause_event.clear(); pause_btn_ref[0].config(text="▶  Resume"); set_status("Paused."); log("⏸  Paused.","info")
    else:
        pause_event.set(); pause_btn_ref[0].config(text="⏸  Pause"); set_status("Rendering…"); log("▶  Resumed.","info")

def request_stop():
    if not processing_state["running"]: messagebox.showinfo("Stop","No active render."); return
    if messagebox.askyesno("Stop","Stop rendering after the current frame?"):
        pause_event.set(); stop_event.set(); set_status("Stopping…"); log("⏹  Stop requested.","err")

def pump_ui_queue():
    try:
        while True:
            cmd,*args=ui_queue.get_nowait()
            if cmd=="progress":
                cf,tf,eta,abs_pt,tp,cmt,ts,use_fl=args
                rel_pt=abs_pt+1   # 1-based for display
                pct=int(cf/tf*100) if tf else 0
                current_pb["value"]=pct; current_pct.config(text=f"{pct:3d}%")
                eta_lbl.config(text=f"ETA  {eta}"); point_lbl.config(text=f"Point {rel_pt} / {tp}")
                try:
                    from datetime import timedelta
                    eh,em,es=map(int,eta.split(":"))
                    finish=datetime.now().replace(microsecond=0)+timedelta(hours=eh,minutes=em,seconds=es)
                    eta_lbl.config(text=f"ETA  {eta}   [{finish.strftime('%H:%M')}]")
                except Exception:
                    pass
                # Extract flag if present
                flag_img = None
                display_cmt = cmt or "—"

                if use_fl and ' | ' in cmt:
                    parts = cmt.split(' | ')
                    last = parts[-1].strip()

                    if len(last) == 3 and last.isalpha():
                        flag_img = get_flag_image(last)
                        display_cmt = ' | '.join(parts[:-1])

                pt_cmt_lbl.config(text=display_cmt)

                if flag_img:
                    flag_label.config(image=flag_img)
                    flag_label.image = flag_img
                else:
                    flag_label.config(image="")
                    flag_label.image = None

                # use absolute point index to look up map coordinate
                if abs_pt!=_last_pt[0] and map_all_coords:
                    idx=min(abs_pt,len(map_all_coords)-1)
                    if idx>=0: update_marker(*map_all_coords[idx])
                    _last_pt[0]=abs_pt
            elif cmd=="overall":
                done,total=args; pct=int(done/total*100) if total else 0
                overall_pb["value"]=pct; overall_pct.config(text=f"{pct:3d}%")
            elif cmd=="file_start":
                fp,idx,total,coords=args; name=os.path.basename(fp)
                file_info_lbl.config(text=f"File {idx}/{total}:  {name}")
                file_status[fp]="rendering"; refresh_listbox(); set_status(f"Rendering {name}…")
                draw_full_track(coords)
            elif cmd=="file_done":
                fp,ok=args; file_status[fp]="done" if ok else "error"; refresh_listbox()
            elif cmd=="log":
                msg,tag=args; log(msg,tag)
            elif cmd=="all_done":
                processing_state["running"]=False; pause_btn_ref[0].config(text="⏸  Pause")
                overall_pb["value"]=100; overall_pct.config(text="100%")
                current_pb["value"]=0; eta_lbl.config(text=""); file_info_lbl.config(text=""); point_lbl.config(text="")
                set_status(args[0])
                if "complete" in args[0].lower(): messagebox.showinfo("Done",args[0])
    except queue.Empty: pass
    root.after(80,pump_ui_queue)

root.after(80,pump_ui_queue)

def render_thread(targets,settings):
    total=len(targets); done=0; n_ok=0; n_err=0
    def pcb(cf,tf,eta,abs_pt,tp,cmt,ts,use_fl): ui_queue.put(("progress",cf,tf,eta,abs_pt,tp,cmt,ts,use_fl))
    def lcb(msg,tag=""): ui_queue.put(("log",msg,tag))
    start_point=settings.pop("start_point",0)
    for idx,fp in enumerate(targets,start=1):
        if stop_event.is_set(): break
        try: coords=extract_all_coords(fp)
        except: coords=[]
        ui_queue.put(("file_start",fp,idx,total,coords))
        lcb(f"── File {idx}/{total}:  {os.path.basename(fp)}","info")
        if start_point>0: lcb(f"   Starting from point {start_point}","info")
        try:
            comments=extract_comments(fp)
            if not comments: lcb("⚠  No comments — skipped.","err"); file_status[fp]="skipped"; ui_queue.put(("file_done",fp,False)); done+=1; ui_queue.put(("overall",done,total)); continue
            if start_point>=len(comments): lcb(f"⚠  Start point {start_point} ≥ total points {len(comments)} — skipped.","err"); ui_queue.put(("file_done",fp,False)); done+=1; ui_queue.put(("overall",done,total)); continue
            durations=calculate_durations(comments)
            out_folder=resolve_output_folder(fp)
            if not out_folder: lcb("⚠  No output folder — skipped.","err"); ui_queue.put(("file_done",fp,False)); done+=1; ui_queue.put(("overall",done,total)); continue
            stem=os.path.splitext(os.path.basename(fp))[0]
            ext=".webm" if settings.get("transparent",False) else ".mp4"
            out_path=os.path.join(out_folder,stem+ext)
            ok,last_pt=generate_video(comments,durations,out_path,settings,pause_event,stop_event,pcb,lambda m,t="ok":lcb(m,t),start_point=start_point)
            if ok:
                lcb(f"✅  Saved → {out_path}","ok"); n_ok+=1
            else:
                lcb(f"⏹  Stopped at point {last_pt} — partial file kept.","err"); n_err+=1
            ui_queue.put(("file_done",fp,ok))
        except Exception as e: lcb(f"❌  Error: {e}","err"); ui_queue.put(("file_done",fp,False)); n_err+=1
        done+=1; ui_queue.put(("overall",done,total))
        if stop_event.is_set(): break
        start_point=0   # start_point only applies to the first file
    if stop_event.is_set():
        stop_event.clear(); ui_queue.put(("all_done","Render stopped."))
    else:
        msg=f"Render complete — {n_ok} succeeded, {n_err} failed."
        lcb(msg,"ok"); ui_queue.put(("all_done",msg))
    processing_state["running"]=False

def start_rendering():
    if processing_state["running"]: messagebox.showinfo("Busy","A render is already in progress."); return
    targets=[fp for fp in file_list if file_status.get(fp) in ("pending","error")]
    if not targets: messagebox.showwarning("Nothing to render","No pending files in the queue.\nAdd GPX files or clear completed ones."); return
    settings={"resolution":RESOLUTIONS.get(res_var.get(),(1280,720)),"fps":fps_var.get(),
              "bg_color":bg_color_var.get(),"text_color":txt_color_var.get(),
              "cmt_fontsize":cmt_size_var.get(),"time_fontsize":ts_size_var.get(),
              "text_align":align_var.get(),"use_flags":use_flags_var.get(),
              "transparent":transparent_var.get(),
              "start_point":max(0,int(start_point_var.get())) if start_point_var.get().strip().isdigit() else 0}
    stop_event.clear(); pause_event.set(); processing_state["running"]=True
    overall_pb["value"]=0; overall_pct.config(text="  0%"); pause_btn_ref[0].config(text="⏸  Pause")
    log(f"▶  Starting render — {len(targets)} file(s)","info")
    t=threading.Thread(target=render_thread,args=(targets,settings),daemon=True)
    processing_state["thread"]=t; t.start()

def on_close():
    if processing_state["running"]:
        if not messagebox.askyesno("Quit","A render is in progress. Quit anyway?"): return
        stop_event.set(); pause_event.set()
    root.destroy()

root.protocol("WM_DELETE_WINDOW",on_close)

if __name__=="__main__":
    root.mainloop()