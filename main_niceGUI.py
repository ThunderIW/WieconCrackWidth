import asyncio
import csv
import io
import os
import sys
import multiprocessing

import polars as pl
from nicegui import ui, app, events
from collections import defaultdict
from pathlib import Path
from fpdf import FPDF
from WieconTools.crack_width_formula import crack_analyze,report_result
from DatabaseInteractionTools.InteractionFile import InteractionFile
from models.models import CrackWidthResultTable
import pendulum

# Quasar QDialog prop: blurs and dims the page behind an open dialog.
# Quoted so ui.props() keeps the two filter functions as one value.
animated_dialog = 'backdrop-filter="blur(4px) brightness(60%)"'


def _asset_dir() -> Path:
    # PyInstaller unpacks bundled data under _MEIPASS; in a source checkout the
    # assets sit next to this file. Path(__file__) alone breaks in a frozen exe.
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


REFERENCE_IMAGE = _asset_dir() / "docs" / "crack_width_variables.svg"
AVATAR_IMAGE    = _asset_dir() / "docs" / "Github Profile.png"
# Drop your logo file here (PNG/SVG with a transparent background works best on
# the dark header). _asset_dir() makes it resolve both in dev and the frozen exe.
LOGO_IMAGE      = _asset_dir() / "docs" / "Wiecon_logo-removebg-preview.png"
# App icon. .ico carries multiple resolutions, so it renders crisply as both the
# browser-tab favicon and the packaged native window / taskbar icon.
APP_ICON        = _asset_dir() / "docs" / "Wiecon_logo.ico"


def _upload_dir() -> Path:
    # Where uploaded files are saved. Unlike _asset_dir() this must NOT use
    # _MEIPASS: that is the read-only temp dir a frozen build unpacks to and wipes
    # on exit. Uploads are writable data, so they sit next to the .exe (mirroring
    # models._database_dir), keeping the app portable. In a source checkout this
    # resolves to the project's upload_data folder.
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    d = base / "upload_data"
    d.mkdir(parents=True, exist_ok=True)
    return d


UPLOAD_DIR = _upload_dir()
#This is for ui.table which uses AAGRID for formatting purposes
NUMERIC_FIELDS = [
      ("section_width",              "Section width b [mm]",     1000.0, 1.0,  "Geometry"),
      ("section_thickness",          "Section thickness h [mm]",  525.0, 1.0,  "Geometry"),
      ("cover_to_bar_surface",       "Cover to bar surface c [mm]",40.0, 0.0,  "Geometry"),
      ("tension_face_bar_diameter",  "Tension face bar Ø [mm]",    16.0, 1.0,  "Reinforcement"),
      ("tension_face_bar_spacing",   "Tension face bar spacing [mm]",150.0,1.0,"Reinforcement"),
      ("opposite_face_bar_diameter", "Opposite face bar Ø [mm]",   20.0, 1.0,  "Reinforcement"),
      ("opposite_face_bar_spacing",  "Opposite face bar spacing [mm]",150.0,1.0,"Reinforcement"),
      ("concrete_strength",          "Concrete strength f_ck [MPa]",50.0, 1.0, "Materials"),
      ("concrete_modulus",           "Concrete modulus E_c [GPa] (0 = auto)",34.0,0.0,"Materials"),
      ("steel_modulus",              "Steel modulus E_s [GPa]",   200.0, 1.0,  "Materials"),
      ("creep_coeff",                "Creep coefficient φ",         0.0, 0.0,  "Materials"),
      ("N_kN",                       "Axial force N [kN] (tension +)",529.0,None,"Loads"),
      ("M_kNm",                      "Bending moment M [kNm]",    116.0, None, "Loads"),
      ("w_max",                      "Crack width limit w_max [mm]",0.30, 0.01,"Loads"),
  ]

# Passed to crack_analyze.run(), not to the constructor.
LOAD_KEYS = ("N_kN", "M_kNm", "w_max")

# (field id, label, options, default, group) — the two non-numeric constructor args.
CHOICE_FIELDS = [
    ("bar_type",      "Bar type",      ["ribbed", "plain"], "ribbed", "Reinforcement"),
    ("load_duration", "Load duration", ["long", "short"],   "long",   "Loads"),]


GROUP_ICONS = {
      "Geometry":      "straighten",     # ruler
      "Reinforcement": "grid_4x4",       # rebar mesh
      "Materials":     "science",        # flask
      "Loads":         "arrow_downward", # applied force
  }


# by_group: "Geometry" -> [(kind, fid, label, default, extra), ...]
#   Sorts the flat field lists into one bucket per expansion panel.
#   defaultdict(list) means by_group[group] auto-creates an empty list on first use.
#   "extra" is the minimum for numbers, the options list for choices — the two
#   field types are unpacked the same way, and `kind` says which is which.
#
# LABELS: fid -> human label, e.g. "section_width" -> "Section width b [mm]"
#   inputs{} only maps fid -> element, so the summary list would otherwise have
#   nothing but the snake_case id to display. Built here because this is the one
#   place fid and label are both in scope (same tuple).
by_group: dict[str, list] = defaultdict(list)
LABELS: dict[str, str] = {}
for fid,label,default,minimum,group in NUMERIC_FIELDS:
    by_group[group].append(("Numeric",fid,label,default,minimum))
    LABELS[fid]=label
for fid,label,options,default,group in CHOICE_FIELDS:
    by_group[group].append(("Choice",fid,label,default,options))
    LABELS[fid]=label


# Turns a raw input value into display text for the summary list.
# Passed (not called) to bind_text_from, which re-runs it on every value change.
def fmt(v):
    if v is None:          # an empty ui.number holds None, not 0
        return "—"
    # selects hold strings ("ribbed"); f'{v:,.2f}' on a str raises ValueError
    return f'{v:,.2f}' if isinstance(v,(int,float)) else str(v)




inputs={}


def verdict_message(r) -> str:
    """The one phrasing of a result: `w_k = 0.678 mm > w_max = 0.300 mm`.

    Shared by live_chip() and save_dialog() so the same check can't read two ways
    depending on where you look at it.

    '≤' not '<' — ok is `wk <= w_max` (crack_width_formula.py), so a w_k landing exactly
    on the limit still passes. Both sides are named, because a bare second number leaves
    the reader to infer that it's the limit; w_max is the EN 1992-1-1 symbol and matches
    the input field's label, so it reads the way a hand calc would. Both at 3dp so the
    comparison scans cleanly: 0.678 > 0.300 beats 0.678 > 0.30.
    """
    op = '≤' if r.ok else '>'
    okay_or_not_okay_message= 'Okay' if r.ok else 'Not Okay'
    return f'w_k = {r.wk:.3f} mm {op} w_max = {r.w_max:.3f} mm ({okay_or_not_okay_message})'


