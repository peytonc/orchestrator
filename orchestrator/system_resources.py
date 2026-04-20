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


class SystemResourceDetector:
    """
    Best-effort physical-core detection using only the standard library.
    Falls back safely when a platform-specific method is unavailable.
    """

    @staticmethod
    def physical_core_count() -> int:
        system = platform.system().lower()

        try:
            if system == "linux":
                value = SystemResourceDetector._linux_physical_cores()
                if value:
                    return value
            elif system == "darwin":
                value = SystemResourceDetector._mac_physical_cores()
                if value:
                    return value
            elif system == "windows":
                value = SystemResourceDetector._windows_physical_cores()
                if value:
                    return value
        except Exception:
            pass

        fallback = os.cpu_count() or 1
        return max(1, fallback)

    @staticmethod
    def recommended_worker_count(requested: int, case_count: int) -> int:
        requested = max(1, int(requested))
        case_count = max(1, int(case_count))

        physical = SystemResourceDetector.physical_core_count()
        safe_physical = max(1, physical - 2) if physical > 2 else 1

        return max(1, min(requested, safe_physical, case_count))

    @staticmethod
    def _linux_physical_cores() -> Optional[int]:
        cpuinfo = Path("/proc/cpuinfo")
        if not cpuinfo.exists():
            return None

        text = cpuinfo.read_text(encoding="utf-8", errors="replace")
        physical_ids = set()

        current_physical_id = None
        current_core_id = None

        def flush() -> None:
            nonlocal current_physical_id, current_core_id
            if current_physical_id is not None and current_core_id is not None:
                physical_ids.add((current_physical_id, current_core_id))
            current_physical_id = None
            current_core_id = None

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                flush()
                continue

            if stripped.startswith("physical id"):
                current_physical_id = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("core id"):
                current_core_id = stripped.split(":", 1)[1].strip()

        flush()

        if physical_ids:
            return len(physical_ids)
        return None

    @staticmethod
    def _mac_physical_cores() -> Optional[int]:
        try:
            proc = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True,
                text=True,
                shell=False,
                check=False,
            )
            value = int(proc.stdout.strip())
            return value if value > 0 else None
        except Exception:
            return None

    @staticmethod
    def _windows_physical_cores() -> Optional[int]:
        commands = [
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum",
            ],
            [
                "wmic",
                "cpu",
                "get",
                "NumberOfCores",
            ],
        ]

        for cmd in commands:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    shell=False,
                    check=False,
                )
                text = proc.stdout.strip()

                if not text:
                    continue

                if "NumberOfCores" in text:
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    nums = []
                    for line in lines:
                        if line.isdigit():
                            nums.append(int(line))
                    if nums:
                        total = sum(nums)
                        return total if total > 0 else None
                else:
                    value = int(text.splitlines()[-1].strip())
                    return value if value > 0 else None
            except Exception:
                continue

        return None
