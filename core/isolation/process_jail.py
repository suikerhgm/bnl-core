"""
ProcessJail — OS-level process containment for Nexus BNL.

On Windows: uses Windows Job Objects to enforce hard limits:
  - Maximum memory per job (ProcessMemoryLimit + JobMemoryLimit)
  - Maximum concurrent processes (ActiveProcessLimit)
  - Lower priority class to reduce CPU competition
  - Kill-on-job-close so children die with the jail

On Linux: uses resource.setrlimit for RLIMIT_AS (memory) and RLIMIT_NPROC.

Neither approach limits CPU percentage directly at the kernel level on Windows
(Job Objects don't expose a CPU % cap). CPU abuse is handled by the
ResourceLimiter monitor that sends SIGKILL / TerminateProcess when the
threshold is sustained beyond a configurable window.

Usage:
    jail = ProcessJail.create(max_memory_mb=256, max_processes=8)
    jail.assign(pid)          # put process in job
    jail.set_priority_low()   # deprioritize CPU
    jail.close()              # kills all assigned processes
"""

import ctypes
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# ── Windows constants ──────────────────────────────────────────────────────────
if _IS_WINDOWS:
    import ctypes.wintypes as wt

    PROCESS_ALL_ACCESS            = 0x001FFFFF
    JOB_OBJECT_LIMIT_ACTIVE_PROC  = 0x00000008
    JOB_OBJECT_LIMIT_PROCESS_MEM  = 0x00000100
    JOB_OBJECT_LIMIT_JOB_MEM      = 0x00000200
    JOB_OBJECT_LIMIT_PRIORITY_CLS = 0x00000020
    JOB_OBJECT_LIMIT_DIE_ON_EX    = 0x00000400
    JOB_OBJECT_LIMIT_KILL_ON_CLOSE = 0x00002000

    JobObjectBasicLimitInformation    = 2
    JobObjectExtendedLimitInformation = 9

    BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
    IDLE_PRIORITY_CLASS         = 0x00000040

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit",     ctypes.c_int64),
            ("LimitFlags",             wt.DWORD),
            ("MinimumWorkingSetSize",  ctypes.c_size_t),
            ("MaximumWorkingSetSize",  ctypes.c_size_t),
            ("ActiveProcessLimit",     wt.DWORD),
            ("Affinity",               ctypes.c_void_p),
            ("PriorityClass",          wt.DWORD),
            ("SchedulingClass",        wt.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount",  ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount",   ctypes.c_uint64),
            ("WriteTransferCount",  ctypes.c_uint64),
            ("OtherTransferCount",  ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo",               IO_COUNTERS),
            ("ProcessMemoryLimit",   ctypes.c_size_t),
            ("JobMemoryLimit",       ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed",    ctypes.c_size_t),
        ]


class ProcessJail:
    """
    A jail wraps one Windows Job Object (or Linux resource limits) and exposes
    assign(pid), set_priority_low(), and close().

    Create via ProcessJail.create() — never use __init__ directly.
    """

    def __init__(self, job_handle, max_memory_mb: int, max_processes: int) -> None:
        self._job    = job_handle     # HANDLE on Windows, None on Linux
        self.max_memory_mb  = max_memory_mb
        self.max_processes  = max_processes
        self._assigned_pids = set()
        self.closed         = False

    @classmethod
    def create(
        cls,
        max_memory_mb: int = 512,
        max_processes: int = 8,
        kill_on_close: bool = True,
    ) -> "ProcessJail":
        """Create a new jail with the given resource limits."""
        if _IS_WINDOWS:
            return cls._create_windows(max_memory_mb, max_processes, kill_on_close)
        return cls._create_posix(max_memory_mb, max_processes)

    @classmethod
    def _create_windows(
        cls,
        max_memory_mb: int,
        max_processes: int,
        kill_on_close: bool,
    ) -> "ProcessJail":
        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            err = ctypes.get_last_error()
            logger.warning("[PROCESS_JAIL] CreateJobObject failed (err=%d) — running without OS limits", err)
            return cls(None, max_memory_mb, max_processes)

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = (
            JOB_OBJECT_LIMIT_ACTIVE_PROC |
            JOB_OBJECT_LIMIT_PROCESS_MEM |
            JOB_OBJECT_LIMIT_JOB_MEM     |
            JOB_OBJECT_LIMIT_PRIORITY_CLS
        )
        if kill_on_close:
            flags |= JOB_OBJECT_LIMIT_KILL_ON_CLOSE

        info.BasicLimitInformation.LimitFlags       = flags
        info.BasicLimitInformation.ActiveProcessLimit = max_processes
        info.BasicLimitInformation.PriorityClass    = BELOW_NORMAL_PRIORITY_CLASS
        info.ProcessMemoryLimit = max_memory_mb * 1024 * 1024
        info.JobMemoryLimit     = max_memory_mb * 1024 * 1024 * 2  # job-wide = 2x

        ok = kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = ctypes.get_last_error()
            logger.warning("[PROCESS_JAIL] SetInformationJobObject failed (err=%d)", err)
            kernel32.CloseHandle(job)
            return cls(None, max_memory_mb, max_processes)

        logger.info(
            "[PROCESS_JAIL] Windows Job Object created: mem=%dMB procs=%d kill_on_close=%s",
            max_memory_mb, max_processes, kill_on_close,
        )
        return cls(job, max_memory_mb, max_processes)

    @classmethod
    def _create_posix(cls, max_memory_mb: int, max_processes: int) -> "ProcessJail":
        """Linux/macOS: rlimits applied in-process or via preexec_fn."""
        logger.info(
            "[PROCESS_JAIL] POSIX jail created: mem=%dMB procs=%d",
            max_memory_mb, max_processes,
        )
        return cls(None, max_memory_mb, max_processes)

    def get_preexec_fn(self):
        """
        Return a callable to pass as preexec_fn to subprocess.Popen on Linux.
        Sets RLIMIT_AS (virtual memory) and RLIMIT_NPROC.
        Returns None on Windows.
        """
        if _IS_WINDOWS:
            return None
        import resource
        mem_bytes  = self.max_memory_mb * 1024 * 1024
        max_procs  = self.max_processes

        def _set_limits():
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except Exception:
                pass
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (max_procs, max_procs))
            except Exception:
                pass

        return _set_limits

    def assign(self, pid: int) -> bool:
        """Assign a PID to this jail (Windows only — no-op on Linux since rlimits are set at spawn)."""
        if self.closed:
            return False
        self._assigned_pids.add(pid)
        if not _IS_WINDOWS or not self._job:
            return True
        kernel32 = ctypes.windll.kernel32
        proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not proc:
            logger.warning("[PROCESS_JAIL] OpenProcess(%d) failed", pid)
            return False
        ok = bool(kernel32.AssignProcessToJobObject(self._job, proc))
        kernel32.CloseHandle(proc)
        if ok:
            logger.info("[PROCESS_JAIL] PID %d assigned to job", pid)
        else:
            logger.warning("[PROCESS_JAIL] AssignProcessToJobObject(%d) failed: err=%d",
                           pid, ctypes.get_last_error())
        return ok

    def set_priority_low(self, pid: int) -> bool:
        """Lower CPU scheduling priority for a process."""
        try:
            import psutil
            p = psutil.Process(pid)
            if _IS_WINDOWS:
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                p.nice(10)
            logger.info("[PROCESS_JAIL] Priority lowered for PID %d", pid)
            return True
        except Exception as exc:
            logger.debug("[PROCESS_JAIL] set_priority_low(%d) failed: %s", pid, exc)
            return False

    def close(self) -> None:
        """Close the job object. On Windows with kill_on_close, all assigned processes are terminated."""
        if self.closed:
            return
        self.closed = True
        if _IS_WINDOWS and self._job:
            ctypes.windll.kernel32.CloseHandle(self._job)
            logger.info("[PROCESS_JAIL] Job Object closed — %d PIDs terminated", len(self._assigned_pids))
        self._assigned_pids.clear()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