def save_dialog(result, values: dict):
    """
    Displays a save dialog for saving results with user confirmation and input.

    The function utilizes a UI dialog to show a notification regarding the result,
    allowing the user to confirm saving it to the database. The dialog provides real-time
    feedback, such as result status and allows users to input a filename.
    Confirmation actions are available via a save button, cancel button, or pressing the Enter key.

    :param result: An object containing the result of a process including attributes
        like `wk` (value to be displayed) and `ok` (boolean indicating pass/fail status).
    :param values: A dictionary containing additional data necessary for saving the result.
    :type values: dict
    :return: None
    """
    # w-96, not w-80: the verdict line is 33 characters, and at w-80 the banner row
    # wrapped — nicegui-row is flex-wrap:wrap, so the icon broke onto its own line
    # above the text instead of sitting beside it.
    with ui.dialog().props(animated_dialog) as dialog, ui.card().classes("w-96"):
        ui.tooltip("Tip: press Enter to save")  # attaches to the card, shown on hover
        # Result banner — colored by pass/fail, shown in the dialog instead of a
        # fleeting toast so it stays on screen while deciding to save.
        tone = "positive" if result.ok else "negative"
        # no-wrap: icon and verdict are one unit, never stacked.
        with ui.row().classes(f"w-full justify-center items-center no-wrap gap-2 py-2 rounded-lg bg-{tone}"):
            ui.icon("check_circle" if result.ok else "cancel").classes("text-2xl text-white")
            ui.label(verdict_message(result)).classes("text-base font-bold text-white")
        with ui.column().classes("w-full items-center"):
            ui.label("Do you want to save this File ?").classes("text-lg font-bold")
            case_name = ui.input(placeholder="Enter File Name").props('autofocus input-class=text-center')

        def save_to_database():
            name = (case_name.value or "").strip()
            if not name:  # don't create nameless rows
                ui.notify("Please enter a File name", type="negative", position="center", timeout=3)
                return
            InteractionFile().add_new_result_to_crackWidth_table(
                name, values, result
            )
            dialog.close()
            refresh_saved_cases()  # new row shows up without a page reload
            ui.notify(f"Saved {name} to database", position="center", timeout=3)

        case_name.on('keydown.enter', save_to_database)  # Enter in the field saves

        with ui.row().classes('w-full justify-center'):
            ui.button("Save", on_click=save_to_database).props("flat")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()



def collect_inputs_and_run_calculation(values: dict) -> report_result:
    """
    Collects input parameters, processes them to separate load-related data, and executes
    a calculation using the gathered inputs. The function prepares input data by splitting
    the provided dictionary into calculations-specific and load-specific components. Using
    these inputs, a calculation instance is executed and the result is returned.

    :param values: A dictionary containing input parameters required for the calculation.
        Keys should include both those relevant for the calculation instance and for loads.
    :return: The result of the calculation after execution with the processed input
        parameters.
    :rtype: report_result
    """
    input_values = dict(values)                       # copy: .pop() would mutate the caller's dict
    loads = {k: input_values.pop(k) for k in LOAD_KEYS}
    #app.storage.user['Crack_width_result'] = crack_analyze(**input_values).run(**loads)

    return crack_analyze(**input_values).run(**loads)









def save_result():
    """
    Executes the process of collecting user input values, running a calculation based
    on the provided data, and saving the result. Ensures all required numeric fields
    are filled before proceeding with the calculation. If the input validation or
    calculation fails, appropriate user notifications are displayed.

    :raises ValueError: Raised if required numeric fields are missing from the input.
    :raises Exception: Raised if the calculation fails due to unforeseen issues.
    :return: None
    """
    values = {fid: el.value for fid, el in inputs.items()}
    # A cleared ui.number holds None, and crack_analyze would raise mid-formula on
    # it. Name the missing fields instead of dumping a stack trace.
    missing = [LABELS[fid] for fid, *_ in NUMERIC_FIELDS if values.get(fid) is None]
    if missing:
        ui.notify("Please fill in: " + ", ".join(missing),
                  type="negative", position="center", timeout=3, multi_line=True)
        return
    try:
        result = collect_inputs_and_run_calculation(values)
    except Exception as e:
        # Unlike the chip, this path was asked for explicitly — so say what broke.
        ui.notify(f"Calculation failed: {e}", type="negative",
                  position="center", timeout=5, multi_line=True)
        return
    save_dialog(result, values)





@ui.refreshable
def live_chip():
    """
    Refreshes the display and updates the live chip output based on the current
    input values. Validates numeric fields and processes calculations if all
    required values are present. Handles errors gracefully to maintain a user-friendly
    interface.

    :param inputs: A dictionary mapping field IDs to their corresponding input elements.
    :type inputs: dict

    :param NUMERIC_FIELDS: A list of tuples defining numeric field IDs and their properties.
    :type NUMERIC_FIELDS: list

    :return: None
    """
    values = {fid: el.value for fid, el in inputs.items()} #Collectin the inputs values
    if any(values.get(fid) is None for fid, *_ in NUMERIC_FIELDS): #Here we check if the required fields are filled
        ui.label('—').classes('text-grey')
        return
    try:
        r = collect_inputs_and_run_calculation(values)
    except Exception:
        """
        During user interaction when no data is inputed it would lead to error being 
        caused so we catch this Exception and Update the chip to be blank.
        """
        ui.label('—').classes('text-grey')
        return

    tone = 'positive' if r.ok else 'negative' #Here we are get the value of the result and if it is true then the chip will be green and if it is false then the chip will be red
    with ui.row().classes(f'items-center gap-2 px-3 py-1 rounded-full bg-{tone}'):
        # we set the icon of the chip to be tick if it passes and x if it fails
        ui.icon('check_circle' if r.ok else 'cancel').classes('text-white text-sm')
        ui.label(verdict_message(r)).classes('text-white font-bold')








    # Columns shown in the saved-cases grid: database field -> header shown in the grid.
# Every field of CrackWidthResultTable is available (see model_fields, ~24 of them);
# this is a curated subset. Add a "field": "Header" pair to show one more.
# "decimals" is optional — only numeric columns get one.
# "rules" is optional — AG Grid cellClassRules: {css class: JS expression}, where
# `x` is the cell value and `data` is the whole row. NOT `params.data`: a string
# expression is evaluated with the row fields bound directly, so `params` is
# undefined in that scope and every comparison against it silently returns false —
# the cell just never gets painted, with no error.
SAVED_COLUMNS = {
    "name":       {"header": "File Name"},
    # field stays created_at (the ISO string) so sorting/filtering stay correct —
    # ISO sorts properly as text. "display_from" points at the pendulum-formatted
    # key that load_saved_rows() adds, which is what the user actually sees.
    "created_at": {"header": "Created at", "display_from": "created_display"},
    "wk":         {"header": "Crack width w_k [mm]",       "decimals": 3,
                   # compared against THIS row's own limit, not a hardcoded number
                   "rules": {"cw-fail": "x > data.w_max",
                             "cw-pass": "x <= data.w_max"}},
    "w_max":      {"header": "Limit w_max [mm]",           "decimals": 2},
    "ok":         {"header": "Pass",
                   "rules": {"cw-pass": "x === true",
                             "cw-fail": "x === false"}},
    "mode":       {"header": "Mode"},
    "sigma_s":    {"header": "Steel stress σ_s [MPa]",     "decimals": 1},
    "sr_max":     {"header": "Crack spacing s_r,max [mm]", "decimals": 0},
}


