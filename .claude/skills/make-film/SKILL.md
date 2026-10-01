---
name: make-film
description: End-to-end AI animation pipeline on Higgsfield - takes a script plus character images (files or URLs from the user's site) and drives breakdown, asset-first design, test stage, previs, shot generation, review and final assembly into one finished video. Use when the user says "make the film", "script + characters -> video", "run the pipeline", or names a project under projects/.
---

# make-film: script + characters -> final video

This is the Hixled "Passport Rush" pipeline turned into a repeatable process.
The one rule everything rests on: **asset first** - the quality and consistency of the
image inputs (character, prop, location sheets) decides the quality of the film.

Tools:
- `python3 pipeline/hixpipe.py ...` - bookkeeping, prompts, final edit (see `--help`).
- Higgsfield MCP tools (`mcp__Higgsfield__*`) - every image/video generation.
  Load them with ToolSearch (`select:mcp__Higgsfield__generate_video,...`) before calling.
- Project state lives in `projects/<name>/project.json`. Update it after every step,
  so the run can be resumed in a new session.

Work through the stages in order. Stop at every **GATE** and show the user what was
made; continue only once they approve (or tell you to run without gates).

---

## Stage 0 - Intake

1. If the project doesn't exist: `python3 pipeline/hixpipe.py init "<Title>"`.
2. Script -> `projects/<p>/script.md` (any format; Hindi/Hinglish fine, prompts are written in English).
3. Characters from the user's site:
   - **URLs** (preferred): `mcp__Higgsfield__media_import_url` for each -> `media_id`.
   - **Local files** in `characters/`: upload with `mcp__Higgsfield__media_upload`
     (+ PUT bytes with curl + `media_confirm`), or `media_upload_widget` in the Higgsfield app.
   - Record each character as an asset in project.json: `type: character`, `name`, `role`,
     `personality` (acting traits, not looks), `description` (looks, for the sheet prompt),
     `source_files` / `source_url`, `media_id`.
4. Ask only for what is truly missing: aspect ratio (16:9 vs 9:16), target length,
   style if the user has none (default: stylized 3D characters + watercolor backgrounds,
   golden-hour lighting), and credit budget.
5. Check credits: `mcp__Higgsfield__balance`. Rough estimate: assets ~4 images each,
   shots ~2-3 takes each.

## Stage 1 - Breakdown (script -> storyboard in words)

Turn the script into `shots` in project.json. Rules:
- 1 shot = one continuous action, **4-10 s** (max 15 s; 30 s only on seedance_2_5).
- `context`: what happens, in plain sentences (this becomes the top 20% of the prompt).
- `beats`: timed actions `{"t": "0-1.5s", "action": "..."}` - what first, what next, holds.
- `camera`: framing + move. `sfx`: sounds. `acting`: performance notes.
- `assets`: ids of every character/prop/location visible in the shot. Every person who
  appears MUST be an asset in the shot, or the model invents random people.
- `route` (the "orange marks" of the storyboard):
  - `previs` - complex movement, specific camera, or anything quicker to animate than to
    describe (stunts, vehicles, choreography). Needs a gray 3D previs video.
  - `keyframe` - framing must be exact / continuity with a previous shot. Needs a start image.
  - `t2v` - everything simpler. Text + image references only.
- Plan story beats, not every frame; leave some shots up to chance.
- Dialogue: put spoken lines in beats as `Maya says: "..."` (seedance/kling generate speech
  with `generate_audio`); or add VO later in post.

Run `hixpipe.py check <p>` and fix errors.
**GATE 1:** show the shot list as a table (id, route, duration, action summary).

## Stage 2 - Style bible

Fill `style` in project.json: `look`, `character_style`, `background_style`, `prop_style`,
`lighting`, `physics`, `palette`, `rules`. Proven defaults (lessons from Passport Rush):
- Characters and moving props: **clean stylized 3D, light texture**. Heavy painted texture on
  moving objects looks like a PNG stretched over geometry, and painted-on-painted doubles
  the load on the model.
- Painted/watercolor texture belongs to the **background** only. Background-only props
  (on screen briefly) may stay painted.
- Lighting formula: **late-afternoon golden hour, low warm sun, long harsh shadows**. Midday
  light looks flat and dull.
- Saturated, bright palette for comedy.

## Stage 3 - Assets (asset-first)

For every asset, in this order: main characters -> secondary characters -> locations -> props
that recur across shots -> FX. Only build assets for things that must look consistent across
shots; one-off background stuff can come from the prompt alone.

**Characters from the user's site**
- If the user image is already a clean sheet (full body, plain background): use it as is.
- Otherwise make a turnaround sheet that keeps their design:
  `generate_image` with `model: nano_banana_pro` (or `gpt_image_2_5`),
  `medias: [{value: <media_id>, role: image_references}]`, prompt from
  `hixpipe.py asset-prompt <p> <id> --print` plus "keep this exact character design".
  `count: 4`, aspect `16:9`.
- Never change a design the user gave you; only normalize it into a sheet.

**New characters / locations / props / FX**
- `hixpipe.py asset-prompt <p> <id> --print` -> refine with the `asset-sheet` skill.
- Characters/props: `model: soul_2`; locations: `soul_2` or `soul_location`; `count: 4`.
- Variants of one asset (roofless car, interior view): edit the locked image with
  `nano_banana_pro` / `seedream_v5_pro` + image_references.
- Use `generate_image_batch` for several independent assets, then `jobs_wait`, then one
  `show_generation_by_ids`.

**Review every asset**: same design in every view, readable silhouette, fits the world,
fits the style rules. Pick one, or iterate. Hand touch-ups (brightness/saturation, painted
strokes around silhouettes) are encouraged - the user can edit in Photoshop and give the
file back.

**Lock**: save the chosen image as a reference element
(`manage_reference_elements action=create`, category matching the type, name = asset id)
and write `element_id` (preferred) or `media_id` into the asset, then `locked: true`.
Save a local copy to `assets/<id>.png` when possible.
**GATE 2:** show all locked assets side by side.

## Stage 4 - Test stage (before full production)

Pick 2-3 representative shots (one per route if possible) and generate cheap drafts
(`resolution: 480p`, `count: 1`). Look for: style drift (photoreal car in a painted
world), random extra people, flat light, broken physics. Write each lesson in
`style_notes.md` and promote it into `style.rules` or `locks` so every prompt carries it.
Re-lock assets if a test proves a design doesn't hold up in motion.
**GATE 3:** summarize lessons and the rule changes.

## Stage 5 - Previs (route = previs only)

- The user's Blender gray preview (no colors/materials: gray geo + motion + camera) goes to
  `previs/<shot>.mp4`, or build one with the Higgsfield 3D scene builder
  (`scene_builder_3d_*` tools) when the user has no 3D artist.
- Camera rule: **if the model doesn't understand your reference, you can't see enough of it -
  zoom out.** Close-ups of untextured gray shapes confuse the model.
- Add squash-and-stretch / anticipation in the previs animation itself.
- Upload -> `previs_media_id` on the shot.

## Stage 6 - Shot generation

1. `python3 pipeline/hixpipe.py prompt <p>` -> `prompts/<shot>.txt` (5-block prompt) and
   `prompts/<shot>.request.json` (ready `generate_video` params). Read each prompt; tighten
   wording with the `shot-prompt` skill if needed, and save it back into the shot fields
   (not only the txt) so it stays reproducible.
2. Preflight cost: one `generate_video` call with `get_cost: true`; tell the user the total.
3. Generate: `generate_video_batch` (2-12 requests per call) using the request JSONs,
   then `jobs_wait`, then `show_generation_by_ids`.
4. Record every take: `hixpipe.py take add <p> <shot> --url <result_url> --job <job_id>`.
5. Review each take against previs/storyboard: timing, camera, design match
   (outfit, accessories, colors), no extra people, physics reads, the gag lands.
6. `hixpipe.py take approve <p> <shot> --n <k> [--in s --out s]`, or fix and regenerate:

| Problem | Fix |
|---|---|
| Model ignores previs / misplaces objects | Re-render previs with the camera pulled back |
| Camera angle changes every take | Screenshot the good take, use it as keyframe (`route: keyframe`) or extra reference |
| Detail disappears (headphones, logo) | Check every reference image shows it; repaint the screenshot to match the sheet |
| Random extra people | Add the real characters to the shot assets; keep the "no extra people" lock |
| Prop/character turns photoreal or texture swims | Cleaner 3D asset, lighter texture; repeat the style rule in the first lines |
| A word is taken literally ("mushroom explosion") | Rephrase ("nuclear blast"), or hand-paint the FX sheet |
| Ordering breaks (lands before clearing trucks) | Add an explicit lock: "X happens only after Y" |
| Subtle acting / pauses don't land (performance gap) | Split into 2 shorter shots with a cut, use start_image + end_image keyframes, or move the acting beat into a reaction close-up |

Max ~4 rounds per shot; if a shot still fails, simplify the shot or change the staging and
tell the user (the "performance gap" is a known limit).
**GATE 4:** all shots approved - show `hixpipe.py status <p>`.

## Stage 7 - Post & final

1. Rough cut / animatic any time: `hixpipe.py assemble <p> --placeholders`.
2. Music: generated videos are SFX-only on purpose. Add a score with
   `mcp__Higgsfield__generate_audio` or a user file, then
   `hixpipe.py assemble <p> --music final/score.mp3 --music-volume 0.25`.
3. Optional voice-over: `generate_audio` per line, mixed in the same way, or
   `sync_so` for lip-sync on a shot.
4. Optional upscale of the final: `upscale_video` / `topaz_video` (1080p/4K).
5. Deliver `projects/<p>/final/<title>.mp4`: send it to the user (SendUserFile), commit
   project.json/prompts (not the heavy video files) and push.
