from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from queue import Queue
from typing import Any, Dict, Iterator, List
import shutil

from .cases import CaseGenerator
from .config import ControlConfig, ControlError
from .parser import OutputParser
from .render import Renderer
from .results import ResultCollector
from .runner import SimulationRunner
from .system_resources import SystemResourceDetector
from .template import TemplateLoader


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
      - execute the black-box executable
      - parse outputs
      - collect and write final results
    """

    def __init__(
        self,
        config: ControlConfig,
        template_loader: TemplateLoader,
        case_generator: CaseGenerator,
        simulation_runner: SimulationRunner,
        output_parser: OutputParser,
        result_collector: ResultCollector,
    ) -> None:
        self.config = config
        self.template_loader = template_loader
        self.case_generator = case_generator
        self.simulation_runner = simulation_runner
        self.output_parser = output_parser
        self.result_collector = result_collector

        self._slot_queue: Queue[int] = Queue()

    @classmethod
    def from_config(
        cls,
        config: ControlConfig,
        timeout_seconds: float | None = None,
    ) -> "WorkflowOrchestrator":
        template_loader = TemplateLoader(config.paths.template_file).load()
        if not template_loader.text:
            raise ControlError("template file is empty")
        config.validate_against_template(template_loader.placeholders)

        return cls(
            config=config,
            template_loader=template_loader,
            case_generator=CaseGenerator(config),
            simulation_runner=SimulationRunner(
                physics_command=config.paths.physics_command,
                timeout_seconds=timeout_seconds,
            ),
            output_parser=OutputParser(),
            result_collector=ResultCollector(),
        )

    def run(self) -> List[Dict[str, Any]]:
        if not self.template_loader.text:
            raise ControlError(
                "template not loaded; use WorkflowOrchestrator.from_config "
                "or call template_loader.load() before run()"
            )

        renderer = Renderer(self.template_loader.text)
        self.result_collector.clear()

        case_iter = self.case_generator.iter_cases()
        first_case = next(case_iter, None)
        if first_case is None:
            raise ControlError("no cases were generated")
        case_iter = chain([first_case], case_iter)

        worker_count = SystemResourceDetector.recommended_worker_count(
            requested=self.config.execution.max_cpu_threads,
            case_count=self.config.execution.max_cases,
            prefer_physical_cores=self.config.execution.prefer_physical_cores,
        )

        if worker_count <= 1:
            self._run_serial(case_iter=case_iter, renderer=renderer)
        else:
            self._run_parallel(case_iter=case_iter, worker_count=worker_count, renderer=renderer)

        records = self.result_collector.to_list()
        records.sort(key=lambda item: item["case_id"])

        self.result_collector.write_json(self.config.paths.results_file)

        if not self.config.execution.preserve_workdirs:
            self._cleanup_worker_dirs(worker_count)

        return records

    def _run_serial(self, case_iter: Iterator[Dict[str, Any]], renderer: Renderer) -> None:
        for case in case_iter:
            record = self._execute_case_in_worker_slot(case, worker_id=1, renderer=renderer)
            self.result_collector.add(**record)

    def _run_parallel(
        self,
        case_iter: Iterator[Dict[str, Any]],
        worker_count: int,
        renderer: Renderer,
    ) -> None:
        self._slot_queue = Queue()
        for worker_id in range(1, worker_count + 1):
            self._slot_queue.put(worker_id)

        in_flight: dict[Any, None] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for _ in range(worker_count):
                case = next(case_iter, None)
                if case is None:
                    break
                future = executor.submit(self._run_single_case, case, renderer)
                in_flight[future] = None

            completion_stream = as_completed(in_flight)
            while in_flight:
                done_future = next(completion_stream)
                del in_flight[done_future]

                record = done_future.result()
                self.result_collector.add(**record)

                next_case = next(case_iter, None)
                if next_case is not None:
                    next_future = executor.submit(self._run_single_case, next_case, renderer)
                    in_flight[next_future] = None
                    completion_stream = as_completed(in_flight)

    def _run_single_case(self, case: Dict[str, Any], renderer: Renderer) -> Dict[str, Any]:
        worker_id = self._acquire_worker_id()
        try:
            return self._execute_case_in_worker_slot(case, worker_id, renderer)
        finally:
            self._slot_queue.put(worker_id)

    def _acquire_worker_id(self) -> int:
        return self._slot_queue.get()

    def _execute_case_in_worker_slot(
        self,
        case: Dict[str, Any],
        worker_id: int,
        renderer: Renderer,
    ) -> Dict[str, Any]:
        case_id = int(case["case_id"])
        worker_paths = self._build_worker_paths(worker_id=worker_id, case_id=case_id)

        warnings: List[str] = []
        errors: List[str] = []

        try:
            worker_paths.worker_dir.mkdir(parents=True, exist_ok=True)
            runtime_values = dict(case["values"])

            rendered_input = renderer.render(runtime_values)
            worker_paths.input_path.write_text(rendered_input, encoding="utf-8")

            run_info = self.simulation_runner.run(
                case_id=case_id,
                worker_id=worker_id,
                worker_dir=worker_paths.worker_dir,
                input_path=worker_paths.input_path,
                output_path=worker_paths.output_path,
            )

            return_code = int(run_info.return_code)
            errors.extend(run_info.errors)
            warnings.extend(run_info.warnings)

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
                if return_code == 0:
                    errors.append(msg)
                else:
                    warnings.append(msg)

            if return_code != 0 and not run_info.errors:
                errors.append(f"physics executable failed with return code {return_code}")

            return {
                "case_id": case_id,
                "worker_id": worker_id,
                "worker_dir": worker_paths.worker_dir,
                "input_path": worker_paths.input_path,
                "output_path": worker_paths.output_path,
                "return_code": return_code,
                "stdout_path": run_info.stdout_path,
                "stderr_path": run_info.stderr_path,
                "parsed": parsed,
                "warnings": warnings,
                "errors": errors,
            }

        except (ControlError, OSError) as exc:
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

    def _cleanup_worker_dirs(self, worker_count: int) -> None:
        root = Path(self.config.execution.worker_dir_root)
        for worker_id in range(1, worker_count + 1):
            worker_dir = root / f"thread_{worker_id:02d}"
            shutil.rmtree(worker_dir, ignore_errors=True)