def build_column_defs() -> list[dict]:
    """columnDefs for the saved-cases grid.

    A key prefixed with ':' is sent to the browser as JavaScript rather than a
    literal string — that's how valueFormatter becomes a real JS function.
    Formatting here (not in load_saved_rows) keeps rowData numeric, so AG Grid
    still sorts and filters numerically; only the painted text is rounded.
    """
    defs=[]
    for field,cfg in SAVED_COLUMNS.items():
        #print(cfg)
        col={"headerName":cfg["header"],"field":field,"sortable":True,"filter":True}
        if "decimals" in cfg:
            d=cfg["decimals"]
            # `== null` catches both null and undefined; .toFixed() on null throws
            # and would silently blank the cell.
            col[":valueFormatter"]=(
                f"params => params.value == null ? '' : params.value.toFixed({d})"
            )
        if "display_from" in cfg:
            # Show another key's value (e.g. the pendulum-formatted date) while the
            # column's own field keeps the sortable raw value.
            col[":valueFormatter"]=f"params => params.data.{cfg['display_from']}"
        if "rules" in cfg:
            # No ':' prefix here — cellClassRules is a plain dict of expressions
            # that AG Grid evaluates itself, not a JS function we hand it.
            col["cellClassRules"]=cfg["rules"]
        defs.append(col)
    return defs



async def on_selected_changed():
    selected=await saved_grid.get_selected_rows()
    n=len(selected)
    delete_button.visible=bool(selected)
    view_more_detail_button.visible=bool(selected)


    delete_button.text=f"Delete {n} File{'' if n==1 else 's'}"
    view_more_detail_button.text=f"Select {n} File{'' if n==1 else 's'} then click to view"

    # When a selection makes the action buttons appear, scroll them into view so
    # they aren't hidden below the fold. Only on select — not on deselect.
    if selected:
        await ui.run_javascript(
            'document.querySelector(".action-buttons")'
            '?.scrollIntoView({behavior: "smooth", block: "center"})'
        )

# Pure data fetch — no UI calls, so it's safe to call while the page is being
# built (ui.notify needs a connected client and would fail there).
def load_saved_rows() -> list[dict]:
    cases=InteractionFile().get_all_result_for_crackWidth_table()


    # mode='json' turns created_at (a datetime) into a string — the frontend
    # can't serialize raw datetimes.
    # Each row keeps ALL its fields (incl. 'id'), even though only SAVED_COLUMNS
    # are displayed.
    rows = [c.model_dump(mode="json") for c in cases]
    for r in rows:
        stamp=pendulum.parse(r["created_at"])
        r['created_display']=stamp.format("MMM D, YYYY hh:mm A")
        r['created_human'] = stamp.diff_for_humans()

    return rows


# Re-reads the table and pushes it to the browser. Call after saving a new case.
def refresh_saved_cases():
    rows=load_saved_rows()
    saved_grid.options["rowData"]=rows
    saved_grid.update()                       # without this the browser never sees it
    # First-launch fix: AG Grid's "no rows" overlay (shown when the grid starts
    # empty) does NOT auto-hide when rowData is updated live, so the first saved
    # row stays hidden behind it. Toggle the overlay to match the new row count.
    saved_grid.run_grid_method('hideOverlay' if rows else 'showNoRowsOverlay')
    # Replacing rowData drops the selection, but AG Grid doesn't reliably fire
    # selectionChanged for that — so hide the buttons ourselves or they linger,
    # still reading "Delete 2 cases" with nothing selected.
    delete_button.visible=False
    view_more_detail_button.visible=False
    # "Delete All" shows only while the table has at least one case.
    delete_all_button.visible=bool(rows)




# --- summary helpers ---------------------------------------------------------
# heading(): the title above each summary column.
def heading(text, icon=None):
    # opacity-60, not text-gray-500: opacity dims the INHERITED colour, so it stays
    # legible in dark mode. A fixed grey would override the adaptive text colour.
    with ui.row().classes("items-center gap-1 border-b w-full pb-1 opacity-60"):
        if icon:
            ui.icon(icon).classes("text-sm")
        ui.label(text).classes("text-xs font-bold uppercase")

# Leading icon per summary row, keyed by field id. Missing keys fall back to a
# neutral bullet, so adding a new row() never breaks — you just get a plain dot
# until you add an icon here. Names are Material Icons (NiceGUI's default set).
ROW_ICONS = {
    "section_width":              "straighten",
    "section_thickness":          "height",
    "cover_to_bar_surface":       "layers",
    "tension_face_bar_diameter":  "radio_button_unchecked",
    "tension_face_bar_spacing":   "space_bar",
    "opposite_face_bar_diameter": "radio_button_unchecked",
    "opposite_face_bar_spacing":  "space_bar",
    "bar_type":                   "category",
    "concrete_strength":          "foundation",
    "concrete_modulus":           "fitness_center",
    "steel_modulus":              "fitness_center",
    "creep_coeff":                "schedule",
    "N_kN":                       "compress",
    "M_kNm":                      "sync",
    "w_max":                      "rule",
    "load_duration":              "timelapse",
}

# row(): one "🔧 Label            value" line in the summary.
#   Looks up inputs[fid] when CALLED, so every row() below must come after the
#   input fields have been built. bind_text_from keeps the value live — see fmt().
def row(fid):
    with ui.row().classes("w-full justify-between items-center gap-4 no-wrap") as line:
        with ui.row().classes("items-center gap-1 no-wrap"):
            ui.icon(ROW_ICONS.get(fid, "circle")).classes("text-sm opacity-50")
            # whitespace-nowrap (not truncate): the label stays on one line and the
            # grid column auto-sizes to fit it, instead of clipping with an ellipsis.
            ui.label(LABELS[fid]).classes("text-xs opacity-70 whitespace-nowrap")
        ui.label().classes("text-sm font-bold text-primary whitespace-nowrap") \
            .bind_text_from(inputs[fid],"value",fmt)
    return line


# Result fields stored on each row, in display order. (Mirrors RESULT_KEYS in
# InteractionFile.py — those are the attributes copied off report_result.)
RESULT_LABELS = {
    "wk":          "Crack width w_k [mm]",
    "w_max":       "Limit w_max [mm]",
    "mode":        "Mode",
    "sigma_s":     "Steel stress σ_s [MPa]",
    "sr_max":      "Crack spacing s_r,max [mm]",
    "rho_p_eff":   "Effective reinf. ratio ρ_p,eff",
}


# Quasar theme colours, reused so the PDF matches the on-screen detail card.
_PDF_POS   = (33, 186, 69)    # q-positive green
_PDF_NEG   = (193, 0, 21)     # q-negative red
_PDF_PRIM  = (25, 118, 210)   # q-primary blue (result values)
_PDF_GREY  = (120, 120, 120)  # muted labels / captions
_PDF_DARK  = (40, 40, 40)     # body text
_PDF_LINE  = (222, 222, 222)  # borders / bar track

# Arial ships on every Windows install and covers the Greek/Ø glyphs the labels
# use; fpdf2's built-in Helvetica is latin-1 only and would raise on σ/φ/ρ.
_FONTS_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def _pdf_kv_row(pdf: FPDF, label: str, value: str, value_rgb=_PDF_DARK) -> None:
    """One 'Label ................ value' line, mirroring a detail row."""
    w = pdf.epw                                   # effective page width (inside margins)
    pdf.set_font("arial", "", 9)
    pdf.set_text_color(*_PDF_GREY)
    pdf.cell(w * 0.62, 6, label, align="L")
    pdf.set_font("arial", "B", 9)
    pdf.set_text_color(*value_rgb)
    pdf.cell(w * 0.38, 6, value, align="R", new_x="LMARGIN", new_y="NEXT")


