# open-podcast-kit

Claude Code skills for interview podcasts: guest research, interview prep cards, outreach messages, loudness correction and final-cut QC. This file holds instructions for coding agents working on this repository; `CLAUDE.md` is a link to it.

## Layout

- `skills/<name>/SKILL.md` plus optional `references/` and `scripts/`; scripts are standalone Python 3.9+ with no third-party dependencies except optional Playwright (PDF export) and ffmpeg on the PATH.
- `lib/kitconf.py` loads the user's `kit.toml` over `kit.example.toml`; every show-specific value comes from there, never hard-coded in a skill or script.
- `presets/<format>/question-bank.md` holds question banks; `examples/` holds fictional demo material only.

## Rules

- Never add real guest names, real résumés, real transcripts or a real show's private data; examples must be fictional and say so.
- Text that goes to a guest (the outline section and the pre-interview message) must stay free of internal tactic words; `check_prep_card.py` enforces this, so extend its word list rather than working around it.
- Loudness changes are static gain plus a limiter; never introduce dynamic `loudnorm` processing.
- Run `python3 -m pytest tests` before committing, and keep the demo prep card at 0 FAIL / 0 WARN.
