# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A desktop app that computes the characteristic crack width `w_k` of a reinforced-concrete
section to **EN 1992-1-1 cl. 7.3.4** and checks it against a limit. NiceGUI + pywebview
front end, SQLite storage, PDF export, shipped as a portable one-dir PyInstaller build.

## Commands

```bash
uv sync                                   # install deps into .venv
uv run python main_niceGUI.py             # dev: browser tab at http://localhost:8082, hot reload
uv run pytest                             # engine regression suite
uv run pytest tests/test_creep.py -k creep_reaches   # a single test / pattern
uv run ruff format .                      # format (defaults: 88 cols, double quotes — no [tool.ruff] section exists)
uv run python build_user_guide.py         # regenerate docs/CrackWidth_User_Guide.pdf
uv run pyinstaller --noconfirm --clean CrackWidthNiceGUI.spec   # -> dist/CrackWidthNiceGUI/
```

Releases (version bump, changelog sync, build, zip) have their own procedure — use the
`rebuild` skill in `.claude/skills/rebuild/`, don't improvise the steps.

## Architecture

### The engine is pure; everything else is a caller

`WieconTools/crack_width_formula.py` has no UI, no I/O, no globals, no randomness:
`crack_analyze(geometry + materials).run(N_kN, M_kNm, w_max)` → a `report_result`
dataclass carrying *every* intermediate of the check, not just `wk`. The section and the
loads are split across the constructor and `run()` on purpose — one section gets checked
against several load cases.

Two traps in this file:

- **The constructor takes the OPPOSITE face before the tension face.** Positional args
  silently swap the two faces and return a plausible wrong answer. Always call by keyword.
- **`run()` executes nine numbered steps, and there is no `step_6`** — steps 5 and 6 are
  one method, `step_5_6_effective_area`.

`tests/test_creep.py` pins the "Wadi" benchmark (α_e 5.88, x 25.1 mm, σ_s 395.7 MPa,
ρ_p,eff 1.12 %, s_r,max 565 mm, w_k 0.678 mm) plus creep monotonicity over randomised
sections. Re-run it after touching the engine — those six numbers were verified against an
independent tool and are the only thing standing between a refactor and a wrong answer.
Deliberate deviations from EC2 (`k_t` pinned at 0.4 for both durations; `cracked`
computed but never acted on) are documented in the module docstring and in
`docs/Crack_Width_Technical_Briefing.html`; don't "fix" them without reading those.

### One shared calculation core

`collect_inputs_and_run_calculation(values)` in `main_niceGUI.py` is the single path from
a form/CSV dict to a result: it copies the dict, pops `LOAD_KEYS` (`N_kN`, `M_kNm`,
`w_max`) into `run()`, and passes the rest to the constructor. It holds no UI and catches
nothing — it raises, and each caller picks its own policy:

- `live_chip()` swallows exceptions into a grey `—` (a half-typed value is an ordinary
  state, not an error),
- `save_result()` and the CSV import surface them as notifications.

Nothing is cached. A result is always derived from the inputs at the moment it is used, so
a stored row's inputs and outputs cannot disagree. Keep it that way.

### The field registry is the schema

`NUMERIC_FIELDS` and `CHOICE_FIELDS` (top of `main_niceGUI.py`) are the one definition of
the inputs. Each field id is simultaneously:

1. a `crack_analyze` parameter name,
2. a column on `CrackWidthResultTable` in `models/models.py`,
3. a column header the CSV bulk import expects (`sample_data/crack_cases_template.csv`).

So **adding or renaming an input means touching all four places** — the tuple list, the
model, the template CSV, and the user guide. The UI panels, the summary list, the import
parser and the detail view are all generated from these lists; they need no edits.

Outputs are the mirror image: `RESULT_KEYS` in `DatabaseInteractionTools/InteractionFile.py`
is the curated subset of `report_result` copied onto a row, and `SAVED_COLUMNS` in
`main_niceGUI.py` picks which of those the AG Grid shows. In the grid's `cellClassRules`,
JS expressions get `x` (the cell value) and `data` (the row) bound directly — `params` is
undefined there, and a comparison against it fails silently with no styling and no error.

### Frozen vs. source is a recurring axis

The same code runs from a checkout and from inside the exe, and the two need different
paths — getting this backwards is the most common breakage here:

- `_asset_dir()` uses `sys._MEIPASS` — the PyInstaller unpack dir. Read-only, **wiped on
  exit**. Bundled assets only (`docs/`, `sample_data/`).
- `_upload_dir()` and `models._database_dir()` use `sys.executable`'s folder — the real
  on-disk location. Writable and persistent, which is what makes the app portable: the
  database lives in `data/` next to the exe and travels with it on a USB stick.
- `FROZEN` drives `ui.run(native=FROZEN, reload=not FROZEN)` — native window when packaged,
  browser tab with hot reload in dev. Native mode re-imports the module as `__mp_main__`,
  hence the `if __name__ in {"__main__", "__mp_main__"}` guard plus `freeze_support()`;
  without it a frozen exe relaunches itself forever.

All UI lives inside `build_ui()`, passed *uncalled* to `ui.run(root=...)`. Calling it at
import time puts NiceGUI into script mode, which cannot work in a frozen exe.

## Conventions worth preserving

- `crack_analyze` and `report_result` are lowercase class names. Deliberate and load-bearing
  across the codebase — don't rename them to PascalCase.
- The engine's units are fixed at the boundary: lengths mm, stresses MPa, moduli GPa,
  N in kN, M in kNm; everything inside is N and mm. Conversions happen once, on entry.
- Comments in this codebase explain *why* a line exists — usually a bug it prevents. Match
  that when editing; don't strip them.

## Git commits

Do not add authorship or attribution trailers to commits. No `Co-Authored-By: Claude`,
no `Claude-Session:` line, no "Generated with Claude Code" footer — the commit message is
the message and nothing else. This applies to PR bodies too.

## Docs and release layout

- `README.md` ships next to the exe (end-user facing). `README.github.md` is repo-only.
  A release updates the former, never the latter.
- `CHANGELOG.md` at the root is the source of truth for the shipped version, and
  `docs/CHANGELOG.md` must be kept byte-identical — the spec bundles it into the exe, so a
  missed copy ships a stale in-app changelog. Note the `version` in `pyproject.toml` is not
  maintained and lags the real release.
- The spec bundles `docs/` and `sample_data/`, so anything dropped in `docs/` (regenerated
  user guide, new screenshots) is picked up by the next build automatically.
