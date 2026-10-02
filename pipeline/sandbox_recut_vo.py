"""Higgsfield-sandbox re-cut with the narration as master clock.

Run in the sandbox dir that holds w/S??_t?.mp4 (takes), picks.json and vo/c?.wav
(continuous narration chunks). recut.json lists, per chunk, the shot ids and their
spoken text. The narration is laid down as one track (chunks joined with short
natural gaps); every shot is retimed (slowed/sped up, then held or trimmed) so its
cut lands just before its first spoken word. Cuts are hidden with a slow push/pull on
every shot plus whip-pan transitions (white flash where cut_before). No subtitles.
"""
import difflib, json, re, subprocess, sys
from faster_whisper import WhisperModel

W, H, FPS = 720, 1280, 24
cfg = json.load(open("recut.json"))
picks = json.load(open("picks.json"))


def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-2000:])
    return r.stdout


dur = lambda p: float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p))
norm = lambda w: re.sub(r"[^a-z0-9']", "", w.lower())

# ---- 1) narration track: trim each chunk's edge silence, join with gaps
wm = WhisperModel("base.en", compute_type="int8")
lead, t, firsts, vo_inputs, delays = cfg.get("lead_in", 0.3), cfg.get("lead_in", 0.3), [], [], []
for k, ch in enumerate(cfg["chunks"]):
    src, out = ch["file"], f"vo/t{k}.wav"
    sh("ffmpeg", "-v", "error", "-y", "-i", src, "-af",
       "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
       "silenceremove=start_periods=1:start_threshold=-45dB,areverse,aresample=48000",
       "-ac", "2", out)
    if k:
        t += ch.get("gap_before", 0.5)
    segs, _ = wm.transcribe(out, word_timestamps=True)
    heard = [(w.start, norm(w.word)) for g in segs for w in g.words]
    script, owner = [], []
    for sid, text in ch["shots"]:
        toks = [norm(x) for x in text.split() if norm(x)]
        owner += [sid] * len(toks)
        script += toks
    sm = difflib.SequenceMatcher(None, script, [h for _, h in heard], autojunk=False)
    first_idx = {}
    for i, sid in enumerate(owner):
        first_idx.setdefault(sid, i)
    for sid, _ in ch["shots"]:
        i0 = first_idx[sid]
        # earliest matched script token at/after the shot's first token
        hit = min((b.b + (i - b.a) for b in sm.get_matching_blocks() for i in range(b.a, b.a + b.size) if i >= i0
                   and owner[i] == sid), default=None)
        st = heard[hit][0] if hit is not None else 0.0
        firsts.append((sid, t + st))
    vo_inputs.append(out)
    delays.append(t)
    t += dur(out)
vo_end = t
print("FIRST_WORDS", [(s, round(x, 2)) for s, x in firsts], "VO_END", round(vo_end, 2), flush=True)

# ---- 2) shot boundaries + transitions
ids = [s for s, _ in firsts]
pre = cfg.get("pre_roll", 0.25)
b = [0.0] + [max(0.0, x - pre) for _, x in firsts[1:]]
for k, sid in enumerate(ids):
    if sid in cfg.get("cut_before", []):  # flash lands in the gap, before the first word
        b[k] = firsts[k][1] - cfg.get("flash_lead", 0.9)
b.append(vo_end + cfg.get("tail", 1.2))
X = [0.0]
for k in range(1, len(ids)):
    X.append(0.8 if ids[k] in cfg.get("cut_before", []) else 0.35)
X.append(0.0)

# ---- 3) per shot: retime to its slot, slow push/pull, SFX bed
clips = []
for k, sid in enumerate(ids):
    c = (b[k + 1] - b[k]) + X[k] / 2 + X[k + 1] / 2
    src = f"w/{sid}_t{picks[sid]['take']}.mp4"
    v = dur(src)
    f = min(c / v, 1.35) if c > v else max(c / v, 0.8)  # >1 slows down, <1 speeds up
    z = 0.06
    e = f"(1+{z}*t/{c:.3f})" if k % 2 == 0 else f"(1+{z}-{z}*t/{c:.3f})"
    out = f"w/{sid}_v3.mp4"
    sh("ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex",
       f"[0:v]setpts={f:.4f}*PTS,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
       f"tpad=stop_mode=clone:stop_duration=10,trim=duration={c:.3f},setpts=PTS-STARTPTS,"
       f"scale=w='trunc({W}*{e}/2)*2':h='trunc({H}*{e}/2)*2':eval=frame,crop={W}:{H},setsar=1,format=yuv420p[v];"
       f"[0:a]aresample=48000,atempo={1/f:.4f},volume={cfg.get('sfx_volume', 0.3)},apad,atrim=duration={c:.3f}[a]",
       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
       "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", out)
    clips.append((out, c))
    print(sid, f"slot={c:.2f} src={v:.2f} speed={1/f:.2f}", flush=True)

# ---- 4) join pictures (whip pans / white flash) + SFX, lay narration on top
cmd = ["ffmpeg", "-v", "error", "-y"]
for p, _ in clips:
    cmd += ["-i", p]
for p in vo_inputs:
    cmd += ["-i", p]
vf, af, vl, al, acc = [], [], "[0:v]", "[0:a]", clips[0][1]
for k in range(1, len(clips)):
    x = X[k]
    tr = "fadewhite" if ids[k] in cfg.get("cut_before", []) else ("smoothleft" if k % 2 else "smoothright")
    vf.append(f"{vl}[{k}:v]xfade=transition={tr}:duration={x}:offset={acc - x:.3f}[x{k}]")
    vf.append(f"[x{k}]tblend=all_mode=average:enable='between(t,{acc - x:.3f},{acc:.3f})'[v{k}]"
              if tr.startswith("smooth") else f"[x{k}]null[v{k}]")
    af.append(f"{al}[{k}:a]acrossfade=d={x}[a{k}]")
    vl, al, acc = f"[v{k}]", f"[a{k}]", acc + clips[k][1] - x
n = len(clips)
for j, d in enumerate(delays):
    ms = int(d * 1000)
    af.append(f"[{n + j}:a]adelay={ms}|{ms}[n{j}]")
af.append(f"{al}" + "".join(f"[n{j}]" for j in range(len(delays))) +
          f"amix=inputs={len(delays) + 1}:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
cmd += ["-filter_complex", ";".join(vf + af), "-map", vl, "-map", "[aout]", "-c:v", "libx264", "-preset", "medium",
        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "final_v3.mp4"]
sh(*cmd)
print("FINAL3", dur("final_v3.mp4"), "expected", round(b[-1], 2), flush=True)
