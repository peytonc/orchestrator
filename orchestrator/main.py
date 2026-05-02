"""
main.py — entry point for the orchestrator simulation pipeline.

Usage:
    python main.py                        # uses control.json in the current directory
    python main.py control.json           # explicit control file
    python main.py --help
"""

from __future__ import annotations

import argparse
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

def _print_header(control_path: Path, config: ControlConfig) -> None:
    print("=" * 60)
    print("  orchestrator")
    print("=" * 60)
    print(f"  Control file : {control_path}")
    print(f"  Mode         : {config.execution.mode}")
    print(f"  Max cases    : {config.execution.max_cases}")
    print(f"  Random seed  : {config.execution.random_seed}")
    print(f"  Max threads  : {config.execution.max_cpu_threads}")
    print(f"  Template     : {config.paths.template_file}")
    print(f"  Results      : {config.paths.results_file}")
    print("=" * 60)


def _print_summary(records: list, elapsed: float) -> None:
    total   = len(records)
    success = sum(1 for r in records if r.get("success"))
    failed  = total - success

    print()
    print("=" * 60)
    print("  Run complete")
    print("=" * 60)
    print(f"  Total cases : {total}")
    print(f"  Succeeded   : {success}")
    print(f"  Failed      : {failed}")
    print(f"  Elapsed     : {elapsed:.1f}s")

    if failed:
        print()
        print(f"  {failed} case(s) with errors:")
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
                print(f"    case {case_id:>5}  {short}")

    print("=" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    control_path = Path(args.control_file)

    try:
        config = ControlConfig.load_json(control_path)
    except FileNotFoundError:
        print(f"[error] control file not found: {control_path}", file=sys.stderr)
        return 1
    except ControlError as exc:
        print(f"[error] invalid control file: {exc}", file=sys.stderr)
        return 1

    try:
        orchestrator = WorkflowOrchestrator.from_config(config)
    except (TemplateError, ControlError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    _print_header(control_path, config)
    print(f"  Template placeholders : {sorted(orchestrator.template_loader.placeholders)}")

    print("\n  Starting simulation runs...\n")
    t0 = time.monotonic()

    try:
        records = orchestrator.run()
    except ControlError as exc:
        print(f"\n[error] pipeline failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[warning] simulation interrupted by user.", file=sys.stderr)
        return 130

    _print_summary(records, time.monotonic() - t0)
    return 1 if any(not r.get("success") for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