def build_detail_pdf(cases: list[dict]) -> bytes:
    """Render the saved-case detail view(s) to a PDF, one case per page."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("arial", "",  str(_FONTS_DIR / "arial.ttf"))
    pdf.add_font("arial", "B", str(_FONTS_DIR / "arialbd.ttf"))

    for d in cases:
        pdf.add_page()
        w = pdf.epw
        ok    = d["ok"]
        tone  = _PDF_POS if ok else _PDF_NEG
        ratio = d["wk"] / d["w_max"] if d["w_max"] else 0
        ratio_text = (f"{1 - ratio:.0%} below limit" if ok
                      else f"exceeds limit by {ratio - 1:.0%}")

        # ---- title ----
        pdf.set_font("arial", "B", 16)
        pdf.set_text_color(*_PDF_DARK)
        pdf.cell(0, 9, d["name"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("arial", "", 9)
        pdf.set_text_color(*_PDF_GREY)
        pdf.cell(0, 5, f"Saved {d['created_at'][:16].replace('T', ' ')}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # ---- verdict banner (bordered box + coloured left accent) ----
        x0, y0, box_h = pdf.l_margin, pdf.get_y(), 22
        pdf.set_draw_color(*_PDF_LINE); pdf.set_line_width(0.3)
        pdf.rect(x0, y0, w, box_h)
        pdf.set_fill_color(*tone)
        pdf.rect(x0, y0, 1.6, box_h, style="F")            # accent stripe

        pdf.set_xy(x0 + 6, y0 + 4)                          # big w_k value
        pdf.set_font("arial", "B", 22); pdf.set_text_color(*tone)
        pdf.cell(30, 9, f"{d['wk']:.3f}")
        pdf.set_font("arial", "", 9); pdf.set_text_color(*_PDF_GREY)
        pdf.cell(10, 9, "mm")
        pdf.set_xy(x0 + 6, y0 + 13)
        pdf.cell(0, 5, f"w_k  ·  limit {d['w_max']:.2f} mm")

        verdict = "PASS" if ok else "FAIL"                  # right-aligned verdict
        pdf.set_font("arial", "B", 14); pdf.set_text_color(*tone)
        pdf.set_xy(x0 + w - 46, y0 + 4)
        pdf.cell(40, 8, verdict, align="R")
        pdf.set_font("arial", "", 8); pdf.set_text_color(*_PDF_GREY)
        pdf.set_xy(x0 + w - 66, y0 + 13)
        pdf.cell(60, 5, ratio_text, align="R")

        # ---- progress bar ----
        pdf.set_y(y0 + box_h + 3)
        bar_y, bar_h = pdf.get_y(), 1.6
        pdf.set_fill_color(*_PDF_LINE); pdf.rect(x0, bar_y, w, bar_h, style="F")
        pdf.set_fill_color(*tone); pdf.rect(x0, bar_y, w * min(ratio, 1.0), bar_h, style="F")
        pdf.ln(6)

        # ---- inputs, grouped exactly like the dialog ----
        for group, fields in by_group.items():
            pdf.set_font("arial", "B", 8); pdf.set_text_color(*_PDF_GREY)
            pdf.cell(0, 6, group.upper(), new_x="LMARGIN", new_y="NEXT")
            for kind, fid, label, default, extra in fields:
                _pdf_kv_row(pdf, label, fmt(d[fid]))
            pdf.ln(1)

        # ---- results (values in primary blue, like text-primary) ----
        pdf.set_font("arial", "B", 8); pdf.set_text_color(*_PDF_GREY)
        pdf.cell(0, 6, "RESULTS", new_x="LMARGIN", new_y="NEXT")
        for key, label in RESULT_LABELS.items():
            _pdf_kv_row(pdf, label, fmt(d[key]), value_rgb=_PDF_PRIM)

    return bytes(pdf.output())


async def get_selected_rows():
    """Read-only detail view of the selected case(s)."""
    selected=await saved_grid.get_selected_rows()
    if not selected:
        ui.notify("No File Selected", type="negative", position="center", timeout=3)
        return

    def export_detail_to_PDF():
        # Renders the same layout shown below (verdict banner, grouped inputs,
        # results) to a PDF — one page per case.
        data=build_detail_pdf(selected)
        stamp=pendulum.now().format("YYYY-MM-DD_HHmm")
        fname=(f"crack_width_detail_{selected[0]['name']}_{stamp}.pdf"
               if len(selected)==1 else f"crack_width_detail_{stamp}.pdf")
        ui.download(data, fname)
        ui.notify(f"Exported {len(selected)} File{'' if len(selected)==1 else 's'}", type="positive", position="center", timeout=3)

    with ui.dialog().props(animated_dialog) as detail_dialog, ui.card().classes("w-[560px] max-h-[80vh] overflow-y-auto"):
        with ui.row().classes("w-full justify-end items-center gap-1"):
            ui.button(icon='picture_as_pdf', on_click=export_detail_to_PDF).props('flat round dense') \
                .tooltip("Download this detail as PDF")
            ui.button(icon='close', on_click=detail_dialog.close).props('flat round dense')

        for d in selected:
            ui.label(d["name"]).classes("text-lg font-bold")
            ui.label(f"Saved {d['created_at'][:16].replace('T', ' ')}").classes("text-xs opacity-60")

            # ---- verdict banner ----
            # Semantic colours (text-positive / text-negative), not bg-green-50 etc:
            # a fixed pastel background would stay pale under dark mode. The tint
            # comes from a coloured left border instead, which reads on both.
            ok    = d["ok"]
            tone  = "positive" if ok else "negative"
            ratio = d["wk"] / d["w_max"] if d["w_max"] else 0
            ratio_text = (f"{1 - ratio:.0%} below limit" if ok
                          else f"exceeds limit by {ratio - 1:.0%}")

            # Quasar has text-positive/text-negative but no border-colour utility,
            # so the accent stripe is set from the theme variable directly.
            with ui.row().classes(
                "w-full items-center justify-between no-wrap gap-4 p-3 my-2 rounded-lg border border-l-4"
            ).style(f"border-left-color: var(--q-{tone})"):
                with ui.column().classes("gap-0"):
                    with ui.row().classes("items-baseline gap-1 no-wrap"):
                        ui.label(f"{d['wk']:.3f}").classes(f"text-3xl font-bold text-{tone} leading-none")
                        ui.label("mm").classes("text-sm opacity-70")
                    ui.label(f"w_k  ·  limit {d['w_max']:.2f} mm").classes("text-xs opacity-80 mt-1")

                with ui.column().classes("gap-1 items-end"):
                    # A solid pill, not text-{tone}: at text-base the tinted text needs
                    # 4.5:1 and only reaches 3.36:1 on the dark surface. White on the
                    # same colour as a background gets 5.02:1, and matches live_chip().
                    with ui.row().classes(
                        f"items-center gap-1 no-wrap px-2 py-0.5 rounded-full bg-{tone}"
                    ):
                        ui.icon("check_circle" if ok else "cancel").classes("text-base text-white")
                        ui.label("PASS" if ok else "FAIL").classes("text-base font-bold text-white")
                    ui.label(ratio_text).classes("text-xs opacity-60")
                    #ui.label(f"{ratio:.0%} of limit").classes("text-xs opacity-60")
            # shrink-0 is load-bearing: the card is a flex column with max-height,
            # so once several cases overflow it the browser shrinks flex children
            # to fit — and a 6px bar collapses to nothing. That's why it vanished
            # only when more than one case was selected.
            ui.linear_progress(min(ratio, 1.0), show_value=False) \
                .props(f"color={tone} rounded size=6px").classes("w-full shrink-0")
            ui.separator().classes("my-2 shrink-0")

            # Inputs, grouped exactly like the form — same by_group, same icons and
            # labels. Add a field to NUMERIC_FIELDS and it shows up in both.
            for group,fields in by_group.items():
                with ui.expansion(group, icon=GROUP_ICONS.get(group), value=False).classes("w-full"):
                    for kind,fid,label,default,extra in fields:
                        with ui.row().classes("w-full justify-between items-baseline no-wrap"):
                            ui.label(label).classes("text-xs opacity-70 truncate")
                            ui.label(fmt(d[fid])).classes("text-sm font-bold whitespace-nowrap")

            with ui.expansion("Results", icon="fact_check", value=True).classes("w-full"):
                for key,label in RESULT_LABELS.items():
                    with ui.row().classes("w-full justify-between items-baseline no-wrap"):
                        ui.label(label).classes("text-xs opacity-70 truncate")
                        ui.label(fmt(d[key])).classes("text-sm font-bold text-primary whitespace-nowrap")

            if d is not selected[-1]:
                ui.separator()

    detail_dialog.open()




async def delete_selected_cases():
    """Delete whatever is ticked in the grid, after confirming."""
    selected=await saved_grid.get_selected_rows()
    """"
    if not selected:
        ui.notify("No File Selected", type="negative", position="center", timeout=3)
        return
    """

    # 'id' rides along in rowData even though it isn't a displayed column.
    # Use it — NOT the grid row index, which changes when you sort or filter.
    ids=[r["id"] for r in selected] #Here we are getting the ids of the selected cases
    names=" "
    #.join(r["name"] for r in selected) #Here we are getting the names of the selected cases



    def confirm():
        deleted=InteractionFile().delete_results_from_crackWidth_table(ids) #Here is where we are actually deleting the cases
        confirm_dialog.close()
        refresh_saved_cases() #Refresh the grid after deletion to reflect the changes made to the database
        ui.notify(f"Deleted {deleted} File{'' if deleted==1 else 's'}", type="warning", position="center", timeout=3)


    #Here is the confirmation dialog to confirm the deletion of the selected cases when prompted
    with ui.dialog().props(animated_dialog) as confirm_dialog, ui.card():
        ui.label(f"Delete {len(ids)} File{'' if len(ids)==1 else 's'}?").classes("text-lg font-bold")
        for pos, file in enumerate(selected, start=1):
            file_name = file['name']
            ui.markdown(f"{pos}. **{file_name}**").classes("text-sm opacity-70")
        ui.label("This cannot be undone !").classes("text-sm opacity-70 text-red-500 font-bold")
        with ui.row():
            ui.button("Delete", on_click=confirm).props("flat color=negative")
            ui.button("Cancel", on_click=confirm_dialog.close).props("flat")
    confirm_dialog.open()

    #ui.notify(f"Currently Selected Rows: {} ", type="info")







async def delete_all_cases():
    """Delete every saved case, after confirming. Ignores the grid selection."""
    rows=load_saved_rows()                         # pull the whole table, not the ticked rows
    if not rows:
        ui.notify("No Files to delete", type="negative", position="center", timeout=3)
        return
    ids=[r["id"] for r in rows]

    def confirm():
        deleted=InteractionFile().delete_results_from_crackWidth_table(ids)
        confirm_dialog.close()
        refresh_saved_cases()                      # empties the grid without a page reload
        ui.notify(f"Deleted {deleted} File{'' if deleted==1 else 's'}", type="warning", position="center", timeout=3)

    with ui.dialog().props(animated_dialog) as confirm_dialog, ui.card():
        ui.label(f"Delete ALL ({len(ids)} file{'' if len(ids)==1 else 's'}) ?").classes("text-lg font-bold")
        ui.label("This cannot be undone.").classes("text-sm opacity-70")
        with ui.row():
            ui.button("Delete All", on_click=confirm).props("flat color=negative")
            ui.button("Cancel", on_click=confirm_dialog.close).props("flat")
    confirm_dialog.open()


ui.button.default_props('rounded unelevated')


# All UI lives in this root function, passed to ui.run(root=build_ui).
#
# Why not module level? With UI at module level, NiceGUI runs in "script mode":
# it re-executes the script (runpy.run_path(sys.argv[0])) for each client. In a
# frozen exe sys.argv[0] is the .exe, so runpy tries to parse a binary as Python
# and dies with "source code string cannot contain null bytes". A root function
# sidesteps the re-execution entirely.
#
# global: the handlers above (on_selected_changed, delete_selected_cases, ...)
# look these up at module scope. Without `global` they'd become locals here and
# the handlers would raise NameError. `inputs` needs no global — it's mutated
# in place (inputs[fid] = ...), never rebound.





def build_ui() -> None:
    global saved_grid, delete_button, view_more_detail_button, delete_all_button

    # Wiecon brand palette. positive/negative stay green/red — those colours carry
    # meaning (pass/fail, delete) and shouldn't be rebranded; they're only darkened
    # from Quasar's defaults for contrast (see apply_theme).
    dark = ui.dark_mode()

    def apply_theme():
        """
        Here we are applying the Wiecon palette to the UI.
        Depending on the mode (dark/light), we are applying the primary color to the UI
        :return:
        """
        primary = '#4a90d9' if dark.value else '#16235c' # Here we are setting the primary color to a different shade of blue
        # positive/negative are overridden because Quasar's defaults are uneven against
        # the white text we put on them: the stock green (#21BA45) gives only 2.57:1,
        # failing WCAG AA, while the stock red manages 6.41:1. These two darker steps
        # land at 5.02:1 and 6.47:1 — so PASS reads as clearly as FAIL. Both are
        # mode-independent: white-on-green doesn't care what's behind the pill.
        ui.colors(primary=primary, secondary='#1e78c8', accent='#1e78c8',
                  positive='#15803d', negative='#b91c1c') #Setting the pages color

    def toggle_dark():
        dark.toggle()
        apply_theme()          # re-tint primary for the new mode

    apply_theme()              # set the initial (light) palette

    # Verdict cells in the saved-files grid. Driven off the Quasar theme variables so
    # they track ui.colors() instead of drifting from it, same as the detail view's
    # accent stripe. A solid fill + white text reads identically in both modes, which
    # the old bg-green-300/bg-red-300 pastels did not: against AG Grid's light dark-mode
    # text they measured 1.40:1 and 1.90:1. !important beats AG Grid's own cell styles.
    ui.add_css('''
        .cw-pass, .cw-fail { color: #fff !important; }
        .cw-pass { background-color: var(--q-positive) !important; }
        .cw-fail { background-color: var(--q-negative) !important; }
    ''')

    with (ui.header().classes('bg-[#16235c] text-white items-center')):
        # White badge behind the logo: the JPEG's white background sits on a white
        # chip so the navy/blue logo reads on the navy header (navy-on-navy would
        # vanish). QImg's inner <img> is absolutely positioned, so it needs an
        # explicit box — h-16 w-28 matches the logo's ~1.57 ratio; fit=contain
        # keeps it from cropping/stretching.

        """Here we are creating a context menu say that when a user right clicks on
        the wiecon logo they are greated with two options 1. Toggle dark mode and 2. Exiting the application since
        its being locally run through  ane exe file """
        def update_Menu_context(e:events.MouseEventArguments)->None:

            """
            Here we are updating the context menu when the user right clicks on the wiecon logo
            1. Toggle dark mode and displaying either "Toggle dark mode" or "light mode" depending on the current mode"
            2. Exiting the application since its being locally run through an exe file
            """

            with context_menu.clear(): #Clearing the context menu item to make fresh ones
                with ui.menu_item(on_click=app.shutdown).props('flat dense'):
                    with ui.row().classes('items-center gap-2 no-wrap'):
                        ui.icon('exit_to_app')
                        ui.label('Exit')

                # The menu is rebuilt on every open, so read dark.value directly
                # instead of binding — the label/icon can't go stale within one open.
                going_to_light = dark.value #here we are getting the current mode of the application either its in dark mode or light mode
                with ui.menu_item(on_click=toggle_dark).props('flat dense'):
                    with ui.row().classes('items-center gap-2 no-wrap'):
                        """
                        #Here we dynamically change the icon and menu_item text based on the current mode of the application
                        """
                        ui.icon('light_mode' if going_to_light else 'dark_mode')
                        ui.label('Toggle Light Mode' if going_to_light else 'Toggle Dark Mode') #




        with ui.element('div').classes('bg-white rounded-md p-1 shrink-0'):
            # HEre we are creating a context menu which appears when the user right clicks on the wiecon logo
           with ui.interactive_image(LOGO_IMAGE,on_mouse=update_Menu_context,events=['contextmenu']).classes("h-16 w-28").props("fit=contain"):
               context_menu=ui.context_menu()
               #with ui.context_menu():
               #    ui.menu_item("Toggle Dark Mode", on_click=toggle_dark)
               #    ui.menu_item("EXIT",on_click=app.shutdown())
        ui.label("Crack Width Calculator (Wiecon)").classes("text-lg font-bold")



        # Named credits_dialog, not `dialog` — the reference-image dialog below also
        # binds `dialog`, and reusing the name makes it easy to open the wrong one.
        """
        Here this for display the credits of the application.
        """
        with ui.dialog().props(animated_dialog) as credits_dialog, ui.card().classes("w-96 items-center"):
            ui.icon("engineering").classes("text-5xl text-primary")
            ui.label("Crack Width Calculator").classes("text-lg font-bold")
            ui.label("EN 1992-1-1 cl. 7.3.4").classes("text-sm opacity-70")
            ui.separator()
            with ui.column().classes("items-center gap-0"):
                ui.label("Developed by").classes("text-xs uppercase opacity-60")
                with ui.avatar(color='blue-2',size='xl').classes("w-12 h-12"):
                    ui.image(AVATAR_IMAGE)
                ui.label("Immanuel Wiessler").classes("text-base font-bold")
                ui.label("Wiecon").classes("text-sm opacity-70")
            ui.separator()
            ui.label("© 2026 Wiecon — internal use").classes("text-xs opacity-60")
            ui.button("Close", on_click=credits_dialog.close).props("flat")

        # ml-auto on the row eats the free space to its left, pushing both buttons
        # to the right edge; they sit side by side inside the row.


        with ui.dialog().props('maximized') as video_dialog, \
             ui.card().classes("w-full h-full p-2 flex flex-col items-center justify-center"):
            ui.button(icon='close', on_click=video_dialog.close) \
                .props('flat round dense').classes("self-end")
            ui.video(_asset_dir() / "docs" / "videos" / "7-21-2026_VERSION_2.1.7.mp4") \
                .classes("flex-1 w-full min-h-0")

        #This is the dialog window that is used for zooming in the screenshot
        with ui.dialog().props('maximized') as zoom_dialog, \
             ui.card().classes("w-full h-full p-2 flex flex-col items-center justify-center"):
            ui.button(icon='close', on_click=zoom_dialog.close) \
                .props('flat round dense').classes("self-end") #Here we are closing the dialog
            zoom_image = ui.image().props("fit=contain").classes("flex-1 w-full min-h-0") #this is where the image is zoomed in

        def open_zoom(src):
            zoom_image.set_source(src) #Here we are setting the image source to the image that was clicked on
            zoom_dialog.open() #Here we are opening the image dialog

        #This the help dialog which contains the steps that are needed to run the application
        with ui.dialog().props(animated_dialog) as help_dialog, ui.card().classes("w-96 items-center"):
            # self-end overrides the card's items-center to pin the X top-right.
            ui.button(icon='close', on_click=help_dialog.close) \
                .props('flat round dense').classes("self-end")
            ui.label("How to use this tool").classes("text-lg font-bold")
            ui.button('Watch walkthrough', icon='videocam', on_click=video_dialog.open) \
                .props('flat')

            # (title, detail, image) — edit/add/remove a tuple to change the guide.
            # image is a path relative to the app root (resolved via _asset_dir so
            # it works in the frozen exe too), or None for a step with no picture.
            help_steps = [
                ("Enter the section",
                 "Fill in **Geometry**, **Reinforcement**, **Materials** and **Loads** in the "
                 "input panels on the left.",
                 "docs/screenshots/01-input-form.png"),
                ("Import many cases at once",
                 "Use the **Import and Download** button to bulk-load cases from a "
                 "`.csv` file — or download the blank template first to see the "
                 "expected columns and fill it in.",
                 "docs/screenshots/11-import-download.png"),
                ("Upload the filled-in file",
                 "Click **upload** and pick your `.csv`; each valid row is imported "
                 "as a saved case and appears in the table.",
                 "docs/screenshots/12-upload-dialog.png"),
                ("Set the load duration",
                 "Choose **long** to include creep φ, or **short** — which greys out "
                 "and zeroes the creep coefficient (φ = 0).",
                 "docs/screenshots/08-settings-loads.png"),
                ("Read the live result",
                 "The result chip updates as you type, showing w_k against the "
                 "limit w_max and whether the check is Okay.",
                 "docs/screenshots/02_2-pill-pass.png"),
                ("Save the case",
                 "Click **Save File**, give it a name, and it's stored so you can "
                 "reopen or compare it later.",
                 "docs/screenshots/02-result-pass.png"),
                ("Review saved cases",
                 "Select rows in the table to **View More Detail** or **export a PDF** "
                 "report; 'Delete File' removes them.",
                 "docs/screenshots/04-detail-pass.png"),
                ("To Exit the app",
                 "Right click the app icon and select **Exit**.",
                 "docs/screenshots/10-exit-program.png")
            ]


            # w-full + items-start overrides the card's items-center so the steps
            # left-align; the numbered avatar keys each row to its order.
            with ui.column().classes("w-full items-start gap-3 py-2"):

                for i, (title, detail, image) in enumerate(help_steps, start=1): #Here we are iterating through the HELP_STEPS list
                    with ui.row().classes("w-full items-start no-wrap gap-3"):
                        #Here we are using nicegui avatar to display the numbered avatar [1,2,3..etc] depending on the number of steps
                        with ui.avatar(color="primary", text_color="white") \
                                .props("size=28px").classes("shrink-0"):
                            ui.label(str(i))
                        with ui.column().classes("gap-1"):
                            ui.label(title).classes("text-sm font-bold")
                            ui.markdown(detail).classes("text-xs opacity-70")
                            if image and (_asset_dir() / image).exists():
                                src = _asset_dir() / image
                                # A relative wrapper lets the zoom button float over
                                # the image; the s=src default binds THIS step's path
                                # (a bare lambda would capture the loop's last value).

                                with ui.interactive_image(src).props("fit=contain").classes("w-full rounded border"):
                                    ui.button(icon='zoom_in', on_click=lambda s=src: open_zoom(s)
                                              ).props('round dense color=primary'
                                                      ).classes('absolute bottom-1 right-1 m-1 opacity-80')





            ui.button("Close", on_click=help_dialog.close).props("flat")




        with ui.row().classes('ml-auto items-center gap-2'):
            ui.button("Help",icon='help',on_click=help_dialog.open)
            ui.button('Credits', icon='account_circle', on_click=credits_dialog.open)




    with ui.card().classes("w-full h-full p-2 flex flex-col"):
        ui.label("📐 Inputs").classes("text-base font-bold")
        # 'maximized' beats Quasar's default dialog max-width (~560px);
        # 'fit=contain' stops QImg cropping the diagram (its default is fit=cover).
        with ui.dialog().props(f'maximized {animated_dialog}') as dialog, \
             ui.card().classes("w-full h-full p-2 flex flex-col items-center justify-center"):
            ui.button(icon='close', on_click=dialog.close).props('flat round dense').classes("self-end")
            ui.image(REFERENCE_IMAGE).props('fit=contain').classes("flex-1 w-full min-h-0")







        with ui.dialog().props(f'{animated_dialog}') as upload_dialog:
            values={}
            async def upload_file(e):
                progress.set_visibility(True)
                progress.value = 0
                saved = 0
                # Assign dest BEFORE the first await, so the finally can always
                # reference it even if reading the upload fails.
                dest = UPLOAD_DIR / Path(e.file.name).name
                try:
                    data = await e.file.read()
                    # Stage the upload on disk so pl.read_csv can read it by path; the
                    # finally deletes it again once the rows are imported.
                    dest.write_bytes(data)

                    # Read the file we just saved DIRECTLY — no folder scan, so old
                    # uploads can't interfere and a second file can't silently skip.
                    if dest.suffix != '.csv':
                        ui.notify(f"Only .csv is supported (got {dest.suffix or 'no extension'})",
                                  type='warning', position='center')
                        return

                    input_cols = [fid for fid, *_ in NUMERIC_FIELDS] \
                        + [fid for fid, *_ in CHOICE_FIELDS]
                    numeric_cols = {fid for fid, *_ in NUMERIC_FIELDS}
                    db = InteractionFile()
                    pf = pl.read_csv(dest)
                    number_of_rows = len(pf)
                    if number_of_rows == 0:
                        ui.notify("That .csv has no rows to import.",
                                  type='warning', position='center')
                        return

                    for row_count, row in enumerate(pf.iter_rows(named=True), start=1):
                        params = {c: (float(row[c]) if c in numeric_cols
                                      else str(row[c]).strip()) for c in input_cols}
                        name = str(row.get('name') or "").strip() or "Imported case"
                        result = collect_inputs_and_run_calculation(params)
                        new_row = db.add_new_result_to_crackWidth_table(name, params, result)
                        if new_row.id is not None:
                            saved += 1

                        progress.value = (row_count / number_of_rows)   # 0..1 fraction
                        await asyncio.sleep(1)                         # one row per second

                    refresh_saved_cases()
                    ui.notify(f"Imported {saved} case(s) into the system.", type="positive",location="center")
                    upload_dialog.close()

                finally:
                    progress.set_visibility(False)   # hide the bar once idle
                    dest.unlink(missing_ok=True)   # drop the raw upload


            with ui.card():


                ui.button(icon='close', on_click=upload_dialog.close).props('flat round dense').classes("self-end")
                ui.label("Upload File for testing").classes("text-lg font-bold w-full text-center")
                ui.upload(on_upload=upload_file, max_files=1, label='Please upload a .csv').props(
                    'accept=".csv,text/csv"')
                progress = ui.linear_progress(value=0, show_value=False)
                # Show the percentage inside the bar; value stays the 0..1 fraction,
                # the label formats it. bind_text_from re-runs on every value change.
                with progress:
                    ui.label().bind_text_from(progress, 'value',
                                              lambda v: f'{v * 100:.0f} %')
                progress.set_visibility(False)






        with ui.row().classes('items-center'):
            ui.button('Reference Image', icon='image', on_click=dialog.open)
            with ui.fab("dataset", label="Import and Download", direction='right') \
                    .props('rounded padding="sm md"').style('min-height: 36px'):
                with ui.fab_action("upload", on_click=upload_dialog.open).props('rounded'):
                    ui.tooltip("Upload a .csv, .xls, and .xlsx file to run multiple cases ")

                with ui.fab_action('download', on_click=lambda: ui.download.file(_asset_dir() / 'sample_data' / 'crack_cases_template.csv', 'crack_cases_template.csv')).props('rounded'):
                    ui.tooltip("Download a sample .csv file to import and run multiple cases ")



        for group, fields in by_group.items():
            with ui.expansion(group,value=False,icon=GROUP_ICONS.get(group)).classes("w-full"):
                with ui.grid(columns=2).classes("w-full"):
                    for kind,fid,desc,default,extra in fields:
                        if kind=='Numeric':
                            inputs[fid]=ui.number(desc,value=default,min=extra,format='%.2f').props('debounce=300')
                        else:
                            inputs[fid]=ui.select(extra,label=desc,value=default)

        for el in inputs.values():
            el.on_value_change(live_chip.refresh)

        # Creep only develops under sustained load: the engine forces phi = 0
        # when 'short' is selected. Wire all of that in one place — grey the field
        # out rather than leave it looking live while its value is ignored, explain
        # why via a tooltip, and on switching to 'short' warn the user and zero the
        # field so the displayed value matches what the engine uses (phi = 0).
        # Re-entering 'long' leaves it at 0 for the user to type the real value.
        def wire_creep_field():
            inputs['creep_coeff'].bind_enabled_from(
                inputs['load_duration'], 'value', backward=lambda v: v == 'long')
            # A disabled Quasar field sets pointer-events:none on its control, so a
            # tooltip on it never fires on hover. Tag the field and restore
            # pointer-events while disabled so the hint still shows when greyed out.
            inputs['creep_coeff'].classes('creep-tip')
            ui.add_css('.creep-tip.q-field--disabled .q-field__control'
                       ' { pointer-events: auto; }')
            inputs['creep_coeff'].tooltip('Only used under long-term loads and for the currently selected load duration'
                                          ' will not be used for short-term loads')

            def on_load_duration_change(e):
                if e.value != 'short':
                    return
                inputs['creep_coeff'].set_value(0.0)
                ui.notify(
                    "The Creep cofficent will only be used in long loads option",
                    type="info", position="center", timeout=0, close_button=True)

            inputs['load_duration'].on_value_change(on_load_duration_change)

        wire_creep_field()




        #calculation_button=ui.button("Calculate",on_click=get_result,icon="calculate")
        #calculation_button.set_visibility(False)


        # ---- Summary of inputs -------------------------------------------------
        # Written out by hand so you control exactly what appears and where.
        # Add a variable  -> add a row("its_field_id") line.
        # Remove one      -> delete the line. Reorder -> move the line.
        # Rename a column -> edit the heading() text.
        ui.separator()
        ui.label("📋 Summary of inputs").classes("text-base font-bold")

        #This is for display the summary of the inputs
        # max-content columns size each group to its widest label (no clipping);
        # overflow-x-auto adds a scrollbar only if all four together exceed the width.
        with ui.grid(columns=4).classes("w-full overflow-x-auto gap-x-8 gap-y-1") \
                .style("grid-template-columns: repeat(4, max-content)"):

            with ui.column().classes("gap-1"):
                heading("Geometry", "crop_square")
                row("section_width")
                row("section_thickness")
                row("cover_to_bar_surface")

            with ui.column().classes("gap-1"):
                heading("Reinforcement", "grid_on")
                row("tension_face_bar_diameter")
                row("tension_face_bar_spacing")
                row("opposite_face_bar_diameter")
                row("opposite_face_bar_spacing")
                row("bar_type")

            with ui.column().classes("gap-1"):
                heading("Materials", "science")
                row("concrete_strength")
                row("concrete_modulus")
                row("steel_modulus")
                # Creep is ignored under short loads (see bind_enabled_from above),
                # so strike the summary row through when 'short' is selected.
                creep_row = row("creep_coeff")
                inputs['load_duration'].on_value_change(
                    lambda e: creep_row.classes(add='line-through opacity-50')
                    if e.value == 'short'
                    else creep_row.classes(remove='line-through opacity-50'))

            with ui.column().classes("gap-1"):
                heading("Loads", "arrow_downward")
                row("N_kN")
                row("M_kNm")
                row("w_max")
                row("load_duration")
        ui.separator()
        ui.label("🧮 Result").classes("text-base font-bold")
        # Stacked, not a row: the button acts on the pill above it, so they read as one
        # unit. Side-by-side in a w-full row either strands the button at the far edge
        # (justify-between) or lets it drift as the pill's width changes. A column also
        # can't wrap, so the pairing survives a narrow window. nicegui-column already
        # aligns items to flex-start, so both sit on the page's left edge.
        with ui.column().classes("gap-2"):
            live_chip()
            ui.button("Save File", icon="save_as", on_click=save_result).props("no-caps")

        ui.separator()
        ui.label("📁 Saved Files").classes("text-base font-bold")

        # AG Grid uses columnDefs/field + rowData — NOT ui.table's name/label/field.
        # rowData is filled here, at page build, so the grid arrives populated.
        # refresh_saved_cases() re-reads it after a new case is saved.
        saved_grid=ui.aggrid({
            "columnDefs":build_column_defs(),
            "rowData":load_saved_rows(),
            'rowSelection':{'mode':'multiRow'},
            # Spread the columns to fill the grid's width on load and on every
            # refresh, instead of leaving whitespace / a horizontal scrollbar.
            'autoSizeStrategy':{'type':'fitGridWidth'},
            'overlayNoRowsTemplate':'<span class="ag-overlay-no-rows-center">No Files to be Shown</span>',
        }).classes("w-full").style("height: 60vh")
        with ui.row().classes("w-full justify-center items-center gap-2 action-buttons"):
            delete_button=ui.button("Delete File", on_click=delete_selected_cases, icon="delete",color="negative",)
            view_more_detail_button=ui.button("View More Detail", on_click=get_selected_rows, icon="visibility",color="primary",)
            # Doesn't depend on a selection, but only makes sense when the table has
            # cases — so it tracks the row count (set here, updated in refresh_saved_cases).
            delete_all_button=ui.button("Delete All Files", on_click=delete_all_cases, icon="delete_forever",color="negative",)

            # Hidden until a row is ticked. on_selected_changed only fires on CHANGE,
            # so without this the button would be visible on a fresh page load.
            delete_button.visible=False
            view_more_detail_button.visible=False
            delete_all_button.visible=bool(saved_grid.options["rowData"])


        saved_grid.on("selectionChanged", on_selected_changed)




    fullscreen=ui.fullscreen()
    # `not e.action.repeat` is load-bearing: held keys auto-repeat keydown, and
    # without this guard each repeat toggles fullscreen on/off → screen flicker.
    ui.keyboard(on_key=lambda e: fullscreen.toggle()
                if (e.action.keydown and not e.action.repeat and e.key == 'f') else None)



    with ui.page_sticky(x_offset=18, y_offset=18):
        # toggle_dark flips the mode AND re-tints primary for it (see apply_theme).
        # Icon tracks dark.value reactively: moon while dark, sun while light.
        ui.button(on_click=toggle_dark).props('fab color=primary') \
            .bind_icon_from(dark, 'value', lambda v: 'dark_mode' if v else 'light_mode')



# True inside the PyInstaller exe, False when running from source. Lets one
# ui.run() serve both: a native window with no reloader when packaged, a browser
# tab with hot-reload while developing.
FROZEN = getattr(sys, "frozen", False)

# The guard: native mode spawns a process that RE-IMPORTS this module as
# "__mp_main__", hence both names. Without it a frozen exe relaunches itself
# forever. freeze_support() is what makes that spawn work once bundled.
if __name__ in {"__main__", "__mp_main__"}:
    multiprocessing.freeze_support()
    # pywebview defaults ALLOW_DOWNLOADS to False, so in the packaged native window
    # ui.download() (the PDF export) is silently blocked. Enabling it here — via
    # app.native.settings so it's forwarded to the pywebview subprocess — lets
    # WebView2 save exported PDFs to the user's Downloads folder.
    app.native.settings['ALLOW_DOWNLOADS'] = True
    ui.run(
        # build_ui, NOT build_ui() — pass the function, don't call it. Calling it
        # here builds the UI at import time, which puts NiceGUI back into "script
        # mode" (it re-executes sys.argv[0] per client) and that cannot work in a
        # frozen exe, where sys.argv[0] is a binary.
        root=build_ui,
        port=8082,
        native=FROZEN,          # window when packaged, browser tab in dev
        reload=not FROZEN,      # watchfiles cannot run inside a frozen exe
        title="Crack Width Calculator",
        # App icon: browser-tab favicon in dev, native window icon when packaged.
        # str() because favicon wants a path string, not a Path object.
        favicon=str(APP_ICON),



    )