---
name: rebuild
description: Rebuild and package a Crack Width app release — sync the changelog, regenerate the user-guide PDF, update the README if the app changed, build the exe with PyInstaller, copy the companion docs, zip it, then push a phone notification. Use whenever the user asks to rebuild, cut a release, or package the app.
---

# Rebuild & package a Crack Width release

Run this when the user asks to **rebuild** / cut a release / package the app.
It builds the frozen exe, refreshes the docs that ship with it, zips the result,
and sends the user a phone notification when it finishes.

The authoritative build steps and gotchas also live in the `release-build-process`
memory — if anything here conflicts with that memory, the memory wins (it may be
newer). Keep the two in sync when the process changes.

## 0. Figure out the version

1. **Find the current version.** Read the latest `## [x.y.z]` block at the top of
   `CHANGELOG.md` (cross-check against the "Latest shipped" line in the
   `release-build-process` memory).
2. **Recommend the next version.** Default to a **patch** bump (`x.y.(z+1)`) for
   bug fixes and small UI changes; suggest a **minor** bump (`x.(y+1).0`) if the
   rebuild adds a notable user-facing feature.
3. **Ask the user** with `AskUserQuestion`, always showing the current version in the
   question text, e.g. *"Current version is 2.1.7. Bump to which version?"* Offer:
   - the recommended bump (label it "(Recommended)", list it first),
   - keep the current version (rebuild without bumping),
   - and let them type a custom version via the free-text "Other" option.
   Do not guess the version — wait for their choice before writing the changelog.
- Use today's date (`YYYY-MM-DD`) for the changelog block.

## 1. Refresh the docs (only what changed)

- **CHANGELOG.md** (root): add a `## [x.y.z] — DATE` block describing the changes.
- **Sync `docs/CHANGELOG.md`** to be byte-identical — the spec bundles it into the
  exe (`_internal/docs/CHANGELOG.md`). Forgetting this ships a stale in-app changelog:
  `cp CHANGELOG.md docs/CHANGELOG.md` then `diff` them.
- **README.md**: if the workflow/features changed, update it (it ships next to the exe).
  Do **not** touch `README.github.md` — that's repo-only and is not shipped.
- **User guide PDF**: if instructions/screenshots changed, edit `build_user_guide.py`
  and regenerate:
  `./.venv/Scripts/python.exe build_user_guide.py` → writes `docs/CrackWidth_User_Guide.pdf`.
  A missing screenshot path raises `FileNotFoundError`, so a clean "Wrote …" means every
  figure embedded.

## 2. Validate

`./.venv/Scripts/python.exe -m py_compile main_niceGUI.py`  → must succeed before building.

## 3. Build the exe

`./.venv/Scripts/pyinstaller.exe --noconfirm --clean CrackWidthNiceGUI.spec > build_x.y.z.log 2>&1; echo "PYINSTALLER_EXIT=$?"`

- **Never pipe PyInstaller to `tail`/`head`** — the pipe masks its real exit code and a
  failed build looks like it passed. Redirect to a log and echo `$?`.
- Require `PYINSTALLER_EXIT=0`. Then sanity-check `dist/CrackWidthNiceGUI/CrackWidthNiceGUI.exe`
  exists and any newly-added dependency actually bundled under `_internal/`
  (e.g. `polars`, `_polars_runtime_*`). Benign warnings: `webview.platforms.android`,
  `polars.testing.parametric` (needs `hypothesis`).

## 4. Copy companion docs + zip

COLLECT wipes `dist/CrackWidthNiceGUI/`, so re-copy the three docs next to the exe and
zip **contents-at-root** (no wrapper folder):

```powershell
Copy-Item CHANGELOG.md, README.md, docs\CrackWidth_User_Guide.pdf -Destination dist\CrackWidthNiceGUI\ -Force
Compress-Archive -Path "dist\CrackWidthNiceGUI\*" -DestinationPath "dist\CrackWidthNiceGUI-x.y.z.zip"
```

Naming convention: `CrackWidthNiceGUI-x.y.z.zip` (hyphen).

## 5. Notify the user's phone

After the zip is created, send a `PushNotification` (status `proactive`) summarizing the
result, e.g. `Crack Width x.y.z rebuilt: dist/CrackWidthNiceGUI-x.y.z.zip ready.`
If the build failed, notify with the failure instead.

## 6. Update memory

Update the `release-build-process` memory's "Latest shipped" line to the new `x.y.z`
and date so the next rebuild starts from the right baseline.
