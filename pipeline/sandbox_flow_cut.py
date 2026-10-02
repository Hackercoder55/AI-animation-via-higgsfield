"""Higgsfield-sandbox "one flow" cut: voice-over only, no visible cuts, no dead air.

flow.json: base URL, chunks [{url, gap_before, shots: [[id, text], ...]}], takes {id: file}, flash_before [ids].
1. Narration: each chunk's pauses are squeezed to <=0.22s and the chunks are laid end to end, so
   the voice never stops. It is the master clock.
2. Picture: each shot fills exactly the time from its first spoken word (minus a short lead) to the
   next shot's. Spare picture is trimmed off the tail (after a slight speed-up, max 1.12x); a short
   shot is slowed with motion interpolation (min 0.85x) and the next shot starts that much earlier.
3. Joins are camera moves, not cuts: alternating zoom-through (push in on the outgoing shot, settle
   out of the incoming one) and whip pans with motion blur; a white flash where flash_before.
4. Audio is the narration only (shot audio is dropped), loudness-normalised.
"""
import difflib, json, os, re, subprocess, sys
from faster_whisper import WhisperModel

W, H, FPS = 720, 1280, 24
cfg = json.load(open("flow.json"))
os.makedirs("f", exist_ok=True)


def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    if r.returncode:
        sys.exit(" ".join(a[:4]) + "\n" + r.stderr[-2000:])
    return r.stdout


dur = lambda p: float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p))
norm = lambda w: re.sub(r"[^a-z0-9']", "", w.lower())


def get(url, path):
    if not os.path.exists(path):
        sh("curl", "-sfL", "-o", path, url if url.startswith("http") else cfg["base"] + url)
    return path


# ---- 1) narration
wm = WhisperModel("base.en", compute_type="int8")
t, firsts, vo, delays = cfg.get("lead_in", 0.2), [], [], []
for k, ch in enumerate(cfg["chunks"]):
    raw, out = get(ch["url"], f"f/c{k}.wav"), f"f/t{k}.wav"
    sh("ffmpeg", "-v", "error", "-y", "-i", raw, "-af",
       "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.3:"
       "stop_threshold=-45dB:stop_silence=0.22,areverse,silenceremove=start_periods=1:start_threshold=-45dB,"
       "areverse,aresample=48000", "-ac", "2", out)
    if k:
        t += ch.get("gap_before", 0.2)
    segs, _ = wm.transcribe(out, word_timestamps=True)
    heard = [(w.start, norm(w.word)) for g in segs for w in g.words]
    script, owner = [], []
    for sid, text in ch["shots"]:
        toks = [norm(x) for x in text.split() if norm(x)]
        script += toks
        owner += [sid] * len(toks)
    sm = difflib.SequenceMatcher(None, script, [h for _, h in heard], autojunk=False)
    hit = {}
    for b in sm.get_matching_blocks():
        for i in range(b.size):
            hit[b.a + i] = b.b + i
    for sid, _ in ch["shots"]:
        idx = [hit[i] for i, o in enumerate(owner) if o == sid and i in hit]
        firsts.append((sid, t + (heard[min(idx)][0] if idx else 0.0)))
    vo.append(out)
    delays.append(t)
    t += dur(out)
vo_end = t
print("FIRST", [(s, round(x, 2)) for s, x in firsts], "VO_END", round(vo_end, 2), flush=True)

# ---- 2) slots
ids = [s for s, _ in firsts]
lead = cfg.get("pre_roll", 0.15)
P = [0.0] + [x - lead for _, x in firsts[1:]] + [vo_end + cfg.get("tail", 0.8)]
for k, sid in enumerate(ids):
    if sid in cfg.get("flash_before", []):
        P[k] = firsts[k][1] - 0.45  # flash peak just before the first word
X = [0.0] + [0.8 if s in cfg.get("flash_before", []) else 0.5 for s in ids[1:]] + [0.0]
KIND = [None] + [("flash" if ids[k] in cfg.get("flash_before", []) else ("zoom" if k % 2 else "whip"))
                 for k in range(1, len(ids))] + [None]

