"""Read country files and the pipe-delimited global member feed.

Source adapters return raw *strings*. Parsing/validation is intentionally separate.
The minimal XLSX reader uses the standard library (ZIP + XML), supports strings,
inline strings, numeric cells, and Excel serial dates in date-named columns.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator
import xml.etree.ElementTree as ET
from zipfile import ZipFile

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def read_csv(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            yield {str(k).strip(): str(v).strip() for k, v in row.items() if k is not None}


def _column_index(cell_ref: str) -> int:
    result = 0
    for char in cell_ref:
        if not char.isalpha():
            break
        result = result * 26 + ord(char.upper()) - ord("A") + 1
    return result - 1


def read_xlsx(path: Path) -> Iterator[dict[str, str]]:
    """Read first worksheet from a simple .xlsx, including sparse cells.

    This demo adapter does not evaluate formulas or handle the 1904 date system.
    Production ingest should use an approved Excel conversion service/connector.
    """
    with ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                      for si in root.findall("m:si", NS)]
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        records = []
        for row in root.findall(".//m:sheetData/m:row", NS):
            cells: dict[int, str] = {}
            for cell in row.findall("m:c", NS):
                col = _column_index(cell.get("r", "A1"))
                kind = cell.get("t")
                if kind == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
                else:
                    v = cell.find("m:v", NS)
                    value = "" if v is None or v.text is None else v.text
                    if kind == "s" and value:
                        value = shared[int(value)]
                cells[col] = value.strip()
            records.append(cells)
        if not records:
            return
        width = max(records[0]) + 1
        headers = [records[0].get(i, "").strip() for i in range(width)]
        for record in records[1:]:
            if not any(record.values()):
                continue
            output = {}
            for i, key in enumerate(headers):
                if not key:
                    continue
                value = record.get(i, "")
                if key in {"Date of Birth", "Date of Enrollment", "Date of Flight"} and value:
                    try:
                        serial = float(value)
                        if 20000 < serial < 100000:
                            value = (date(1899, 12, 30) + timedelta(days=serial)).isoformat()
                    except ValueError:
                        pass
                output[key] = value
            yield output


def read_global_flat(path: Path) -> Iterator[dict[str, str]]:
    """The sample has ten fields after |D|, despite a spec mentioning Post Code."""
    with path.open(encoding="utf-8-sig") as handle:
        header = None
        for line in handle:
            line = line.strip()
            if not line:
                continue
            fields = line.strip("|").split("|")
            if fields[0] == "H":
                header = fields[1:]
            elif fields[0] == "D":
                if not header or len(fields) - 1 != len(header):
                    yield {"_parse_error": "MALFORMED_FLAT_RECORD", "_original_line": line}
                else:
                    yield dict(zip(header, fields[1:]))
            else:
                yield {"_parse_error": "UNKNOWN_RECORD_TYPE", "_original_line": line}


def iter_source(path: Path, source: str) -> Iterator[dict[str, str]]:
    if source == "GLOBAL":
        return read_global_flat(path)
    if path.suffix.lower() == ".xlsx":
        return read_xlsx(path)
    if path.suffix.lower() == ".csv":
        return read_csv(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")
