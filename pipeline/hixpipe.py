#!/usr/bin/env python3
"""hixpipe - script + characters -> final animated film, via Higgsfield.

Asset-first AI animation pipeline (based on the Hixled "Passport Rush" workflow):

    init      create a new project folder from the template
    check     validate project.json (assets, shots, durations, files)
    asset-prompt  build the image prompt for a character/location/prop/fx sheet
    prompt    build 5-block video prompts + Higgsfield request JSON for shots
    take      record / download a generated take, approve one per shot
    status    show what is done and what is left
    assemble  cut approved takes into the final video (ffmpeg)

Generation itself happens through the Higgsfield MCP tools (generate_image /
generate_video) driven by Claude Code - see CLAUDE.md. This CLI owns the
deterministic parts: prompt structure, bookkeeping and the final edit.
Standard library only; needs ffmpeg/ffprobe on PATH for `assemble`.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
PROJECT_TEMPLATE = ROOT / "projects" / "_template"

# Duration limits (seconds) and reference roles of the video models we route to.
VIDEO_MODELS = {
    "seedance_2_5": {"min": 4, "max": 30, "has_mode": True},
    "cinematic_studio_video_4_0": {"min": 4, "max": 30, "has_mode": True},
    "seedance_2_0": {"min": 4, "max": 15, "has_mode": False},
    "minimax_h3": {"min": 4, "max": 15, "has_mode": False},
    "kling3_0": {"min": 3, "max": 15, "has_mode": False},
}
ROUTES = ("t2v", "previs", "keyframe")
ASSET_TYPES = ("character", "location", "prop", "fx", "lighting")

ANIMATION_PRINCIPLES = (
    "Apply the 12 principles of animation: squash and stretch, anticipation, "
    "staging, straight-ahead and pose-to-pose, follow-through and overlapping "
    "action, slow in and slow out, arcs, secondary action, timing, "
    "exaggeration, solid drawing, appeal. Movement is snappy and cartoony, "
    "with clear holds on key poses so every beat reads."
)
DEFAULT_LOCKS = [
    "No music. SFX and ambience only.",
    "No extra people, characters, text, logos or subtitles beyond the references.",
    "Characters, environments and props 100% match the reference images - "
    "same design, colors, proportions and outfit in every frame.",
    "Keep one consistent art style for the whole shot; no switch to photorealism.",
]


class PipelineError(Exception):
    pass


# --------------------------------------------------------------------------- io
def project_dir(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if (p / "project.json").exists():
        return p.resolve()
    q = ROOT / "projects" / name_or_path
    if (q / "project.json").exists():
        return q
    raise PipelineError(f"no project.json found for '{name_or_path}'")


def load(pdir: Path) -> dict:
    with open(pdir / "project.json", encoding="utf-8") as f:
        return json.load(f)


def save(pdir: Path, proj: dict) -> None:
    tmp = pdir / "project.json.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(proj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(pdir / "project.json")


def find_shot(proj: dict, shot_id: str) -> dict:
    for s in proj.get("shots", []):
        if s["id"] == shot_id:
            return s
    raise PipelineError(f"unknown shot '{shot_id}'")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "film"


# ------------------------------------------------------------------- validation
def validate(proj: dict, pdir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    assets = proj.get("assets", {})
    models = proj.get("models", {})
    vmodel = models.get("video", "seedance_2_5")
    if vmodel not in VIDEO_MODELS:
        warnings.append(f"video model '{vmodel}' is not in the known table; durations unchecked")

    for aid, a in assets.items():
        if a.get("type") not in ASSET_TYPES:
            errors.append(f"asset {aid}: type must be one of {ASSET_TYPES}")
        for f in a.get("source_files", []):
            if not (pdir / f).exists():
                warnings.append(f"asset {aid}: source file missing: {f}")
        if a.get("locked") and not (a.get("element_id") or a.get("media_id") or a.get("media_ids")):
            errors.append(f"asset {aid}: locked but has no element_id or media_id")

    seen = set()
    for s in proj.get("shots", []):
        sid = s.get("id", "?")
        if sid in seen:
            errors.append(f"shot {sid}: duplicate id")
        seen.add(sid)
        route = s.get("route", "t2v")
        if route not in ROUTES:
            errors.append(f"shot {sid}: route must be one of {ROUTES}")
        model = s.get("model") or (models.get("video_previs") if route == "previs" else None) or vmodel
        lim = VIDEO_MODELS.get(model)
        dur = s.get("duration")
        if not isinstance(dur, (int, float)) or dur <= 0:
            errors.append(f"shot {sid}: duration must be a positive number")
        elif lim and not (lim["min"] <= dur <= lim["max"]):
            errors.append(f"shot {sid}: duration {dur}s outside {model} range {lim['min']}-{lim['max']}s")
        for ref in s.get("assets", []):
            if ref not in assets:
                errors.append(f"shot {sid}: references unknown asset '{ref}'")
            elif not assets[ref].get("locked"):
                warnings.append(f"shot {sid}: asset '{ref}' not locked yet (asset-first: lock before generating)")
        if not s.get("beats"):
            errors.append(f"shot {sid}: needs at least one beat")
        if route == "previs" and not (s.get("previs_media_id") or s.get("previs_file")):
            warnings.append(f"shot {sid}: previs route but no previs_file / previs_media_id yet")
        if route == "keyframe" and not s.get("keyframe_media_id"):
            warnings.append(f"shot {sid}: keyframe route but no keyframe_media_id yet")
        for t in s.get("takes", []):
            if t.get("file") and not (pdir / t["file"]).exists():
                warnings.append(f"shot {sid}: take file missing: {t['file']}")
    return errors, warnings


# --------------------------------------------------------------------- prompts
def asset_handle(aid: str, a: dict) -> str:
    """How an asset is named inside a prompt.

    Higgsfield reference elements are embedded as <<<element_id>>> and the
    backend injects the image; plain uploaded images are named @<id> and passed
    as image_references.
    """
    if a.get("element_id"):
        return f"<<<{a['element_id']}>>>"
    return f"@{aid}"


def build_shot_prompt(proj: dict, shot: dict) -> str:
    style = proj.get("style", {})
    assets = proj.get("assets", {})
    route = shot.get("route", "t2v")
    out: list[str] = []

    # 1. Scene context & style - the first ~20% of the prompt weighs the most.
    out.append("SCENE CONTEXT & STYLE")
    out.append(shot["context"].strip())
    style_bits = [
        f"Style: {style['look']}." if style.get("look") else "",
        f"Lighting: {shot.get('lighting') or style['lighting']}." if (shot.get("lighting") or style.get("lighting")) else "",
        f"World physics: {style['physics']}." if style.get("physics") else "",
    ]
    out.append(" ".join(b for b in style_bits if b))
    for rule in style.get("rules", []):
        out.append(f"- {rule}")

    # 2. Active references - a call sheet. Role + personality, never visuals.
    out.append("")
    out.append("ACTIVE REFERENCES")
    for ref in shot.get("assets", []):
        a = assets.get(ref, {})
        line = f"{asset_handle(ref, a)} = {a.get('name', ref)} ({a.get('type', 'asset')})"
        if a.get("role"):
            line += f": {a['role']}"
        if a.get("personality"):
            line += f". Personality: {a['personality']}"
        out.append(line)
    if route == "previs":
        out.append(
            "@previs = attached video reference. Follow ONLY its motion, timing, "
            "blocking and camera move. Ignore its gray untextured look - all "
            "appearance comes from the image references."
        )
    if next_continuous(proj, shot):
        out.append("@end_frame = final frame. The shot must end exactly on this image - same framing, "
                   "poses and positions.")
    if route == "keyframe":
        out.append(
            "@keyframe = start frame. Keep its framing and camera angle; the "
            "character design still comes from the character references."
        )
    out.append("Characters, environments and props 100% match the reference.")

    # 3. Shot structure - the storyboard in words, beat by beat with timing.
    out.append("")
    out.append("SHOT STRUCTURE")
    out.append(f"Single continuous shot, {shot['duration']}s." if not shot.get("cuts")
               else f"{shot['duration']}s total, hard cuts as listed.")
    if shot.get("camera"):
        out.append(f"Camera: {shot['camera']}")
    if next_continuous(proj, shot):
        out.append("One unbroken take with no cuts: the camera moves smoothly and continuously so the "
                   "final frame lands exactly on @end_frame (the next shot's opening frame).")
    for b in shot.get("beats", []):
        if isinstance(b, dict):
            out.append(f"- {b.get('t', '')}: {b['action']}".replace("- : ", "- "))
        else:
            out.append(f"- {b}")
    if shot.get("sfx"):
        out.append(f"Sound: {shot['sfx']}")

    # 4. Locks & constraints.
    out.append("")
    out.append("LOCKS & CONSTRAINTS")
    locks = list(DEFAULT_LOCKS) + proj.get("locks", []) + shot.get("locks", [])
    for ref in shot.get("assets", []):
        a = assets.get(ref, {})
        if a.get("age"):
            locks.append(f"{a.get('name', ref)} is {a['age']} in every frame - same age, face and "
                         "body proportions as the reference; never younger or older.")
    for lock in dict.fromkeys(locks):
        out.append(f"- {lock}")

    # 5. Animation principles.
    out.append("")
    out.append("ANIMATION PRINCIPLES")
    out.append(proj.get("animation_principles", ANIMATION_PRINCIPLES))
    if shot.get("acting"):
        out.append(f"Acting notes: {shot['acting']}")
    return "\n".join(out).strip() + "\n"


def next_continuous(proj: dict, shot: dict) -> dict | None:
    """The following shot when the film is one continuous take across this join.

    With project "continuous": true every shot ends exactly on the next shot's
    start frame (end_image), so the edit has no visible cut. A shot with
    "cut_before": true (location change, time jump) breaks the chain.
    """
    if not proj.get("continuous"):
        return None
    shots = proj.get("shots", [])
    i = next((k for k, s in enumerate(shots) if s["id"] == shot["id"]), None)
    if i is None or i + 1 >= len(shots):
        return None
    nxt = shots[i + 1]
    if nxt.get("cut_before") or not nxt.get("keyframe_media_id"):
        return None
    return nxt


def build_request(proj: dict, shot: dict, prompt: str) -> dict:
    """Params for mcp__Higgsfield__generate_video."""
    models = proj.get("models", {})
    route = shot.get("route", "t2v")
    model = shot.get("model") or (models.get("video_previs") if route == "previs" else None) \
        or models.get("video", "seedance_2_5")
    assets = proj.get("assets", {})

    medias = []
    for ref in shot.get("assets", []):
        a = assets.get(ref, {})
        # element_id references are injected by the backend from the prompt.
        if a.get("element_id"):
            continue
        for mid in a.get("media_ids") or ([a["media_id"]] if a.get("media_id") else []):
            medias.append({"value": mid, "role": "image_references", "_label": f"@{ref}"})
    for mid in shot.get("extra_reference_media_ids", []):
        medias.append({"value": mid, "role": "image_references", "_label": "@extra"})
    if route == "previs" and shot.get("previs_media_id"):
        medias.append({"value": shot["previs_media_id"], "role": "video_references", "_label": "@previs"})
    if route == "keyframe" and shot.get("keyframe_media_id"):
        medias.append({"value": shot["keyframe_media_id"], "role": "start_image", "_label": "@keyframe"})
    nxt = next_continuous(proj, shot)
    if nxt:
        medias.append({"value": nxt["keyframe_media_id"], "role": "end_image", "_label": "@end_frame"})

    params: dict = {
        "model": model,
        "prompt": prompt,
        "duration": int(round(shot["duration"])),
        "aspect_ratio": proj.get("aspect_ratio", "16:9"),
        "count": int(shot.get("variants", proj.get("variants_per_shot", 2))),
    }
    if model in ("seedance_2_5", "cinematic_studio_video_4_0", "seedance_2_0"):
        params["resolution"] = proj.get("resolution", "720p")
        params["generate_audio"] = bool(proj.get("generate_sfx", True))
    if VIDEO_MODELS.get(model, {}).get("has_mode"):
        params["mode"] = "omni_reference" if (medias or "<<<" in prompt) else "t2v"
    if proj.get("higgsfield_folder_id"):
        params["folder_id"] = proj["higgsfield_folder_id"]
    if medias:
        params["medias"] = medias
    return params


def build_asset_prompt(proj: dict, aid: str) -> str:
    a = proj["assets"][aid]
    kind = a["type"]
    tpl_file = TEMPLATES / f"{'location' if kind == 'lighting' else kind}_sheet.txt"
    tpl = tpl_file.read_text(encoding="utf-8")
    style = proj.get("style", {})
    asset_style = a.get("style") or (
        style.get("character_style") if kind == "character"
        else style.get("background_style") if kind in ("location", "lighting")
        else style.get("prop_style")
    ) or style.get("look", "")
    return tpl.format(
        name=a.get("name", aid),
        description=a.get("description", "").strip(),
        personality=a.get("personality", ""),
        style=asset_style,
        lighting=style.get("lighting", ""),
        palette=style.get("palette", ""),
    ).strip() + "\n"


def mcp_params(params: dict) -> dict:
    """Strip our private keys before handing params to the MCP tool."""
    clean = dict(params)
    if "medias" in clean:
        clean["medias"] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in clean["medias"]]
    return clean


# ----------------------------------------------------------------------- media
def ffprobe_json(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in ffprobe_json(path).get("streams", []))


def frame_size(aspect: str, resolution: str) -> tuple[int, int]:
    short = int(re.sub(r"\D", "", resolution) or 720)
    if resolution.lower() in ("4k", "2160p"):
        short = 2160
    w, h = (int(x) for x in aspect.split(":"))
    if w >= h:
        return 2 * round(short * w / h / 2), short
    return short, 2 * round(short * h / w / 2)


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise PipelineError(f"command failed: {' '.join(cmd)}\n{r.stderr[-2000:]}")


def normalize_clip(src: Path, dst: Path, w: int, h: int, fps: int,
                   t_in: float | None, t_out: float | None) -> None:
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if t_in:
        cmd += ["-ss", str(t_in)]
    if t_out:
        cmd += ["-to", str(t_out)]
    cmd += ["-i", str(src)]
    if has_audio(src):
        cmd += ["-map", "0:v:0", "-map", "0:a:0"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", str(dst)]
    run(cmd)


def placeholder_clip(dst: Path, w: int, h: int, fps: int, dur: float) -> None:
    run(["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=0x404040:s={w}x{h}:r={fps}:d={dur}",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-ac", "2", str(dst)])


def join_seconds(proj: dict, shot: dict, default: float) -> float:
    """Crossfade length into this shot: per-shot transition_in, else project/CLI default."""
    if shot.get("transition_in") is not None:
        return float(shot["transition_in"])
    return float(proj.get("xfade", default))


def xfade_join(parts: list[Path], joins: list[float], out: Path) -> None:
    """Join clips with video+audio crossfades. joins[i] is the overlap into parts[i] (joins[0] unused)."""
    durs = [float(ffprobe_json(p)["format"]["duration"]) for p in parts]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for p in parts:
        cmd += ["-i", str(p)]
    vf, af = [], []
    vlast, alast, t = "[0:v]", "[0:a]", durs[0]
    for i in range(1, len(parts)):
        d = max(0.0, min(joins[i], durs[i - 1] / 2, durs[i] / 2))
        vo, ao = f"[v{i}]", f"[a{i}]"
        if d > 0:
            vf.append(f"{vlast}[{i}:v]xfade=transition=fade:duration={d:.3f}:offset={t - d:.3f}{vo}")
            af.append(f"{alast}[{i}:a]acrossfade=d={d:.3f}{ao}")
        else:
            vf.append(f"{vlast}[{i}:v]concat=n=2:v=1:a=0{vo}")
            af.append(f"{alast}[{i}:a]concat=n=2:v=0:a=1{ao}")
        vlast, alast, t = vo, ao, t + durs[i] - d
    cmd += ["-filter_complex", ";".join(vf + af), "-map", vlast, "-map", alast,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-b:a", "192k", str(out)]
    run(cmd)


# -------------------------------------------------------------------- commands
def cmd_init(args) -> None:
    dst = ROOT / "projects" / slugify(args.name)
    if dst.exists():
        raise PipelineError(f"{dst} already exists")
    shutil.copytree(PROJECT_TEMPLATE, dst)
    proj = load(dst)
    proj["title"] = args.name
    save(dst, proj)
    print(f"created {dst.relative_to(ROOT)}")
    print("next: put character images in characters/, write script.md, then ask Claude to run the make-film skill")


def cmd_check(args) -> None:
    pdir = project_dir(args.project)
    errors, warnings = validate(load(pdir), pdir)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR:   {e}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    if errors:
        sys.exit(1)


def cmd_asset_prompt(args) -> None:
    pdir = project_dir(args.project)
    proj = load(pdir)
    ids = [args.asset] if args.asset else list(proj.get("assets", {}))
    for aid in ids:
        if aid not in proj["assets"]:
            raise PipelineError(f"unknown asset '{aid}'")
        text = build_asset_prompt(proj, aid)
        out = pdir / "prompts" / f"asset_{aid}.txt"
        out.parent.mkdir(exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"== {aid} -> {out.relative_to(pdir)}")
        if args.print:
            print(text)


def cmd_prompt(args) -> None:
    pdir = project_dir(args.project)
    proj = load(pdir)
    errors, _ = validate(proj, pdir)
    if errors and not args.force:
        raise PipelineError("project has errors, run `check` (or pass --force):\n  " + "\n  ".join(errors))
    shots = [find_shot(proj, args.shot)] if args.shot else proj.get("shots", [])
    (pdir / "prompts").mkdir(exist_ok=True)
    batch = []
    for s in shots:
        prompt = build_shot_prompt(proj, s)
        params = build_request(proj, s, prompt)
        (pdir / "prompts" / f"{s['id']}.txt").write_text(prompt, encoding="utf-8")
        with open(pdir / "prompts" / f"{s['id']}.request.json", "w", encoding="utf-8") as f:
            json.dump(mcp_params(params), f, indent=2, ensure_ascii=False)
        batch.append({"shot": s["id"], "params": mcp_params(params)})
        print(f"== {s['id']} [{s.get('route', 't2v')}] {params['model']} {params['duration']}s "
              f"-> prompts/{s['id']}.request.json")
        if args.print:
            print(prompt)
    if not args.shot:
        with open(pdir / "prompts" / "batch.json", "w", encoding="utf-8") as f:
            json.dump(batch, f, indent=2, ensure_ascii=False)


def cmd_take(args) -> None:
    pdir = project_dir(args.project)
    proj = load(pdir)
    shot = find_shot(proj, args.shot)
    takes = shot.setdefault("takes", [])
    if args.action == "add":
        n = len(takes) + 1
        take = {"n": n, "job_id": args.job, "url": args.url, "note": args.note or ""}
        if args.file:
            src = Path(args.file)
            dst = pdir / "takes" / f"{shot['id']}_t{n}{src.suffix or '.mp4'}"
            dst.parent.mkdir(exist_ok=True)
            shutil.copy(src, dst)
            take["file"] = str(dst.relative_to(pdir))
        elif args.url:
            dst = pdir / "takes" / f"{shot['id']}_t{n}.mp4"
            dst.parent.mkdir(exist_ok=True)
            urllib.request.urlretrieve(args.url, dst)
            take["file"] = str(dst.relative_to(pdir))
        takes.append(take)
        print(f"{shot['id']}: added take {n}" + (f" -> {take['file']}" if take.get("file") else ""))
    elif args.action == "approve":
        match = [t for t in takes if t["n"] == args.n]
        if not match:
            raise PipelineError(f"{shot['id']} has no take {args.n}")
        if not match[0].get("file"):
            raise PipelineError(f"{shot['id']} take {args.n} has no local file; add it with --url or --file")
        shot["approved_take"] = args.n
        if args.t_in is not None:
            shot["trim_in"] = args.t_in
        if args.t_out is not None:
            shot["trim_out"] = args.t_out
        print(f"{shot['id']}: approved take {args.n}")
    elif args.action == "note":
        for t in takes:
            if t["n"] == args.n:
                t["note"] = args.note or ""
        print(f"{shot['id']}: noted take {args.n}")
    save(pdir, proj)


def cmd_status(args) -> None:
    pdir = project_dir(args.project)
    proj = load(pdir)
    print(f"# {proj.get('title', pdir.name)}  ({proj.get('aspect_ratio', '16:9')}, {proj.get('resolution', '720p')})")
    print("\nASSETS")
    for aid, a in proj.get("assets", {}).items():
        ref = a.get("element_id") or a.get("media_id") or "-"
        print(f"  {'[x]' if a.get('locked') else '[ ]'} {aid:<16} {a.get('type', ''):<10} ref={ref}")
    print("\nSHOTS")
    total = approved_dur = 0.0
    for s in proj.get("shots", []):
        total += s.get("duration", 0)
        has_prompt = (pdir / "prompts" / f"{s['id']}.request.json").exists()
        appr = s.get("approved_take")
        if appr:
            approved_dur += s.get("duration", 0)
        print(f"  {'[x]' if appr else '[ ]'} {s['id']:<6} {s.get('route', 't2v'):<8} {s.get('duration', 0):>4}s "
              f"prompt={'y' if has_prompt else 'n'} takes={len(s.get('takes', []))} approved={appr or '-'}")
    print(f"\nrunning time {total:.0f}s, approved {approved_dur:.0f}s")


def cmd_assemble(args) -> None:
    pdir = project_dir(args.project)
    proj = load(pdir)
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise PipelineError(f"{tool} not found on PATH")
    w, h = frame_size(proj.get("aspect_ratio", "16:9"), args.resolution or proj.get("resolution", "720p"))
    fps = int(proj.get("fps", 24))
    work = pdir / "final" / "_work"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    missing = []
    for s in proj.get("shots", []):
        take = next((t for t in s.get("takes", []) if t["n"] == s.get("approved_take")), None)
        part = work / f"{s['id']}.mp4"
        if take and take.get("file"):
            normalize_clip(pdir / take["file"], part, w, h, fps, s.get("trim_in"), s.get("trim_out"))
        elif args.placeholders:
            placeholder_clip(part, w, h, fps, s.get("duration", 4))
            missing.append(s["id"])
        else:
            missing.append(s["id"])
            continue
        parts.append(part)
    if missing and not args.placeholders:
        raise PipelineError(f"shots without an approved take: {', '.join(missing)} (use --placeholders for an animatic)")
    if not parts:
        raise PipelineError("nothing to assemble")

    cut = work / "cut.mp4"
    joins = [join_seconds(proj, s, args.xfade) for s in proj.get("shots", []) if s["id"] not in missing or args.placeholders]
    if any(joins[1:]):
        xfade_join(parts, joins, cut)
    else:
        listfile = work / "concat.txt"
        listfile.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(cut)])

    out = Path(args.out) if args.out else pdir / "final" / f"{slugify(proj.get('title', 'film'))}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    music = args.music or proj.get("music")
    if music:
        mpath = Path(music) if Path(music).is_absolute() else pdir / music
        vol = args.music_volume
        run(["ffmpeg", "-y", "-v", "error", "-i", str(cut), "-stream_loop", "-1", "-i", str(mpath),
             "-filter_complex",
             f"[1:a]volume={vol},afade=t=in:d=1[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,"
             f"loudnorm=I=-16:TP=-1.5:LRA=11[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)])
    else:
        run(["ffmpeg", "-y", "-v", "error", "-i", str(cut), "-c:v", "copy",
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", str(out)])
    dur = float(ffprobe_json(out)["format"]["duration"])
    print(f"final: {out} ({dur:.1f}s, {w}x{h}@{fps})")
    if missing:
        print(f"placeholders used for: {', '.join(missing)}")


# ------------------------------------------------------------------------- cli
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="hixpipe", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a project from the template")
    p.add_argument("name")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("check", help="validate project.json")
    p.add_argument("project")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("asset-prompt", help="build sheet prompts for assets")
    p.add_argument("project")
    p.add_argument("asset", nargs="?")
    p.add_argument("--print", action="store_true")
    p.set_defaults(fn=cmd_asset_prompt)

    p = sub.add_parser("prompt", help="build 5-block shot prompts + request JSON")
    p.add_argument("project")
    p.add_argument("--shot")
    p.add_argument("--print", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_prompt)

    p = sub.add_parser("take", help="record / approve generated takes")
    p.add_argument("action", choices=["add", "approve", "note"])
    p.add_argument("project")
    p.add_argument("shot")
    p.add_argument("--n", type=int, help="take number (approve/note)")
    p.add_argument("--url", help="result URL to download (add)")
    p.add_argument("--file", help="local video file (add)")
    p.add_argument("--job", help="Higgsfield job id (add)")
    p.add_argument("--note")
    p.add_argument("--in", dest="t_in", type=float, help="trim start seconds (approve)")
    p.add_argument("--out", dest="t_out", type=float, help="trim end seconds (approve)")
    p.set_defaults(fn=cmd_take)

    p = sub.add_parser("status", help="progress overview")
    p.add_argument("project")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("assemble", help="edit approved takes into the final video")
    p.add_argument("project")
    p.add_argument("--music", help="music/score file mixed under the SFX")
    p.add_argument("--music-volume", type=float, default=0.25)
    p.add_argument("--resolution", help="override output resolution, e.g. 1080p")
    p.add_argument("--placeholders", action="store_true", help="gray cards for unapproved shots (animatic)")
    p.add_argument("--xfade", type=float, default=0.0, help="crossfade seconds at every join (0 = hard cuts)")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_assemble)

    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except PipelineError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
