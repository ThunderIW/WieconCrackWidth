"""Generate the English user guide PDF for the Crack Width app.

Run once whenever the instructions change:

    .venv/Scripts/python build_user_guide.py

Output: docs/CrackWidth_User_Guide.pdf  (auto-bundled into the exe via the spec's
`datas = [('docs','docs')]`).

Font: Arial (covers the Greek/Ø glyphs the labels use; fpdf2's builtin Helvetica
is latin-1 only and would raise on σ/φ/ρ). Ships on every Windows install.
"""

from pathlib import Path
from fpdf import FPDF
from PIL import Image

HERE = Path(__file__).resolve().parent
DOCS = HERE / "docs"
SHOTS = DOCS / "screenshots"
FONTS_DIR = Path(r"C:\Windows\Fonts")
LOGO = DOCS / "Wiecon_logo-removebg-preview.png"
OUT = DOCS / "CrackWidth_User_Guide.pdf"

# Wiecon palette (mirrors the on-screen theme / report colours).
NAVY = (22, 35, 92)
BLUE = (25, 118, 210)
GREY = (110, 110, 110)
DARK = (40, 40, 40)
LINE = (222, 222, 222)

F = "arial"  # font alias registered below


class Guide(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_y(8)
        self.set_font(F, "", 8)
        self.set_text_color(*GREY)
        self.cell(
            0,
            5,
            "Crack Width Calculator (Wiecon)  ·  EN 1992-1-1 cl. 7.3.4",
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font(F, "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 5, f"{self.page_no()}", align="C")


def h2(pdf, title):
    """Section heading with an underline."""
    pdf.ln(3)
    pdf.set_font(F, "B", 13)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*LINE)
    y = pdf.get_y() + 1
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)


def step(pdf, num, text):
    """One instruction line (numbered when `num` is given)."""
    label = f"{num}. " if num else ""
    pdf.set_font(F, "B" if num else "", 10)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(0, 5.5, f"{label}{text}", align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def field_table(pdf, group, rows):
    """A group heading + a 4-column reference table (field / meaning / unit / default)."""
    pdf.ln(1)
    pdf.set_font(F, "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 6, group, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    w = pdf.epw
    cw = [w * 0.30, w * 0.44, w * 0.12, w * 0.14]
    heads = ["Field", "Meaning", "Unit", "Default"]

    pdf.set_font(F, "B", 8.5)
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    for c, head in zip(cw, heads):
        pdf.cell(c, 7, head, border=0, align="L", fill=True)
    pdf.ln(7)

    pdf.set_font(F, "", 8.5)
    fill = False
    for field, meaning, unit, default in rows:
        # Row height must fit the tallest wrapped cell; measure the meaning column.
        lines = pdf.multi_cell(cw[1], 5, meaning, dry_run=True, output="LINES")
        rh = max(6, 5 * len(lines) + 1)
        x0, y0 = pdf.get_x(), pdf.get_y()
        if fill:  # zebra stripe across the whole row
            pdf.set_fill_color(245, 247, 250)
            pdf.rect(x0, y0, sum(cw), rh, style="F")
        pdf.set_text_color(*DARK)
        pdf.set_xy(x0, y0)
        pdf.multi_cell(
            cw[0],
            rh,
            field,
            border=0,
            align="L",
            new_x="RIGHT",
            new_y="TOP",
            max_line_height=5,
        )
        pdf.set_xy(x0 + cw[0], y0)
        pdf.multi_cell(
            cw[1],
            5,
            meaning,
            border=0,
            align="L",
            new_x="RIGHT",
            new_y="TOP",
            max_line_height=5,
        )
        pdf.set_xy(x0 + cw[0] + cw[1], y0)
        pdf.multi_cell(
            cw[2],
            rh,
            unit,
            border=0,
            align="L",
            new_x="RIGHT",
            new_y="TOP",
            max_line_height=5,
        )
        pdf.set_xy(x0 + cw[0] + cw[1] + cw[2], y0)
        pdf.multi_cell(
            cw[3],
            rh,
            default,
            border=0,
            align="L",
            new_x="LMARGIN",
            new_y="TOP",
            max_line_height=5,
        )
        pdf.set_y(y0 + rh)
        fill = not fill
    pdf.ln(3)


def _img_ar(path):
    """Height / width of an image, for sizing before placement."""
    with Image.open(path) as im:
        return im.height / im.width


def figure(pdf, path, caption, max_w=None):
    """Place one centred, bordered screenshot with a caption; break page if needed."""
    w = max_w or pdf.epw
    h = w * _img_ar(path)
    if pdf.get_y() + h + 9 > pdf.page_break_trigger:  # keep image + caption together
        pdf.add_page()
    x = pdf.l_margin + (pdf.epw - w) / 2  # centre horizontally
    y = pdf.get_y()
    pdf.image(str(path), x=x, y=y, w=w)
    pdf.set_draw_color(*LINE)
    pdf.rect(x, y, w, h)
    pdf.set_y(y + h + 1.5)
    pdf.set_font(F, "", 8)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(0, 4.5, caption, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


def two_up(pdf, left, right, cap_left, cap_right):
    """Place two screenshots side by side (e.g. PASS vs FAIL) with captions."""
    gap = 6
    w = (pdf.epw - gap) / 2
    hl, hr = w * _img_ar(left), w * _img_ar(right)
    h = max(hl, hr)
    if pdf.get_y() + h + 9 > pdf.page_break_trigger:
        pdf.add_page()
    y = pdf.get_y()
    xL, xR = pdf.l_margin, pdf.l_margin + w + gap
    pdf.image(str(left), x=xL, y=y, w=w)
    pdf.image(str(right), x=xR, y=y, w=w)
    pdf.set_draw_color(*LINE)
    pdf.rect(xL, y, w, hl)
    pdf.rect(xR, y, w, hr)
    pdf.set_y(y + h + 1.5)
    pdf.set_font(F, "", 8)
    pdf.set_text_color(*GREY)
    pdf.cell(w, 4.5, cap_left, align="C")
    pdf.cell(gap, 4.5, "")
    pdf.cell(w, 4.5, cap_right, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


def build():
    pdf = Guide(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font(F, "", str(FONTS_DIR / "arial.ttf"))
    pdf.add_font(F, "B", str(FONTS_DIR / "arialbd.ttf"))
    pdf.add_page()

    # --- Title block ---------------------------------------------------------
    # Logo sits above the title (the PNG is ~1.57:1, so w=42 -> ~27 mm tall,
    # ending near y=40); the title starts at y=44 so the two never overlap.
    if LOGO.exists():
        pdf.image(str(LOGO), x=pdf.l_margin, y=13, w=42)
    pdf.set_y(44)
    pdf.set_font(F, "B", 20)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 10, "Crack Width Calculator", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(F, "", 10)
    pdf.set_text_color(*GREY)
    pdf.cell(
        0,
        6,
        "User Guide      |      EN 1992-1-1 cl. 7.3.4",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    step(
        pdf,
        "",
        "This app calculates the characteristic crack width w_k of a reinforced "
        "concrete section and checks it against a limit. It is valid for slabs "
        "only - not beams or columns: the check assumes a slab-type section (a "
        "rectangular strip with one bar layer per face), so beam or column "
        "dimensions return a crack width that does not apply to them.",
    )

    # --- 1. Launch -----------------------------------------------------------
    h2(pdf, "1. Launching the app")
    step(
        pdf,
        "",
        "Double-click CrackWidthNiceGUI.exe. It opens in its own window; no "
        "installation is needed. Keep the whole folder (with _internal) together.",
    )

    # --- 2. Workflow ---------------------------------------------------------
    h2(pdf, "2. Step-by-step workflow")
    # NOTE: section names here stay plain text — the on-screen headings carry emoji
    # (📋 Summary of inputs, 🧮 Result), but arial.ttf has no emoji glyphs and fpdf2
    # would render them as empty boxes.
    steps = [
        "Fill in the four input panels: Geometry, Reinforcement, Materials, Loads. "
        "Click a panel header to expand it.",
        'Review the "Summary of inputs" below the panels to confirm your values.',
        'Watch the "Result" badge. It recalculates as you type, so there is no '
        "Calculate button. It reads w_k = 0.288 mm ≤ w_max = 0.300 mm (Okay) on green "
        "(within the limit), or w_k = 0.678 mm > w_max = 0.300 mm (Not Okay) on red "
        "(exceeds it), and shows a grey dash while any field is still empty or "
        "half-typed.",
        "Save the result: click Save File, type a File name, then click Save (or "
        "press Enter). The dialog repeats the verdict so you can confirm first.",
        "Manage saved files in the Saved Files table: View More Detail, Delete File, "
        "or Delete All Files.",
        "Export to PDF: in the detail view, click the PDF icon (one page per file). "
        "PDFs go to your Downloads folder.",
    ]
    for i, text in enumerate(steps, 1):
        step(pdf, i, text)
        # Illustrate the key steps with the app screenshots.
        if i == 1:
            figure(
                pdf,
                SHOTS / "01-input-form.png",
                "Fig 1 — The four input panels; a live summary of inputs sits below them.",
            )
        elif i == 3:
            # The badge is a wide, short pill (~7:1), so the two states stack rather
            # than sit side by side — half-width would shrink the text past reading.
            figure(
                pdf,
                SHOTS / "02_2-pill-pass.png",
                "Fig 2a — Within the limit: the badge turns green and reads (Okay).",
                max_w=140,
            )
            figure(
                pdf,
                SHOTS / "02_1-pill-fail.png",
                "Fig 2b — Over the limit: the badge turns red and reads (Not Okay).",
                max_w=140,
            )
        elif i == 4:
            two_up(
                pdf,
                SHOTS / "02-result-pass.png",
                SHOTS / "02-result-fail.png",
                "PASS — the save dialog repeats the verdict",
                "FAIL — the save dialog repeats the verdict",
            )
        elif i == 5:
            figure(
                pdf,
                SHOTS / "03-saved-files.png",
                "Fig 3 — Saved files, colour-coded by verdict: PASS (green), FAIL (red).",
            )
        elif i == 6:
            figure(
                pdf,
                SHOTS / "04-detail-pass.png",
                "Fig 4 — Detail view; the PDF icon (top-right) exports it as a report.",
                max_w=95,
            )

    # --- 3. Importing multiple cases -----------------------------------------
    h2(pdf, "3. Importing multiple cases at once")
    step(
        pdf,
        "",
        "To run a batch of cases without typing each one, use the Import and Download "
        "button (beside Reference Image). It expands to two actions: download a blank "
        "template, and upload a filled-in file.",
    )
    figure(
        pdf,
        SHOTS / "11-import-download.png",
        "Fig 5 — The Import and Download button expands to a template download and "
        "an upload action.",
        max_w=110,
    )
    step(
        pdf,
        "",
        "Download the template first if you are unsure of the format: it is a .csv "
        "with one column per input field. Enter one case per row, then save the file.",
    )
    step(
        pdf,
        "",
        "Upload the file: click the upload action and choose your .csv. Each row is "
        "calculated and stored as a saved case, added to the Saved Files table; a "
        "progress bar tracks the import and a message confirms how many were added. "
        "Only .csv files are accepted.",
    )
    figure(
        pdf,
        SHOTS / "12-upload-dialog.png",
        "Fig 6 — The upload dialog; browse to a .csv to import its rows.",
        max_w=90,
    )

    # --- 4. Handy controls ---------------------------------------------------
    h2(pdf, "4. Handy controls")
    step(
        pdf,
        "",
        "Dark-mode toggle (the round button, bottom-right) switches the whole app "
        "between the light and dark themes. It shows a sun while you are in light "
        "mode and a moon while you are in dark mode — the icon is the mode you are "
        "in, not the one you will get. The choice applies everywhere: inputs, "
        "summary, result badge and the Saved Files table.",
    )
    two_up(
        pdf,
        SHOTS / "05-light-mode.png",
        SHOTS / "06-dark-mode.png",
        "Fig 5a — Light mode (the default)",
        "Fig 5b — Dark mode",
    )
    step(
        pdf,
        "",
        "Press 'f' to toggle fullscreen. The Credits button in the header shows the "
        "app info and the standard reference.",
    )
    step(
        pdf,
        "",
        'The Help button (next to Credits) opens a "How to use this tool" guide: a '
        "numbered walkthrough with a screenshot for each step. Click the zoom icon on "
        "any screenshot to view it full-size, or Watch walkthrough to play a short "
        "video that can be opened full-screen.",
    )
    figure(
        pdf,
        SHOTS / "09-help-dialog.png",
        "Fig 7 — The Help guide: a numbered walkthrough with a zoomable screenshot "
        "for each step.",
        max_w=70,
    )
    step(
        pdf,
        "",
        "Right-click the header logo for a quick menu: Toggle Light/Dark Mode (the "
        "same switch as the round button), and Exit to close the application.",
    )
    figure(
        pdf,
        SHOTS / "10-exit-program.png",
        "Fig 8 — Right-click the logo for Exit and the theme toggle.",
        max_w=90,
    )

    # --- 5. Field reference --------------------------------------------------
    pdf.add_page()
    h2(pdf, "5. Input field reference")

    field_table(
        pdf,
        "Geometry",
        [
            ("Section width b", "Width of the section", "mm", "1000"),
            ("Section thickness h", "Overall thickness", "mm", "525"),
            ("Cover to bar surface c", "Clear cover to bar surface", "mm", "40"),
        ],
    )
    field_table(
        pdf,
        "Reinforcement",
        [
            ("Tension face bar Ø", "Bar diameter, tension face", "mm", "16"),
            ("Tension face bar spacing", "Centre-to-centre spacing", "mm", "150"),
            ("Opposite face bar Ø", "Bar diameter, opposite face", "mm", "20"),
            ("Opposite face bar spacing", "Centre-to-centre spacing", "mm", "150"),
            ("Bar type", "ribbed (high bond) or plain", "-", "ribbed"),
        ],
    )
    field_table(
        pdf,
        "Materials",
        [
            ("Concrete strength f_ck", "Characteristic cylinder strength", "MPa", "50"),
            ("Concrete modulus E_c", "Elastic modulus; 0 = auto", "GPa", "34"),
            ("Steel modulus E_s", "Elastic modulus of steel", "GPa", "200"),
            ("Creep coefficient phi", "Creep coefficient, long-term", "-", "0"),
        ],
    )
    field_table(
        pdf,
        "Loads",
        [
            ("Axial force N", "Axial force; tension positive (+)", "kN", "529"),
            ("Bending moment M", "Applied bending moment", "kNm", "116"),
            ("Crack width limit w_max", "Allowable crack width", "mm", "0.30"),
            ("Load duration", "long (sustained) or short", "-", "long"),
        ],
    )

    step(
        pdf,
        "",
        "Note: a blank field reads as empty and the Result badge simply shows a dash "
        "until every field is filled; if you click Save File with one missing, the app "
        "names the value it needs. The badge updates shortly after you stop typing, not "
        "on every keystroke, so a half-typed number never flashes a misleading verdict. "
        "Results are stored locally and reload next time you open the app.",
    )

    pdf.output(str(OUT))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
