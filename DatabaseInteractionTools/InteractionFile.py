from typing import Optional
import pendulum
from sqlmodel import Session, select
from dataclasses import dataclass

from models.models import CrackWidthResultTable,StartEngine
from WieconTools.crack_width_formula import report_result

# Attributes read off report_result and stored on a row.
RESULT_KEYS = ("wk", "ok", "mode", "sigma_s", "sr_max", "sr_equation", "rho_p_eff")


class InteractionFile:

    def __init__(self):
        self.engine=StartEngine().engine


    def get_all_result_for_crackWidth_table(self) -> list[CrackWidthResultTable]:
        """Every saved case, newest first."""
        with Session(self.engine) as session:
            return list(session.exec(
                select(CrackWidthResultTable)
                .order_by(CrackWidthResultTable.created_at.desc())
            ))


    def delete_results_from_crackWidth_table(self, ids: int | list[int]) -> int:
        """Delete saved cases by id. Returns how many rows were removed."""
        if isinstance(ids,int):
            ids=[ids]

        deleted_rows=0
        with Session(self.engine) as session:
            for row_id in ids:
                row=session.get(CrackWidthResultTable,row_id)
                if row is None:            # id not in table — skip, don't crash or over-count
                    continue
                session.delete(row)
                deleted_rows+=1
            session.commit()
        return deleted_rows



    def add_new_result_to_crackWidth_table(self, name: str, params: dict,
                                           result: report_result) -> CrackWidthResultTable:
        """Save one crack-width run.

        :param name: label for the saved case, e.g. "Wadi wall, base"
        :param params: the 16 form inputs, keyed by crack_analyze's parameter
                       names (the same dict passed to crack_analyze / .run)
        :param result: what crack_analyze.run() returned
        :return: the saved row, with its database-assigned id
        """
        newResult = CrackWidthResultTable(
            name=name,
            **params,
            **{key: getattr(result, key) for key in RESULT_KEYS},
        )
        with Session(self.engine) as session:
            session.add(newResult)
            session.commit()
            session.refresh(newResult)
        return newResult