src, D = {}, {}
for sid in ids:
    src[sid] = get(cfg["takes"][sid], f"f/{sid}.mp4")
    D[sid] = dur(src[sid])

plan = []
for k, sid in enumerate(ids):
    c = (P[k + 1] - P[k]) + X[k] / 2 + X[k + 1] / 2
    v = D[sid]
    if c <= v:
        s = min(v / c, 1.12)  # play a touch faster, trim the rest off the tail
    else:
        s = max(v / c, 0.85)
        short = c - v / s
        if short > 0.04 and k + 1 < len(ids):  # next shot starts a bit early instead of freezing
            give = min(short, 0.9)
            P[k + 1] -= give
            c -= give
    plan.append((sid, c, s))

# ---- 3) render shots with continuous camera drift + transition moves
clips = []
for k, (sid, c, s) in enumerate(plan):
    zi = 0.18 if KIND[k] == "zoom" else 0.0          # settle out of a push-in
    zo = 0.18 if KIND[k + 1] == "zoom" else 0.0      # push into the next shot
    xi, xo = max(X[k], 0.01), max(X[k + 1], 0.01)
    drift = f"0.05*t/{c:.3f}" if k % 2 == 0 else f"0.05*(1-t/{c:.3f})"
    z = (f"(1+{drift}+{zi}*pow(max(0,1-t/{xi:.3f}),2)+{zo}*pow(max(0,(t-{c - xo:.3f})/{xo:.3f}),2))")
    interp = f",minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir" if s < 0.97 else ""
    out = f"f/{sid}_v.mp4"
    sh("ffmpeg", "-v", "error", "-y", "-i", src[sid], "-an", "-vf",
       f"setpts=PTS/{s:.4f},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}{interp},fps={FPS},"
       f"tpad=stop_mode=clone:stop_duration=3,trim=duration={c:.3f},setpts=PTS-STARTPTS,"
       f"scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame,crop={W}:{H},setsar=1,format=yuv420p",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out)
    clips.append((out, c))
    print(sid, f"slot={c:.2f} src={D[sid]:.2f} speed={s:.2f} used={c * s:.2f}", flush=True)

# ---- 4) join + narration
cmd = ["ffmpeg", "-v", "error", "-y"]
for p, _ in clips:
    cmd += ["-i", p]
for p in vo:
    cmd += ["-i", p]
vf, vl, acc = [], "[0:v]", clips[0][1]
for k in range(1, len(clips)):
    x, kind = X[k], KIND[k]
    tr = {"flash": "fadewhite", "zoom": "fade"}.get(kind, "smoothleft" if k % 4 == 1 else "smoothright")
    a, b = acc - x, acc
    vf.append(f"{vl}[{k}:v]xfade=transition={tr}:duration={x}:offset={a:.3f}[x{k}]")
    vf.append(f"[x{k}]tblend=all_mode=average:enable='between(t,{a:.3f},{b:.3f})'[v{k}]" if kind != "flash"
              else f"[x{k}]null[v{k}]")
    vl, acc = f"[v{k}]", acc + clips[k][1] - x
n, af = len(clips), []
for j, d in enumerate(delays):
    ms = int(round(d * 1000))
    af.append(f"[{n + j}:a]adelay={ms}|{ms}[n{j}]")
af.append("".join(f"[n{j}]" for j in range(len(delays))) +
          f"amix=inputs={len(delays)}:duration=longest:normalize=0,apad,atrim=duration={acc:.3f},"
          "loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
cmd += ["-filter_complex", ";".join(vf + af), "-map", vl, "-map", "[aout]", "-c:v", "libx264", "-preset", "medium",
        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "final_flow.mp4"]
sh(*cmd)
print("FINAL", round(dur("final_flow.mp4"), 2), "timeline", round(acc, 2), flush=True)
