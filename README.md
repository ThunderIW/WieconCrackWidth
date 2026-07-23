# Crack Width Calculator (Wiecon)

Calculates the characteristic crack width `w_k` of a reinforced concrete section to **EN 1992-1-1 cl. 7.3.4** and checks it against a limit.

---

## 1. Launching the app

Double-click **`CrackWidthNiceGUI.exe`**. The application opens in its own window — no installation is required.

> The `_internal` folder next to the `.exe` is required. Keep the whole `CrackWidthNiceGUI` folder together; do not move the `.exe` out on its own.

Two documents sit beside the `.exe`:

| File | What it is |
|---|---|
| `CrackWidth_User_Guide.pdf` | This guide, illustrated with screenshots. |
| `CHANGELOG.md` | What changed in each release. |

The app is **portable**: your saved results live in a `data` folder created next to the `.exe` on first run, so copying the folder — to a USB stick, or another PC — takes your saved files with it.

---

## 2. Step-by-step workflow

1. **Fill in the four input panels** — Geometry, Reinforcement, Materials, Loads. Click a panel header to expand it.

2. **Review the "📋 Summary of inputs"** below the panels to confirm your values at a glance.

3. **Watch the "🧮 Result" badge** — it recalculates as you type, so there is no Calculate button. It reads:

   `w_k = 0.288 mm ≤ w_max = 0.300 mm (Okay)` on green (within the limit), or
   `w_k = 0.678 mm > w_max = 0.300 mm (Not Okay)` on red (exceeds it).

   It shows a grey **—** while any field is still empty or half-typed.

4. **Save the result:** click **Save File**, type a **File name**, then click **Save** (or press **Enter**). The dialog repeats the verdict so you can confirm before saving.

5. **Manage saved files** in the **📁 Saved Files** table:
   - **View More Detail** — open a read-only detail view of the selected file(s).
   - **Delete File** — delete the ticked rows. **Delete All Files** — clear the whole table.

6. **Export to PDF:** in the detail view, click the **PDF** icon to export the report (one page per file). PDFs are saved to your **Downloads** folder.

---

## 3. Importing multiple cases at once

To run a batch of cases without typing each one, use the **Import and Download** button (beside **Reference Image**). It expands to two actions:

1. **Download the template** — a `.csv` with one column per input field. Enter one case per row, then save the file.
2. **Upload the file** — choose your `.csv`; each row is calculated and stored as a saved case, added to the **📁 Saved Files** table. A progress bar tracks the import and a message confirms how many cases were added.

> Only `.csv` files are accepted. Download the template first if you are unsure of the expected columns.

---

## 4. Handy controls

| Control | What it does |
|---|---|
| **Dark-mode toggle** (round button, bottom-right) | Switches the whole app between light and dark themes. The icon shows the mode you are **in** — a sun in light mode, a moon in dark mode — not the one you will switch to. |
| Press **`f`** | Toggles fullscreen. |
| **Credits** (header, top-right) | Shows the app info and the standard reference. |

---

## 5. Input field reference

### Geometry
| Field | Meaning | Unit | Default |
|---|---|---|---|
| Section width **b** | Width of the section. | mm | 1000 |
| Section thickness **h** | Overall depth/thickness. | mm | 525 |
| Cover to bar surface **c** | Clear cover to the bar surface. | mm | 40 |

### Reinforcement
| Field | Meaning | Unit | Default |
|---|---|---|---|
| Tension face bar **Ø** | Bar diameter on the tension face. | mm | 16 |
| Tension face bar spacing | Centre-to-centre spacing, tension face. | mm | 150 |
| Opposite face bar **Ø** | Bar diameter on the opposite face. | mm | 20 |
| Opposite face bar spacing | Centre-to-centre spacing, opposite face. | mm | 150 |
| Bar type | `ribbed` (high bond) or `plain`. | — | ribbed |

### Materials
| Field | Meaning | Unit | Default |
|---|---|---|---|
| Concrete strength **f_ck** | Characteristic cylinder strength. | MPa | 50 |
| Concrete modulus **E_c** | Elastic modulus; **0 = auto** (derived from f_ck). | GPa | 34 |
| Steel modulus **E_s** | Elastic modulus of reinforcement. | GPa | 200 |
| Creep coefficient **φ** | Creep coefficient for long-term effects. | — | 0 |

### Loads
| Field | Meaning | Unit | Default |
|---|---|---|---|
| Axial force **N** | Axial force; **tension is positive (+)**. | kN | 529 |
| Bending moment **M** | Applied bending moment. | kNm | 116 |
| Crack width limit **w_max** | Allowable crack width the result is checked against. | mm | 0.30 |
| Load duration | `long` (sustained) or `short` (instantaneous). | — | long |

---

## 6. Notes

- A blank numeric field reads as empty (`—`). The Result badge simply shows `—` until every field is filled; if you click **Save File** with one missing, the app names the value it needs.
- The Result badge updates shortly after you stop typing, not on every keystroke — so a half-typed number never flashes a misleading verdict.
- Results are stored in a local database and reload automatically the next time you open the app.

*Crack Width Calculator · Wiecon — EN 1992-1-1 cl. 7.3.4*
