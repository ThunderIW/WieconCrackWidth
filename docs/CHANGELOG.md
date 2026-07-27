# Changelog

All notable changes to the **Crack Width Calculator (Wiecon)** are recorded here.

Versions before 2.1.1 were released without a tracked history, so their changes cannot be
reconstructed. Version 2.1.1 is therefore written up as a **baseline**: it describes the
application in full, rather than as a diff. Every release after it — starting with 2.1.2
— is a real change list measured against that baseline.

---

## [2.1.8] — 2026-07-27

### Added

- **A scope warning in the Credits dialog.** The dialog now states that the check is
  valid for slabs only — not beams or columns. The calculation has always assumed a
  slab-type section, but nothing said so on screen, and entering beam or column
  dimensions returns a plausible-looking crack width that does not apply to them.

> **Results are unaffected.** This release changes text on screen only; no calculation
> behaviour changed.

---

## [2.1.7] — 2026-07-21

### Added

- **Bulk import of cases from a `.csv` file.** A new **Import and Download** button
  loads many cases at once: each row of the file is calculated and stored as a saved
  case in the Saved Files table, so a batch no longer has to be typed in one at a time.
  A progress bar tracks the import, and a message confirms how many cases were added.
- **A downloadable blank template.** The same button offers a template `.csv` to
  download, showing the exact columns an import expects — fill in one row per case and
  upload it back.

### Changed — user interface only

- The Help guide gains two steps covering the new workflow — importing a file and
  downloading the template — each with a screenshot.

### Documentation

- The user guide (`CrackWidth_User_Guide.pdf`) now has a section on importing multiple
  cases and downloading the blank template, with screenshots of the Import and Download
  button and the upload dialog.

> **Results are unaffected.** Imported cases run through the same EN 1992-1-1 engine as
> cases entered by hand; no calculation behaviour changed.

---

## [2.1.5] — 2026-07-20

### Added — user interface only

- **A right-click menu on the header logo.** Right-clicking the logo opens a quick
  menu with **Toggle Light/Dark Mode** (the same switch as the round button) and
  **Exit** to close the application.
- **Zoomable screenshots in the Help guide.** Each step image now carries a zoom
  button that opens the picture full-size in its own window.

### Fixed

- **Help-guide step images now display for every step.** Three step screenshots
  (load duration, live result, and exiting the app) pointed at old file names and
  showed nothing; they now render correctly.
- Removed a stray module import that pointed into the packaged `dist` folder, which
  could break a fresh build. No user-facing behaviour changed.

### Documentation

- The user guide (`CrackWidth_User_Guide.pdf`) now covers the Help guide and the
  header-logo right-click menu (Toggle Light/Dark Mode and Exit), each with a
  screenshot.

> **Results are unaffected.** Every change in 2.1.5 is presentation only — no
> calculation behaviour changed.

---

## [2.1.4] — 2026-07-20

### Added — user interface only

- **A "How to use this tool" guide in the Help dialog.** Help now opens a numbered,
  step-by-step walkthrough — enter the section, set the load duration, read the live
  result, save the case, review saved cases — each step illustrated with a screenshot.
- **A "Watch walkthrough" video.** The Help dialog links to a short video that opens
  in its own maximised window, so it can be played full-screen.
- **A tooltip on the creep coefficient φ field.** Hovering the field explains that it
  is only used under long-term loads. The hint shows even while the field is greyed
  out on "short" duration, where it was previously unreachable.
- **A notice when switching load duration to "short".** Selecting "short" now shows a
  message that the creep coefficient is only applied to long-duration loads, so the
  greyed-out, zeroed field is explained rather than silent.

### Changed — user interface only

- The Help and Credits buttons are grouped together, and the Help dialog gains a
  close (✕) button in its top-right corner.

> **Results are unaffected.** Every change in 2.1.4 is presentation only — no
> calculation behaviour changed.

---

## [2.1.3] — 2026-07-18

### Changed — user interface only

- **The creep coefficient φ field now clears to 0 when load duration is set to
  "short".** Previously the field was only greyed out on "short" while keeping
  whatever value had been typed, which could read as though a non-zero φ were still
  in effect. The engine already forced φ = 0 for short-duration loading, so this is
  a display fix that makes the shown value match the value actually used. Switching
  back to "long" leaves the field at 0 for the real coefficient to be entered.

  > **Results are unaffected.** The calculation engine already applied φ = 0 for
  > "short" load duration; only the on-screen field value changes.

