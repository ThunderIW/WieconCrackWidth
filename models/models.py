import sys
from sqlmodel import Field, SQLModel, Relationship, create_engine
from pathlib import Path
from typing import Optional
from datetime import datetime


def _database_dir() -> Path:
    # Portable build: keep the database next to the executable so it travels with
    # the app (e.g. on a USB stick) instead of being left behind on the host PC.
    #
    # sys.executable is the REAL on-disk location of the .exe (on the USB stick),
    # not the temp dir a frozen build unpacks itself to — that temp path is
    # sys._MEIPASS, which IS wiped on exit. So writing beside sys.executable is
    # both persistent and portable, for one-dir and one-file builds alike.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent.parent / "database"


DB_PATH = _database_dir() / "WieconDatabaseResult.db"


class CrackWidthResultTable(SQLModel, table=True):
    # Guards against the class body running twice against the same metadata —
    # which happens if this module is ever imported under two names in one
    # process (a dev reloader or a multiprocessing spawn can do it). Without it
    # the second pass raises "Table is already defined for this MetaData".
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.now)

    # --- Inputs: crack_analyze() constructor ---
    section_width: float
    section_thickness: float
    cover_to_bar_surface: float
    tension_face_bar_diameter: float
    tension_face_bar_spacing: float
    opposite_face_bar_diameter: float
    opposite_face_bar_spacing: float
    concrete_strength: float
    concrete_modulus: float
    steel_modulus: float
    creep_coeff: float
    bar_type: str
    load_duration: str

    # --- Inputs: .run() ---
    N_kN: float
    M_kNm: float
    w_max: float

    # --- Outputs: copied off report_result ---
    wk: float
    ok: bool
    mode: str
    sigma_s: float
    sr_max: float
    sr_equation: str
    rho_p_eff: float


class StartEngine:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{DB_PATH}")
        # A packaged build starts against an empty database file, so the schema
        # has to be created on the way up rather than assumed to exist.
        # create_all emits CREATE TABLE IF NOT EXISTS: safe on a populated DB.
        self.create_table()

    def create_table(self):
        SQLModel.metadata.create_all(self.engine)
