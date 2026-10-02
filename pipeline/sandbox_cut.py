"""Higgsfield-sandbox side of the final edit (the CI container can't reach the CDN).

Reads cut.json (shots with take URLs, start/end keyframe URLs, narration URL),
scores every take for seamless joins, picks the best, mixes the narration over
the shot SFX at vo_offset, burns word-timed subtitles and joins everything with
crossfades. Writes final.mp4 and picks.json.
"""
import json, os, subprocess, sys
import numpy as np
from PIL import Image, ImageFilter

W, H, FPS = 720, 1280, 24
cfg = json.load(open("cut.json"))
os.makedirs("w", exist_ok=True)


def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-1500:])
    return r.stdout


def get(url, path):
    if not url.startswith("http"):
        url = cfg["base"] + url
    if not os.path.exists(path):
        sh("curl", "-sfL", "-o", path, url)
    return path


def dur(p):
    return float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p))


def frame(video, last, out):
    if last:
        n = int(sh("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                   "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", video).strip())
        sh("ffmpeg", "-v", "error", "-y", "-i", video, "-vf", f"select=eq(n\\,{n-1})", "-vsync", "0", "-frames:v", "1", out)
    else:
        sh("ffmpeg", "-v", "error", "-y", "-i", video, "-frames:v", "1", out)
    return Image.open(out)


def sim(a, b):
    f = lambda im: np.asarray(im.convert("RGB").resize((54, 96)).filter(ImageFilter.GaussianBlur(1)), float).ravel()
    return float(np.corrcoef(f(a), f(b))[0, 1])


# ---- pick takes
shots = cfg["shots"]
picks = {}
for i, s in enumerate(shots):
    kf = Image.open(get(s["start"], f"w/{s['id']}_kf.png"))
    nxt = shots[i + 1] if i + 1 < len(shots) and not shots[i + 1].get("cut_before") else None
    nk = Image.open(get(nxt["start"], f"w/{nxt['id']}_kf.png")) if nxt else None
    best = None
    for n, url in enumerate(s["takes"], 1):
        v = get(url, f"w/{s['id']}_t{n}.mp4")
        sc = sim(frame(v, False, "w/f.png"), kf)
        if nk is not None:
            sc += sim(frame(v, True, "w/l.png"), nk)
        if best is None or sc > best[1]:
            best = (n, sc)
    picks[s["id"]] = {"take": best[0], "score": round(best[1], 3)}
json.dump(picks, open("picks.json", "w"), indent=1)
print("PICKS", json.dumps(picks))

# ---- per shot: normalize video, compress narration, mix
from faster_whisper import WhisperModel
wm = WhisperModel("base.en", compute_type="int8")
off = cfg.get("vo_offset", 0.3)
parts, words = [], []
for s in shots:
    v = f"w/{s['id']}_t{picks[s['id']]['take']}.mp4"
    vo = get(s["vo"], f"w/{s['id']}_vo.wav")
    sh("ffmpeg", "-v", "error", "-y", "-i", vo, "-af",
       "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.45:"
       "stop_threshold=-45dB:stop_silence=0.35,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
       "-ar", "48000", "-ac", "2", f"w/{s['id']}_voc.wav")
    vd = dur(f"w/{s['id']}_voc.wav")
    d = max(dur(v), vd + off + 0.4)  # never cut the narration short
    out = f"w/{s['id']}_mix.mp4"
    sh("ffmpeg", "-v", "error", "-y", "-i", v, "-i", f"w/{s['id']}_voc.wav", "-filter_complex",
       f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,"
       f"tpad=stop_mode=clone:stop_duration=5,trim=duration={d:.3f},format=yuv420p[v];"
       f"[0:a]aresample=48000,volume=0.30,apad,atrim=duration={d:.3f}[sfx];"
       f"[1:a]adelay={int(off*1000)}|{int(off*1000)},apad,atrim=duration={d:.3f}[vo];"
       f"[sfx][vo]amix=inputs=2:duration=first:normalize=0[a]",
       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
       "-c:a", "aac", "-ar", "48000", "-b:a", "192k", out)
    segs, _ = wm.transcribe(f"w/{s['id']}_voc.wav", word_timestamps=True)
    ws = [(w.start + off, w.end + off, w.word.strip()) for g in segs for w in g.words]
    parts.append((s, out, dur(out), ws))

# ---- timeline with crossfades
t, starts = 0.0, []
for k, (s, p, d, ws) in enumerate(parts):
    x = 0.0 if k == 0 else min(s.get("transition_in", cfg.get("xfade", 0.25)), d / 2, parts[k - 1][2] / 2)
    t -= x
    starts.append((t, x))
    for a, b, wd in ws:
        words.append((t + a, t + b, wd))
    t += d

# ---- subtitles: 3-word chunks, ASS
def ts(x):
    return f"{int(x//3600)}:{int(x%3600//60):02d}:{x%60:05.2f}"
ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
       "[V4+ Styles]",
       "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,"
       "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
       "Style: Cap,Montserrat,56,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,330,1",
       "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
for i in range(0, len(words), 3):
    ch = words[i:i + 3]
    end = words[i + 3][0] if i + 3 < len(words) else ch[-1][1] + 0.4
    txt = " ".join(w for _, _, w in ch).upper().replace(",", "")
    ass.append(f"Dialogue: 0,{ts(ch[0][0])},{ts(min(end, ch[-1][1] + 0.6))},Cap,,0,0,0,,{txt}")
open("subs.ass", "w").write("\n".join(ass) + "\n")

# ---- join
cmd = ["ffmpeg", "-v", "error", "-y"]
for _, p, _, _ in parts:
    cmd += ["-i", p]
vf, af, vl, al, acc = [], [], "[0:v]", "[0:a]", parts[0][2]
for k in range(1, len(parts)):
    x = starts[k][1]
    vf.append(f"{vl}[{k}:v]xfade=transition=fade:duration={x:.3f}:offset={acc - x:.3f}[v{k}]")
    af.append(f"{al}[{k}:a]acrossfade=d={x:.3f}[a{k}]")
    vl, al, acc = f"[v{k}]", f"[a{k}]", acc + parts[k][2] - x
vf.append(f"{vl}subtitles=subs.ass[vout]" if cfg.get("subtitles", True) else f"{vl}null[vout]")
af.append(f"{al}loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
cmd += ["-filter_complex", ";".join(vf + af), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "final.mp4"]
sh(*cmd)
print("FINAL", dur("final.mp4"))