---

## [2.1.2] — 2026-07-17

### Fixed — affects results

- **The creep coefficient φ now widens the crack instead of narrowing it.** Setting φ
  above 0 used to *reduce* `w_k` (0.678 → 0.670 on the default section) and then stop
  having any effect at all — every φ from 0.5 upward returned exactly the same number.

  Creep never reached the cracked-section analysis: the neutral axis stayed at 25.121 mm
  and the steel stress at 395.658 MPa whatever φ was set to. The only path φ had into the
  result was the tension-stiffening term of Eq 7.9, which *subtracts* — so more creep
  meant a smaller crack, until the strain hit its `0.6·σ_s/E_s` floor and pinned there.

  The section is now solved on the creep-adjusted modulus `E_c,eff = E_cm/(1 + φ)`, and
  the tension-stiffening term uses the `E_s/E_cm` ratio that Eq 7.9 actually specifies.
  Creep now deepens the neutral axis and raises the steel stress, as it should:
  `w_k` 0.678 → 0.681 at φ = 2 on the default section.

  > **If you use a non-zero creep coefficient, your results will change** — `w_k` rises
  > where it previously fell. **A φ = 0 result is unaffected**: the fix is algebraically
  > inert at φ = 0, so every case saved with the default still reads exactly as before,
  > verification benchmark included. Re-check any saved case that used a non-zero φ.

  Note that `w_k` is still not guaranteed to rise with φ on every section. EN 1992-1-1
  ties the crack spacing `s_r,max` to the neutral axis (Eq 7.14 is `1.3(h − x)`), and
  creep deepens `x`, which shrinks the spacing. Where that outruns the strain increase,
  `w_k` eases off. That is the code's geometry, not a defect.

---

## [2.1.1] — 2026-07-17

Baseline release. The application calculates the characteristic crack width `w_k` of a
reinforced concrete section to **EN 1992-1-1 cl. 7.3.4** and checks it against an
allowable limit.

### Shipped in this release

**Calculation**
- Crack width `w_k` to EN 1992-1-1 cl. 7.3.4, checked against a user-set limit `w_max`.
- A result passes when `w_k ≤ w_max`, so a value landing exactly on the limit is within it.
- Concrete modulus `E_c` may be entered directly or left at `0` to be derived from `f_ck`.
- Creep coefficient `φ` and load duration (`long` / `short`) account for long-term effects.
- Axial force `N` follows the tension-positive sign convention.

**Input**
- Fourteen numeric fields and two choice fields, grouped into four expansion panels:
  Geometry, Reinforcement, Materials, Loads.
- A live "Summary of inputs" below the panels reflects every field as it is typed.
- Empty fields read as `—` rather than as zero; saving with one missing names the
  value that is needed.

**Result**
- A verdict badge recalculates as you type — there is no Calculate button.
- Green when within the limit, red when it exceeds, grey `—` while any field is blank
  or half-typed.
- The badge settles shortly after typing stops, so a partially entered number never
  flashes a misleading verdict.
- One shared phrasing of the verdict (`w_k = 0.209 mm ≤ w_max = 0.300 mm`) is used by
  the badge, the save dialog, and the PDF report, so the same check cannot read two
  ways depending on where it is viewed.

**Saved files**
- Results are stored in a local SQLite database and reload on next launch.
- A Saved Files table lists them colour-coded by verdict: PASS green, FAIL red.
- View a read-only detail view of one or more selected files; delete selected rows or
  clear the table.
- The save dialog repeats the verdict so it can be confirmed before writing.

**PDF export**
- Any saved case exports to a PDF report, one page per case, written to the user's
  Downloads folder.
- The report reuses the on-screen theme colours, so it matches the detail card.

**Interface**
- Runs as its own desktop window; no installation, no browser needed.
- Light and dark themes via the bottom-right toggle.
- `f` toggles fullscreen; the header logo opens app info and the standard reference.

**Documentation**
- `CrackWidth_User_Guide.pdf` — illustrated English user guide, bundled with the app
  and placed next to the `.exe`.
- `CHANGELOG.md` — this file, shipped alongside the guide.

### Known limitations
- Windows only. The PDF export and the user guide both load Arial from
  `C:\Windows\Fonts`, which is also what carries the `σ`, `φ`, and `Ø` glyphs the
  labels use.
- The app's own headings use emoji; the generated PDFs deliberately do not, because
  Arial has no emoji glyphs and they would render as empty boxes.
