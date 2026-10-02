# Style notes / lessons

Lessons from the test stage become rules here, and the important ones are copied into
`project.json -> style.rules` or `locks` so every prompt carries them.

- 
- Test stage (480p): start frames are honored (~0.92 similarity), end frames well in Heaven (0.84-0.89), weaker in hospital (0.71).
- Over-the-shoulder framing made the model draw the narrator twice (blurred shoulder + in bed). Never ask for an over-the-shoulder of a character who is also visible; lock: every character appears once.
- Voice model drops sentences after quoted dialogue and drags on ALL-CAPS words: feed narration without quote marks or caps, then verify every take with Whisper.

## Flow cut (v4) lessons
- Voice-over only: no SFX/music in the mix; shot audio is dropped in `sandbox_flow_cut.py`.
- Narration is the master clock: pauses squeezed to <=0.22s, chunks laid end to end; each shot is
  trimmed (after <=1.12x speed-up) or slowed with motion interpolation (>=0.85x) to fit its words.
- Joins are camera moves (zoom-through / whip pan with blur), white flash only Heaven -> hospital.
- Prop/costume pop-in: the S13 keyframe had the surgeon without her cap; the omni reference
  (with cap) made it pop in mid-shot. Fix the KEYFRAME to match the asset first, then add a
  "wears X in every frame" lock. Check with a per-frame colour probe (teal top-of-head).
