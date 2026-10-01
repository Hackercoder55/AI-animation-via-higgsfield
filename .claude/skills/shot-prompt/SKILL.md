---
name: shot-prompt
description: System prompt for writing AI video shot prompts in the 5-block structure (scene context & style, active references, shot structure, locks & constraints, animation principles). Use when writing, reviewing or fixing a video generation prompt for a shot in projects/*/project.json.
---

# Shot prompt system prompt

`pipeline/hixpipe.py prompt` builds this structure automatically from the shot fields.
Use this skill to write those fields well, or to hand-tune a prompt for a hard shot.

Why long prompts: every detail you don't write, the model decides for you - and it is a
terrible guesser. Why order matters: the model reads top to bottom and follows the first
~20% most strictly, so the most important information goes first.

## The 5 blocks (always in this order)

1. **SCENE CONTEXT & STYLE** - what happens in the shot, in plain sentences; then style
   rules and world physics. 2-4 sentences of context, max.
2. **ACTIVE REFERENCES** - a call sheet. Each attached image/video gets a handle and a role:
   `@maya = Maya (character): main character. Personality: frantic, determined`.
   Personality and role only, **never visual description** - that is what the images are for
   (text descriptions fight the image). End with:
   `Characters, environments and props 100% match the reference.`
   Video reference: "follow ONLY its motion, timing and camera; ignore its gray look".
3. **SHOT STRUCTURE** - storyboard panel in words. Hard cuts listed as separate shots.
   Beat by beat with timing: what happens first, next, how long each pose holds.
   One clear action per beat. Name the camera (framing, angle, move).
4. **LOCKS & CONSTRAINTS** - rules the model must follow strictly. Always:
   `No music. SFX and ambience only.` (music is added in post). Add continuity locks
   (seats, accessories, order of events: "lands only after it has fully cleared the trucks").
5. **ANIMATION PRINCIPLES** - the 12 principles, and the specific ones that matter for the
   shot (anticipation before the jump, squash on landing, follow-through on hair/hoodie).

## Writing rules

- Write in English, present tense, concrete verbs. No "maybe", no lists of alternatives.
- Use the asset names consistently (same handle every time).
- Prefer words the model can't misread: "nuclear blast" not "mushroom-shaped explosion".
- Durations: beats must add up to the shot duration.
- For gags: give the reaction its own timed beat (the pause is what sells it).
- Don't stack two dense textures (painted prop on painted background).
- Keep the person count explicit: "only Maya and the Driver are in the shot".

## Review checklist before generating

- [ ] First two lines alone tell what the shot is
- [ ] Every visible character/prop/location is an attached reference with a role
- [ ] No visual descriptions of referenced assets
- [ ] Beats are timed and add up
- [ ] Locks cover the things that broke in earlier takes
- [ ] "No music, SFX only" present
