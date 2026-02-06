#!/usr/bin/env python3
"""Memory profiling for QFC Worker - ALWAYS ENABLED for debugging."""

import gc
import logging
import tracemalloc
from contextlib import contextmanager
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

# Profiling is always enabled
MEMORY_PROFILING_ENABLED = True
MEMORY_PROFILING_DETAILED = False


class MemoryProfiler:
    """Memory profiler that tracks both Python and system memory usage.

    This profiler uses:
    - tracemalloc: Python memory allocations (built-in)
    - psutil: System RSS/VMS memory (already installed)
    - gc: Garbage collector statistics

    Usage:
        # As context manager
        with MemoryProfiler("my_operation"):
            do_something()

        # Manual
        profiler = MemoryProfiler("my_operation")
        profiler.start()
        do_something()
        profiler.stop()
    """

    def __init__(self, label: str, enabled: Optional[bool] = None):
        """Initialize memory profiler.

        Args:
            label: Descriptive label for this profiling session
            enabled: Not used, always enabled
        """
        self.label = label
        self.enabled = True
        self.process = psutil.Process()

        # Start metrics
        self.start_rss: Optional[int] = None
        self.start_vms: Optional[int] = None
        self.start_tracemalloc_current: Optional[int] = None
        self.start_tracemalloc_peak: Optional[int] = None

        # End metrics
        self.end_rss: Optional[int] = None
        self.end_vms: Optional[int] = None
        self.end_tracemalloc_current: Optional[int] = None
        self.end_tracemalloc_peak: Optional[int] = None

    def start(self) -> None:
        """Start profiling."""
        # Get memory info without forcing GC
        mem_info = self.process.memory_info()
        self.start_rss = mem_info.rss
        self.start_vms = mem_info.vms

        # Get tracemalloc info
        if tracemalloc.is_tracing():
            self.start_tracemalloc_current, self.start_tracemalloc_peak = (
                tracemalloc.get_traced_memory()
            )

        logger.info(
            f"[MEMPROF] START: {self.label}\n"
            f"  RSS: {self.start_rss / 1024 / 1024:.2f} MB\n"
            f"  VMS: {self.start_vms / 1024 / 1024:.2f} MB"
        )

        if MEMORY_PROFILING_DETAILED:
            self._log_gc_stats("START")
            self._log_qgis_objects("START")

    def stop(self) -> dict[str, str | float | None]:
        """Stop profiling and return metrics."""
        # Get memory info without forcing GC
        mem_info = self.process.memory_info()
        self.end_rss = mem_info.rss
        self.end_vms = mem_info.vms

        # Get tracemalloc info
        if tracemalloc.is_tracing():
            self.end_tracemalloc_current, self.end_tracemalloc_peak = (
                tracemalloc.get_traced_memory()
            )

        # Calculate deltas
        if self.start_rss:
            rss_delta = self.end_rss - self.start_rss
        else:
            rss_delta = 0

        if self.start_vms:
            vms_delta = self.end_vms - self.start_vms
        else:
            vms_delta = 0

        logger.info(
            f"[MEMPROF] END: {self.label}\n"
            f"  RSS: {self.end_rss / 1024 / 1024:.2f} MB "
            f"(Δ {rss_delta / 1024 / 1024:+.2f} MB)\n"
            f"  VMS: {self.end_vms / 1024 / 1024:.2f} MB "
            f"(Δ {vms_delta / 1024 / 1024:+.2f} MB)"
        )

        if MEMORY_PROFILING_DETAILED:
            self._log_gc_stats("END")
            self._log_qgis_objects("END")
            if tracemalloc.is_tracing():
                self._log_tracemalloc_top()

        result: dict[str, str | float | None] = {"label": self.label}

        if self.start_rss:
            result["rss_start_mb"] = self.start_rss / 1024 / 1024
            result["rss_delta_mb"] = rss_delta / 1024 / 1024
        else:
            result["rss_start_mb"] = None
            result["rss_delta_mb"] = None

        if self.end_rss:
            result["rss_end_mb"] = self.end_rss / 1024 / 1024
        else:
            result["rss_end_mb"] = None

        if self.start_vms:
            result["vms_delta_mb"] = vms_delta / 1024 / 1024
        else:
            result["vms_delta_mb"] = None

        return result

    def checkpoint(self, checkpoint_label: str) -> None:
        """Log a memory checkpoint without stopping profiling."""
        mem_info = self.process.memory_info()

        if self.start_rss:
            rss_delta = mem_info.rss - self.start_rss
        else:
            rss_delta = 0

        logger.info(
            f"[MEMPROF] CHECKPOINT: {self.label} - {checkpoint_label}\n"
            f"  RSS: {mem_info.rss / 1024 / 1024:.2f} MB "
            f"(Δ {rss_delta / 1024 / 1024:+.2f} MB from start)"
        )

    def _log_gc_stats(self, stage: str) -> None:
        """Log garbage collector statistics."""
        stats = gc.get_stats()
        counts = gc.get_count()

        logger.debug(
            f"[MEMPROF] GC Stats ({stage}): {self.label}\n"
            f"  Counts (gen0, gen1, gen2): {counts}\n"
            f"  Collections: {stats}"
        )

    def _log_qgis_objects(self, stage: str) -> None:
        """Log counts of QGIS objects in memory."""
        try:
            from qgis.core import QgsMapLayer, QgsMapSettings, QgsProject

            all_objects = gc.get_objects()
            projects = sum(1 for obj in all_objects if isinstance(obj, QgsProject))
            layers = sum(1 for obj in all_objects if isinstance(obj, QgsMapLayer))
            map_settings = sum(
                1 for obj in all_objects if isinstance(obj, QgsMapSettings)
            )

            logger.debug(
                f"[MEMPROF] QGIS Objects ({stage}): {self.label}\n"
                f"  QgsProject instances: {projects}\n"
                f"  QgsMapLayer instances: {layers}\n"
                f"  QgsMapSettings instances: {map_settings}"
            )
        except ImportError:
            pass

    def _log_tracemalloc_top(self, limit: int = 10) -> None:
        """Log top memory allocations from tracemalloc."""
        if not tracemalloc.is_tracing():
            return

        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics("lineno")

        logger.debug(f"[MEMPROF] Top {limit} memory allocations: {self.label}")
        for index, stat in enumerate(top_stats[:limit], 1):
            logger.debug(f"  #{index}: {stat}")

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False


@contextmanager
def profile_memory(label: str, enabled: Optional[bool] = None):
    """Context manager for memory profiling.

    Args:
        label: Descriptive label for this profiling session
        enabled: Not used, always enabled
    """
    profiler = MemoryProfiler(label)
    profiler.start()
    try:
        yield profiler
    finally:
        profiler.stop()


def init_memory_profiling() -> None:
    """Initialize memory profiling at application startup."""
    logger.info("[MEMPROF] ========================================")
    logger.info("[MEMPROF] Memory profiling ENABLED")
    logger.info("[MEMPROF] ========================================")
    if not tracemalloc.is_tracing():
        tracemalloc.start()
        logger.info("[MEMPROF] tracemalloc started")


def log_current_memory(label: str) -> None:
    """Quick utility to log current memory usage."""
    process = psutil.Process()
    mem_info = process.memory_info()

    logger.info(
        f"[MEMPROF] {label}: "
        f"RSS: {mem_info.rss / 1024 / 1024:.2f} MB, "
        f"VMS: {mem_info.vms / 1024 / 1024:.2f} MB"
    )
