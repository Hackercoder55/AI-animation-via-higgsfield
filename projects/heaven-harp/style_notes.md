# Style notes / lessons

Lessons from the test stage become rules here, and the important ones are copied into
`project.json -> style.rules` or `locks` so every prompt carries them.

- 
- Test stage (480p): start frames are honored (~0.92 similarity), end frames well in Heaven (0.84-0.89), weaker in hospital (0.71).
- Over-the-shoulder framing made the model draw the narrator twice (blurred shoulder + in bed). Never ask for an over-the-shoulder of a character who is also visible; lock: every character appears once.
- Voice model drops sentences after quoted dialogue and drags on ALL-CAPS words: feed narration without quote marks or caps, then verify every take with Whisper.
