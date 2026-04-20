from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any, Dict, List, Optional
import json
import os
import platform
import shutil
import subprocess


@dataclass(frozen=True)
class WorkerPaths:
    worker_id: int
    worker_dir: Path
    input_path: Path
    output_path: Path


class WorkflowOrchestrator:
    """
    Full pipeline:
      - validate config/template
      - generate cases
      - run cases in parallel
      - render per-case inputs
      - inject worker-local OUTPUT_FILENAME when present in the template
      - execute the black-box executable
      - parse outputs
      - collect and write final results
    """

    def __init__(
        self,
        config: ControlConfig,
        template_loader: TemplateLoader,
        renderer: Renderer,
        case_generator: CaseGenerator,
        simulation_runner: SimulationRunner,
        output_parser: OutputParser,
        result_collector: ResultCollector,
    ) -> None:
        self.config = config
        self.template_loader = template_loader
        self.renderer = renderer
        self.case_generator = case_generator
        self.simulation_runner = simulation_runner
        self.output_parser = output_parser
        self.result_collector = result_collector

        self._slot_queue: Queue[int] = Queue()
        self._reserved_placeholders = {"OUTPUT_FILENAME"}

    def run(self) -> List[Dict[str, Any]]:
        self._validate_template_and_config()

        cases = self.case_generator.generate_cases()
        if not cases:
            raise ControlError("no cases were generated")

        worker_count = SystemResourceDetector.recommended_worker_count(
            requested=self.config.execution.max_cpu_threads,
            case_count=len(cases),
        )

        for worker_id in range(1, worker_count + 1):
            self._slot_queue.put(worker_id)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(self._run_single_case, case)
                for case in cases
            ]

            for future in as_completed(futures):
                record = future.result()
                self.result_collector.add(**record)

        records = self.result_collector.to_list()
        records.sort(key=lambda item: item["case_id"])

        self._write_results_file(records)

        if not self.config.execution.preserve_workdirs:
            self._cleanup_worker_dirs(worker_count)

        return records

    def _validate_template_and_config(self) -> None:
        template_placeholders = set(self.template_loader.placeholders)
        public_placeholders = template_placeholders - self._reserved_placeholders

        # Exact match for ordinary placeholders.
        self.config.validate_against_template(public_placeholders)

        # If the template uses OUTPUT_FILENAME, that is handled at runtime.
        # The required output path itself is still defined by paths.physics_output_file.
        if not self.config.paths.physics_output_file:
            raise ControlError("paths.physics_output_file must be defined")

    def _run_single_case(self, case: Dict[str, Any]) -> Dict[str, Any]:
        worker_id = self._acquire_worker_id()
        try:
            return self._execute_case_in_worker_slot(case, worker_id)
        finally:
            self._slot_queue.put(worker_id)

    def _acquire_worker_id(self) -> int:
        return self._slot_queue.get()

    def _execute_case_in_worker_slot(
        self,
        case: Dict[str, Any],
        worker_id: int,
    ) -> Dict[str, Any]:
        case_id = int(case["case_id"])
        worker_paths = self._build_worker_paths(worker_id=worker_id, case_id=case_id)
        worker_paths.worker_dir.mkdir(parents=True, exist_ok=True)

        warnings: List[str] = []
        errors: List[str] = []

        try:
            runtime_values = dict(case["values"])

            if "OUTPUT_FILENAME" in self.template_loader.placeholders:
                runtime_values["OUTPUT_FILENAME"] = str(worker_paths.output_path)

            rendered_input = self.renderer.render(runtime_values)
            worker_paths.input_path.write_text(rendered_input, encoding="utf-8")

            run_info = self.simulation_runner.run(
                case_id=case_id,
                worker_id=worker_id,
                worker_dir=worker_paths.worker_dir,
                input_path=worker_paths.input_path,
                output_path=worker_paths.output_path,
            )

            return_code = int(run_info["return_code"])

            parsed: Dict[str, Any] = {}
            if worker_paths.output_path.exists():
                try:
                    parsed = self.output_parser.parse(
                        worker_paths.output_path,
                        self.config.parsing,
                    )
                except Exception as exc:
                    errors.append(str(exc))
            else:
                msg = f"output file missing: {worker_paths.output_path}"
                warnings.append(msg)
                if return_code == 0:
                    errors.append(msg)

            if return_code != 0:
                errors.append(f"physics executable failed with return code {return_code}")

            return {
                "case_id": case_id,
                "worker_id": worker_id,
                "worker_dir": worker_paths.worker_dir,
                "input_path": worker_paths.input_path,
                "output_path": worker_paths.output_path,
                "return_code": return_code,
                "stdout_path": run_info["stdout_path"],
                "stderr_path": run_info["stderr_path"],
                "parsed": parsed,
                "warnings": warnings,
                "errors": errors,
            }

        except Exception as exc:
            errors.append(str(exc))
            return {
                "case_id": case_id,
                "worker_id": worker_id,
                "worker_dir": worker_paths.worker_dir,
                "input_path": worker_paths.input_path,
                "output_path": worker_paths.output_path,
                "return_code": -1,
                "stdout_path": worker_paths.worker_dir / f"case_{case_id:05d}.stdout.log",
                "stderr_path": worker_paths.worker_dir / f"case_{case_id:05d}.stderr.log",
                "parsed": {},
                "warnings": warnings,
                "errors": errors,
            }

    def _build_worker_paths(self, worker_id: int, case_id: int) -> WorkerPaths:
        root = Path(self.config.execution.worker_dir_root)
        worker_dir = root / f"thread_{worker_id:02d}"

        input_path = self._build_case_input_path(worker_dir, case_id)
        output_path = self._build_case_output_path(worker_dir, case_id)

        return WorkerPaths(
            worker_id=worker_id,
            worker_dir=worker_dir,
            input_path=input_path,
            output_path=output_path,
        )

    def _build_case_input_path(self, worker_dir: Path, case_id: int) -> Path:
        base = self.config.paths.generated_input_file
        stem = base.stem or "generated_input"
        suffix = base.suffix or ".in"
        return worker_dir / f"{stem}_case_{case_id:05d}{suffix}"

    def _build_case_output_path(self, worker_dir: Path, case_id: int) -> Path:
        base = self.config.paths.physics_output_file
        stem = base.stem or "physics_output"
        suffix = base.suffix or ".txt"
        return worker_dir / f"{stem}_case_{case_id:05d}{suffix}"

    def _write_results_file(self, records: List[Dict[str, Any]]) -> None:
        results_file = self.config.paths.results_file
        results_file.parent.mkdir(parents=True, exist_ok=True)
        results_file.write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _cleanup_worker_dirs(self, worker_count: int) -> None:
        root = Path(self.config.execution.worker_dir_root)
        for worker_id in range(1, worker_count + 1):
            worker_dir = root / f"thread_{worker_id:02d}"
            shutil.rmtree(worker_dir, ignore_errors=True)
