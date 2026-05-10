"""
main.py — entry point for the orchestrator simulation pipeline.

Usage:
    python -m orchestrator.main                        # uses control.json in the current directory
    python -m orchestrator.main control.json           # explicit control file
    python -m orchestrator.main --help
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from orchestrator import (
    ControlConfig,
    ControlError,
    TemplateError,
    WorkflowOrchestrator,
)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Run the orchestrator simulation pipeline.",
    )
    parser.add_argument(
        "control_file",
        nargs="?",
        default="control.json",
        help="Path to the JSON control file (default: control.json)",
    )
    return parser


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_header(logger: logging.Logger, control_path: Path, config: ControlConfig) -> None:
    logger.info("orchestrator")
    logger.info("Control file : %s", control_path)
    logger.info("Mode         : %s", config.execution.mode)
    logger.info("Max cases    : %s", config.execution.max_cases)
    logger.info("Random seed  : %s", config.execution.random_seed)
    logger.info("Max threads  : %s", config.execution.max_cpu_threads)
    logger.info("Template     : %s", config.paths.template_file)
    logger.info("Results      : %s", config.paths.results_file)


def _log_summary(logger: logging.Logger, records: list, elapsed: float) -> None:
    total   = len(records)
    success = sum(1 for r in records if r.get("success"))
    failed  = total - success

    logger.info("Run complete")
    logger.info("Total cases : %s", total)
    logger.info("Succeeded   : %s", success)
    logger.info("Failed      : %s", failed)
    logger.info("Elapsed     : %.1fs", elapsed)

    if failed:
        logger.warning("%s case(s) with errors", failed)
        for r in records:
            if not r.get("success"):
                errs = r.get("errors")
                if isinstance(errs, list) and errs:
                    short = str(errs[0])[:80]
                elif isinstance(errs, str):
                    short = errs[:80]
                else:
                    short = "unknown error"
                case_id = r.get("case_id", "N/A")
                logger.warning("case %5s %s", case_id, short)


def _configure_file_logging(log_file: Path, log_level: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    control_path = Path(args.control_file)

    _configure_file_logging(Path("orchestrator.log"), "INFO")

    try:
        config = ControlConfig.load_json(control_path)
    except FileNotFoundError:
        logging.getLogger(__name__).error("control file not found: %s", control_path)
        return 1
    except ControlError as exc:
        logging.getLogger(__name__).error("invalid control file: %s", exc)
        return 1
    log_file = Path(config.execution.log_file)
    _configure_file_logging(log_file, config.execution.log_level)
    logger = logging.getLogger(__name__)
    logger.info("orchestrator starting with control file: %s", control_path)

    try:
        orchestrator = WorkflowOrchestrator.from_config(config, logger=logger)
    except (TemplateError, ControlError) as exc:
        logger.error("configuration failed: %s", exc)
        return 1

    _log_header(logger, control_path, config)
    logger.info("Template placeholders : %s", sorted(orchestrator.template_loader.placeholders))
    logger.info("Starting simulation runs")
    t0 = time.monotonic()

    try:
        records = orchestrator.run()
    except ControlError as exc:
        logger.error("pipeline failed: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("simulation interrupted by user")
        return 130

    _log_summary(logger, records, time.monotonic() - t0)
    logger.info(
        "run complete: total=%d succeeded=%d failed=%d",
        len(records),
        sum(1 for r in records if r.get("success")),
        sum(1 for r in records if not r.get("success")),
    )
    return 1 if any(not r.get("success") for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
