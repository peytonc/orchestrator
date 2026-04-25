from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import threading


class ResultCollector:
    """
    Collects per-case run records and writes an aggregated JSON output file.
    """

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def add(
        self,
        *,
        case_id: int,
        worker_id: int,
        worker_dir: str | Path,
        input_path: str | Path,
        output_path: str | Path,
        return_code: int,
        stdout_path: str | Path,
        stderr_path: str | Path,
        parsed: Dict[str, Any],
        warnings: Optional[List[str]] = None,
        errors: Optional[List[str]] = None,
    ) -> None:
        warnings = warnings or []
        errors = errors or []

        record = {
            "case_id": case_id,
            "worker_id": worker_id,
            "worker_dir": str(Path(worker_dir)),
            "input_path": str(Path(input_path)),
            "output_path": str(Path(output_path)),
            "return_code": return_code,
            "stdout_path": str(Path(stdout_path)),
            "stderr_path": str(Path(stderr_path)),
            "success": return_code == 0 and not errors,
            "parsed": parsed,
            "warnings": warnings,
            "errors": errors,
        }
        with self._lock:
            self._records.append(record)

    def extend(self, records: List[Dict[str, Any]]) -> None:
        self._records.extend(records)

    def to_list(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def write_json(self, results_file: str | Path) -> None:
        results_file = Path(results_file)
        results_file.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(self._records, key=lambda item: int(item.get("case_id", 0)))
        results_file.write_text(
            json.dumps(ordered, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
