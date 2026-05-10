from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
import subprocess
import traceback


@dataclass(frozen=True)
class RunResult:
    case_id: int
    worker_id: int
    worker_dir: Path
    input_path: Path
    output_path: Path
    return_code: int
    stdout_path: Path
    stderr_path: Path
    success: bool
    parsed: Dict[str, Any]
    warnings: List[str]
    errors: List[str]


class SimulationRunner:
    """
    Runs the black-box executable locally using subprocess.

    This class does not generate cases; it expects a rendered input file and an
    output path already chosen inside a worker directory.
    """

    def __init__(self, physics_command: List[str], timeout_seconds: int | float | None = None):
        self.physics_command = physics_command
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        *,
        case_id: int,
        worker_id: int,
        worker_dir: str | Path,
        input_path: str | Path,
        output_path: str | Path,
    ) -> RunResult:
        worker_dir = Path(worker_dir)
        input_path = Path(input_path)
        output_path = Path(output_path)

        worker_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = worker_dir / f"case_{case_id:05d}.stdout.log"
        stderr_path = worker_dir / f"case_{case_id:05d}.stderr.log"

        cmd = list(self.physics_command) + [str(input_path.resolve())]

        def _safe_write(path: Path, content: str) -> list[str]:
            try:
                path.write_text(content, encoding="utf-8")
                return []
            except OSError as write_exc:
                return [
                    f"Failed to write log file {path}: {write_exc}",
                    traceback.format_exc(),
                ]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(worker_dir),
                capture_output=True,
                text=True,
                shell=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            errors = [f"Simulation timed out after {self.timeout_seconds} seconds."]
            errors.extend(_safe_write(stdout_path, exc.stdout or ""))
            errors.extend(_safe_write(stderr_path, exc.stderr or ""))
            return RunResult(
                case_id=case_id, worker_id=worker_id, worker_dir=worker_dir,
                input_path=input_path, output_path=output_path,
                return_code=-1, stdout_path=stdout_path, stderr_path=stderr_path,
                success=False, parsed={}, warnings=[],
                errors=errors
            )
        except OSError as exc:
            errors = [f"Failed to launch simulation command: {exc}"]
            errors.extend(_safe_write(stdout_path, ""))
            errors.extend(_safe_write(stderr_path, ""))
            return RunResult(
                case_id=case_id, worker_id=worker_id, worker_dir=worker_dir,
                input_path=input_path, output_path=output_path,
                return_code=-1, stdout_path=stdout_path, stderr_path=stderr_path,
                success=False, parsed={}, warnings=[],
                errors=errors
            )

        errors: List[str] = []
        errors.extend(_safe_write(stdout_path, proc.stdout or ""))
        errors.extend(_safe_write(stderr_path, proc.stderr or ""))

        return RunResult(
            case_id=case_id,
            worker_id=worker_id,
            worker_dir=worker_dir,
            input_path=input_path,
            output_path=output_path,
            return_code=proc.returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            success=proc.returncode == 0,
            parsed={},
            warnings=[],
            errors=errors,
        )
