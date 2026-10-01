---
name: asset-sheet
description: Turn a short request ("a watercolor drawing of an old yellow taxi, 3/4 front view") into a full image prompt for a character sheet, prop sheet, location painting or FX sheet that matches the project style bible. Use in the asset stage of the make-film pipeline.
---

# Asset sheet prompts

Start from `python3 pipeline/hixpipe.py asset-prompt <project> <asset> --print` (built from
`pipeline/templates/*_sheet.txt` + the project `style`), then refine it with these rules.

## Every sheet prompt covers

- **Subject**: what it is, one sentence.
- **Design**: shapes, proportions, outfit/material, colors, the 2-3 details that make it
  recognizable (ginger hair vs blue hoodie; cap + huge mustache).
- **Personality in the design**: how it should feel (cute but cool; friendly and very
  pleased with himself). Comedy has to read in the design as well as the acting.
- **Pose & framing**: characters - full-body turnaround (front, 3/4, side, back) +
  expressions; props - 3/4 front main view + side/back; locations - wide view with room
  for action.
- **Lighting**: characters/props - even neutral studio light, plain background (so the
  sheet carries design, not mood); locations - the film's lighting formula (golden hour).
- **Style**: from the style bible (`character_style`, `prop_style`, `background_style`).
- **Exclusions**: no text, no extra characters, no other objects.

## Style lessons

- Moving characters/props: clean stylized 3D, light texture. Painted texture on moving
  objects swims in video.
- Backgrounds: painterly, but clean edges - pure watercolor tests came out sloppy, dirty
  and soulless; lighting fixed most of it.
- Literal words: describe the shape you want, not a thing it resembles.
- Generate `count: 4`, compare, combine the best parts (e.g. hoodie from v1, hair from v3)
  with an edit model, then hand-finish (saturation, painted strokes around the silhouette)
  for the hybrid look.

## Models

- New design: `soul_2` (characters, props), `soul_location` / `soul_2` (locations).
- Keep the user's existing character, only reformat it into a sheet: `nano_banana_pro`
  or `gpt_image_2_5` with the original as `image_references`.
- Variants of a locked asset (roofless car, interior, other outfit): `nano_banana_pro`
  / `seedream_v5_pro` edit with the locked image as reference.
