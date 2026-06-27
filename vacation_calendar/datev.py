"""DATEV reconciliation interface — absence (Fehlzeiten) CSV export / import.

DATEV's payroll products (LODAS, *Lohn und Gehalt*) exchange absence data as
"Fehlzeiten"/"Bewegungsdaten" keyed by *Personalnummer* and an
*Abwesenheitsschlüssel* (absence key) with a from/to date and a day count. The
exact numeric absence keys depend on each client's payroll configuration, so the
mapping is kept configurable here (:data:`DEFAULT_ABSENCE_KEYS`) rather than
hard-coded.

This module deliberately uses a plain, well-documented semicolon-separated CSV
(the German DATEV convention) so the file can be produced and consumed without a
live DATEV connection. When API credentials (Beraternummer / Mandantennummer /
DATEVconnect) become available, :func:`export_rows` is the single seam to wire a
real client onto — it already yields normalised records.

CSV columns
-----------
``Personalnummer;Nachname;Abwesenheitsschluessel;Datum_von;Datum_bis;Tage;Art;Status``
"""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass

# Map our internal request kinds to a DATEV absence key. Override per client.
DEFAULT_ABSENCE_KEYS = {
    "vacation": "U",   # Urlaub
    "ko": "KO",        # K.O.-Tag (bezahlte Abwesenheit, kein regulärer Urlaub)
}

CSV_HEADER = [
    "Personalnummer",
    "Nachname",
    "Abwesenheitsschluessel",
    "Datum_von",
    "Datum_bis",
    "Tage",
    "Art",
    "Status",
]


@dataclass(frozen=True)
class AbsenceRow:
    personnel_no: str
    name: str
    absence_key: str
    start_date: str
    end_date: str
    days: float
    kind: str
    status: str

    def as_csv(self) -> list[str]:
        return [
            self.personnel_no,
            self.name,
            self.absence_key,
            self.start_date,
            self.end_date,
            _fmt_days(self.days),
            self.kind,
            self.status,
        ]


def _fmt_days(days: float) -> str:
    # German decimal comma, integers without a fractional part.
    if float(days).is_integer():
        return str(int(days))
    return f"{days:.1f}".replace(".", ",")


def _parse_days(raw: str) -> float:
    return float(raw.strip().replace(",", "."))


def export_rows(
    conn: sqlite3.Connection,
    year: int,
    *,
    status: str = "approved",
    absence_keys: dict[str, str] | None = None,
) -> list[AbsenceRow]:
    """Collect absences for ``year`` (default: only approved) as normalised rows."""
    keys = absence_keys or DEFAULT_ABSENCE_KEYS
    rows = conn.execute(
        """
        SELECT r.kind, r.start_date, r.end_date, r.days, r.status,
               e.personnel_no, e.name
        FROM requests r JOIN employees e ON e.id = r.employee_id
        WHERE r.status = ? AND strftime('%Y', r.start_date) = ?
        ORDER BY e.personnel_no, r.start_date
        """,
        (status, str(year)),
    ).fetchall()
    return [
        AbsenceRow(
            personnel_no=r["personnel_no"],
            name=r["name"],
            absence_key=keys.get(r["kind"], r["kind"]),
            start_date=r["start_date"],
            end_date=r["end_date"],
            days=float(r["days"]),
            kind=r["kind"],
            status=r["status"],
        )
        for r in rows
    ]


def export_csv(conn: sqlite3.Connection, year: int, *, status: str = "approved",
               absence_keys: dict[str, str] | None = None) -> str:
    """Return a DATEV-compatible Fehlzeiten CSV string for the given year."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for row in export_rows(conn, year, status=status, absence_keys=absence_keys):
        writer.writerow(row.as_csv())
    return buf.getvalue()


def parse_csv(text: str) -> list[AbsenceRow]:
    """Parse a DATEV Fehlzeiten CSV (as produced by :func:`export_csv`)."""
    reader = csv.reader(io.StringIO(text), delimiter=";")
    out: list[AbsenceRow] = []
    header_seen = False
    for raw in reader:
        if not raw or all(not c.strip() for c in raw):
            continue
        if not header_seen and raw[0].strip().lower() == "personnel_no".lower():
            header_seen = True
            continue
        if not header_seen and raw[0].strip() == CSV_HEADER[0]:
            header_seen = True
            continue
        # tolerate files with or without a header row
        if raw[0].strip() == CSV_HEADER[0]:
            continue
        try:
            out.append(
                AbsenceRow(
                    personnel_no=raw[0].strip(),
                    name=raw[1].strip() if len(raw) > 1 else "",
                    absence_key=raw[2].strip() if len(raw) > 2 else "",
                    start_date=raw[3].strip(),
                    end_date=raw[4].strip(),
                    days=_parse_days(raw[5]),
                    kind=raw[6].strip() if len(raw) > 6 else "",
                    status=raw[7].strip() if len(raw) > 7 else "",
                )
            )
        except (IndexError, ValueError) as exc:
            raise ValueError(f"Ungültige DATEV-Zeile {raw!r}: {exc}")
    return out


@dataclass(frozen=True)
class ReconcileResult:
    in_both: list[tuple[AbsenceRow, AbsenceRow]]
    only_in_calendar: list[AbsenceRow]
    only_in_datev: list[AbsenceRow]
    day_mismatches: list[tuple[AbsenceRow, AbsenceRow]]

    @property
    def is_clean(self) -> bool:
        return not (self.only_in_calendar or self.only_in_datev or self.day_mismatches)


def _key(row: AbsenceRow) -> tuple[str, str, str]:
    return (row.personnel_no, row.start_date, row.end_date)


def reconcile(
    conn: sqlite3.Connection,
    year: int,
    datev_rows: list[AbsenceRow],
    *,
    status: str = "approved",
) -> ReconcileResult:
    """Compare the calendar's approved absences against an imported DATEV file."""
    calendar_rows = export_rows(conn, year, status=status)
    cal_by_key = {_key(r): r for r in calendar_rows}
    datev_by_key = {_key(r): r for r in datev_rows}

    in_both: list[tuple[AbsenceRow, AbsenceRow]] = []
    day_mismatches: list[tuple[AbsenceRow, AbsenceRow]] = []
    for k, cal in cal_by_key.items():
        if k in datev_by_key:
            dv = datev_by_key[k]
            in_both.append((cal, dv))
            if abs(cal.days - dv.days) > 1e-9:
                day_mismatches.append((cal, dv))

    only_in_calendar = [r for k, r in cal_by_key.items() if k not in datev_by_key]
    only_in_datev = [r for k, r in datev_by_key.items() if k not in cal_by_key]
    return ReconcileResult(in_both, only_in_calendar, only_in_datev, day_mismatches)
