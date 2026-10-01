# AI animation via Higgsfield

Asset-first AI animation pipeline: **script + character images -> finished video**.

- Orchestration: `.claude/skills/make-film/SKILL.md` - follow it stage by stage whenever the
  user asks to make a film/video from a script, or names a project in `projects/`.
- Prompt writing: `.claude/skills/shot-prompt/` (video shots), `.claude/skills/asset-sheet/` (image sheets).
- CLI: `python3 pipeline/hixpipe.py --help` (stdlib only; ffmpeg for `assemble`).
- Generation goes through the Higgsfield MCP tools (`mcp__Higgsfield__*`, load via ToolSearch).
- State: `projects/<name>/project.json` is the single source of truth - update it after every
  generation/approval so work can resume in a new session.
- Tests: `python3 -m unittest discover -s tests`.

Conventions
- Never spend credits without telling the user the estimated cost first (`get_cost: true`).
- Never alter a character design the user supplied; only normalize it into a sheet.
- Video prompts are SFX-only (no music); music/VO are added in `assemble`.
- Don't commit generated videos/images (see .gitignore); commit project.json, prompts and notes.
