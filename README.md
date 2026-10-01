# AI Animation via Higgsfield - Script + Characters -> Final Video

Ye repo "Passport Rush" (Hixled Animation) wale workflow ko ek repeatable pipeline bana deta hai.
Tum **script** aur apni site ke **character images** do, Claude Code + Higgsfield baaki kaam karke
**final video** deta hai.

## Quick start (Hinglish)

1. Is repo ko Claude Code mein kholo (Higgsfield connector connected hona chahiye).
2. Bolo:
   > "Naya project banao *My Film*. Script ye hai: ... Characters ye hain: https://mysite.com/hero.png, https://mysite.com/villain.png. 16:9, ~60 sec."
3. Claude `make-film` skill follow karega aur har gate pe tumse approve karwayega:
   shot list -> character/location/prop sheets -> test shots -> saare shots -> final video.
4. Final video: `projects/<film>/final/<film>.mp4`

## Pipeline

```
 script.md + character images (site URLs / files)
        |
 [0] Intake        URLs -> Higgsfield media (media_import_url)
 [1] Breakdown     script -> shots (4-10s), har shot ka route:
                     t2v      = simple shot, text + image refs
                     previs   = complex motion/camera -> gray 3D previs video as reference
                     keyframe = exact framing -> start image
 [2] Style bible   look, lighting formula (golden hour), physics, rules
 [3] ASSET FIRST   character / location / prop / FX sheets  (soul_2, nano_banana_pro)
                   -> review -> hand touch-ups -> lock as Higgsfield reference elements
 [4] Test stage    2-3 cheap drafts -> lessons -> new rules/locks
 [5] Previs        Blender gray render (or Higgsfield 3D scene builder) -> video reference
 [6] Shots         5-block prompts -> seedance_2_5 (omni_reference) -> review -> approve
 [7] Post          ffmpeg assemble + music/VO + loudness -> optional upscale -> FINAL.mp4
```

### 5-block shot prompt (order matters - first 20% matters most)

1. **Scene context & style** - kya ho raha hai + style rules + world physics
2. **Active references** - har image/video ka role & personality (visual description nahi)
   + "Characters, environments and props 100% match the reference."
3. **Shot structure** - beat by beat, timing ke saath (storyboard in words)
4. **Locks & constraints** - "No music, SFX only", no extra people, continuity rules
5. **Animation principles** - 12 principles (squash & stretch, anticipation, follow-through...)

### Lessons baked in

- Moving characters/props = clean 3D; painted/watercolor texture sirf background mein.
- Golden-hour lighting (low warm sun, long shadows) -> depth; midday = flat.
- Model previs nahi samjha -> camera zoom out karo.
- Camera har take mein badal raha -> achhe take ka screenshot keyframe banao; check karo ki
  screenshot character sheet se match kare (headphones wala lesson).
- Random log aa rahe -> real characters ko shot mein add karo.
- Subtle acting ("performance gap") hard hai -> shot split karo / keyframes / reaction close-up.

## CLI

```bash
python3 pipeline/hixpipe.py init "My Film"              # new project from template
python3 pipeline/hixpipe.py check my-film                # validate
python3 pipeline/hixpipe.py asset-prompt my-film --print # sheet prompts for all assets
python3 pipeline/hixpipe.py prompt my-film               # 5-block prompts + generate_video params
python3 pipeline/hixpipe.py take add my-film S01 --url <video_url> --job <job_id>
python3 pipeline/hixpipe.py take approve my-film S01 --n 2 --in 0.3 --out 4.8
python3 pipeline/hixpipe.py status my-film
python3 pipeline/hixpipe.py assemble my-film --placeholders            # animatic
python3 pipeline/hixpipe.py assemble my-film --music final/score.mp3   # final
```

`projects/passport-rush-demo/` is a worked example (taxi sequence: t2v, keyframe and previs
shots). Run `python3 pipeline/hixpipe.py prompt passport-rush-demo --print` to see the prompts.

## Layout

```
.claude/skills/make-film     end-to-end orchestration (stages + gates + troubleshooting)
.claude/skills/shot-prompt   5-block video prompt system prompt
.claude/skills/asset-sheet   character/prop/location/FX sheet prompts
pipeline/hixpipe.py          CLI (stdlib only, ffmpeg for assemble)
pipeline/templates/          sheet prompt templates
projects/_template/          new-project skeleton
projects/<film>/             project.json, script.md, characters/, assets/, previs/, prompts/, takes/, final/
tests/                       unittest suite
```

## Requirements

- Claude Code with the Higgsfield connector (credits on your Higgsfield account)
- Python 3.10+, ffmpeg/ffprobe
- Optional: Blender for previs shots
