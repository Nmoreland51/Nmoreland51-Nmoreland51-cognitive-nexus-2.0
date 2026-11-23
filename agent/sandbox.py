"""Run a program for the agent with limits the operating system enforces.

What is enforced, and by what:

Windows
  * Writes: the program runs at Low integrity level, so Windows refuses any write outside folders
    labelled Low. Only the task's workspace is labelled. (Reading other files is still possible.)
  * Memory, number of processes, lifetime: a Job Object. Everything the program starts is in the
    job and dies with it; a time limit or a cancel ends the whole tree.
Linux and macOS
  * Memory and CPU time: resource limits set before the program starts, and its own process
    group, which is killed as a whole on a time limit or cancel. The number of processes is not
    limited there.
  * Writes are NOT confined by the operating system here.
Everywhere
  * A clean environment: no API keys or tokens, and home, temp and cache folders redirected into
    the workspace.
  * No shell: the program gets a list of arguments, so there are no pipes, redirects or
    command substitution to abuse.
  * Network access is NOT blocked by the operating system. With allow_network=False the proxy
    variables point at a closed port, which stops well-behaved tools (pip, requests, git) and
    nothing else. Do not run code here that you would not run at all.

isolation_report() says which of these are available on this machine; every result carries the
same record of what was enforced for that run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"
TEMP_FOLDER = ".agent_tmp"
HOME_FOLDER = ".agent_home"
# Variables a program needs to start at all. Everything else, including every key and token, is left out.
_PASSED_THROUGH = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "VIRTUAL_ENV",
)  # fmt: skip
_CLOSED_PROXY = "http://127.0.0.1:9"


class SandboxError(Exception):
    """The program could not be started under the requested limits."""


@dataclass(frozen=True)
class Limits:
    seconds: float = 300.0  # wall-clock time before the whole process tree is ended
    memory_mb: int = 2048  # all processes of the run together
    processes: int = 64
    output_chars: int = 200_000  # kept per stream; the middle is dropped beyond this


@dataclass
class RunResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    seconds: float
    stopped: str = ""  # "" (ended by itself), "timeout" or "cancelled"
    truncated: bool = False
    peak_memory_mb: float | None = None
    isolation: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.stopped

    def combined(self) -> str:
        return self.stdout + (("\n" if self.stdout and not self.stdout.endswith("\n") else "") + self.stderr if self.stderr else "")


def clean_environment(workspace: Path, *, allow_network: bool = False, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a sandboxed program gets: the minimum to start, with home and temp inside the workspace."""

    workspace = Path(workspace).resolve()
    home, temp = workspace / HOME_FOLDER, workspace / TEMP_FOLDER
    env = {name: os.environ[name] for name in os.environ if name.upper() in _PASSED_THROUGH}
    env.update(
        {
            "TEMP": str(temp), "TMP": str(temp), "TMPDIR": str(temp),
            "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"), "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_CONFIG_HOME": str(home / ".config"), "PYTHONUSERBASE": str(home / ".pythonuser"),
            "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "GIT_TERMINAL_PROMPT": "0", "NO_COLOR": "1",
            "CI": "1",
        }
    )  # fmt: skip
    if not allow_network:
        # Not a barrier: it only stops programs that honour proxy settings.
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env[name] = _CLOSED_PROXY
        env["PIP_NO_INDEX"] = "1"
    env.update(extra or {})
    return env


def prepare_workspace(workspace: Path) -> dict[str, Any]:
    """Make a folder usable as a sandbox: create the redirected home and temp, and on Windows label
    the whole folder Low so a confined program can write there (and nowhere else)."""

    workspace = Path(workspace).resolve()
    for folder in (workspace, workspace / TEMP_FOLDER, workspace / HOME_FOLDER):
        folder.mkdir(parents=True, exist_ok=True)
    labelled = False
    if IS_WINDOWS:
        done = subprocess.run(
            ["icacls", str(workspace), "/setintegritylevel", "(OI)(CI)L", "/T", "/C", "/Q"],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )  # fmt: skip
        labelled = done.returncode == 0
    return {"workspace": str(workspace), "labelled_low": labelled}


def _keep(chunks: list[bytes], limit: int) -> tuple[str, bool]:
    text = b"".join(chunks).decode("utf-8", errors="replace").replace("\r\n", "\n")
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - 2 * half:,} characters left out ...]\n{text[-half:]}", True


class _Collector(threading.Thread):
    """Read a stream to its end without holding more than a bounded amount of it."""

    def __init__(self, stream: Any, limit: int) -> None:
        super().__init__(daemon=True)
        self.stream, self.limit = stream, limit
        self.head: list[bytes] = []
        self.tail: list[bytes] = []
        self.head_size = self.tail_size = 0
        self.dropped = 0

    def run(self) -> None:
        try:
            while True:
                chunk = self.stream.read(65536)
                if not chunk:
                    break
                if self.head_size < self.limit * 2:
                    self.head.append(chunk)
                    self.head_size += len(chunk)
                    continue
                self.tail.append(chunk)
                self.tail_size += len(chunk)
                while self.tail_size - len(self.tail[0]) > self.limit * 2:
                    self.dropped += len(self.tail[0])
                    self.tail_size -= len(self.tail.pop(0))
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.stream.close()
            except OSError:
                pass

    def text(self) -> tuple[str, bool]:
        if not self.tail:
            return _keep(self.head, self.limit)
        text, _ = _keep(self.head + [f"\n[... {self.dropped:,} bytes left out ...]\n".encode()] + self.tail, self.limit)
        return text, True


# ---- Windows ---------------------------------------------------------------------------------

_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt
    import msvcrt

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _launch_lock = threading.Lock()  # so one launch cannot inherit another launch's pipe handles

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]

    class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", _SID_AND_ATTRIBUTES)]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
            ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
            ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
            ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD), ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE),
        ]  # fmt: skip

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]

    class _SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wt.BOOL)]

    class _BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wt.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD),
            ("SchedulingClass", wt.DWORD),
        ]  # fmt: skip

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

    class _EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMITS), ("IoInfo", _IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]  # fmt: skip

    _JOB_KILL_ON_CLOSE, _JOB_MEMORY, _JOB_ACTIVE_PROCESS, _JOB_DIE_ON_EXCEPTION = 0x2000, 0x200, 0x8, 0x400
    _EXTENDED_LIMIT_INFORMATION = 9
    _CREATE_SUSPENDED, _CREATE_UNICODE_ENVIRONMENT = 0x4, 0x400
    _STARTF_USESTDHANDLES, _HANDLE_FLAG_INHERIT = 0x100, 1
    _LOW_INTEGRITY_SID = "S-1-16-4096"

    def _declare(library: Any, name: str, restype: Any, *argtypes: Any) -> None:
        function = getattr(library, name)
        function.restype, function.argtypes = restype, list(argtypes)

    _P = ctypes.POINTER
    _declare(_advapi32, "OpenProcessToken", wt.BOOL, wt.HANDLE, wt.DWORD, _P(wt.HANDLE))
    _declare(_advapi32, "DuplicateTokenEx", wt.BOOL, wt.HANDLE, wt.DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, _P(wt.HANDLE))
    _declare(_advapi32, "ConvertStringSidToSidW", wt.BOOL, wt.LPCWSTR, _P(ctypes.c_void_p))
    _declare(_advapi32, "SetTokenInformation", wt.BOOL, wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD)
    _declare(_advapi32, "GetLengthSid", wt.DWORD, ctypes.c_void_p)
    _declare(
        _advapi32, "CreateProcessAsUserW", wt.BOOL, wt.HANDLE, wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL,
        wt.DWORD, ctypes.c_void_p, wt.LPCWSTR, _P(_STARTUPINFOW), _P(_PROCESS_INFORMATION),
    )  # fmt: skip
    _declare(
        _kernel32, "CreateProcessW", wt.BOOL, wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
        ctypes.c_void_p, wt.LPCWSTR, _P(_STARTUPINFOW), _P(_PROCESS_INFORMATION),
    )  # fmt: skip
    _declare(_kernel32, "GetCurrentProcess", wt.HANDLE)
    _declare(_kernel32, "CreatePipe", wt.BOOL, _P(wt.HANDLE), _P(wt.HANDLE), _P(_SECURITY_ATTRIBUTES), wt.DWORD)
    _declare(_kernel32, "SetHandleInformation", wt.BOOL, wt.HANDLE, wt.DWORD, wt.DWORD)
    _declare(_kernel32, "CreateFileW", wt.HANDLE, wt.LPCWSTR, wt.DWORD, wt.DWORD, _P(_SECURITY_ATTRIBUTES), wt.DWORD, wt.DWORD, wt.HANDLE)
    _declare(_kernel32, "ResumeThread", wt.DWORD, wt.HANDLE)
    _declare(_kernel32, "WaitForSingleObject", wt.DWORD, wt.HANDLE, wt.DWORD)
    _declare(_kernel32, "GetExitCodeProcess", wt.BOOL, wt.HANDLE, _P(wt.DWORD))
    _declare(_kernel32, "CloseHandle", wt.BOOL, wt.HANDLE)
    _declare(_kernel32, "LocalFree", ctypes.c_void_p, ctypes.c_void_p)
    _declare(_kernel32, "CreateJobObjectW", wt.HANDLE, ctypes.c_void_p, wt.LPCWSTR)
    _declare(_kernel32, "SetInformationJobObject", wt.BOOL, wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD)
    _declare(_kernel32, "QueryInformationJobObject", wt.BOOL, wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, _P(wt.DWORD))
    _declare(_kernel32, "AssignProcessToJobObject", wt.BOOL, wt.HANDLE, wt.HANDLE)
    _declare(_kernel32, "TerminateJobObject", wt.BOOL, wt.HANDLE, wt.UINT)

    def _fail(what: str) -> SandboxError:
        return SandboxError(f"{what} failed: {ctypes.WinError(ctypes.get_last_error())}")

    def _low_integrity_token() -> Any:
        """A copy of this process's token at Low integrity: what it starts cannot write to the user's files."""

        token, low, sid = wt.HANDLE(), wt.HANDLE(), ctypes.c_void_p()
        if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(), 0x0002 | 0x0008 | 0x0080 | 0x0001, ctypes.byref(token)):
            raise _fail("OpenProcessToken")
        try:
            if not _advapi32.DuplicateTokenEx(token, 0x02000000, None, 2, 1, ctypes.byref(low)):
                raise _fail("DuplicateTokenEx")
            if not _advapi32.ConvertStringSidToSidW(_LOW_INTEGRITY_SID, ctypes.byref(sid)):
                raise _fail("ConvertStringSidToSid")
            try:
                label = _TOKEN_MANDATORY_LABEL()
                label.Label.Sid, label.Label.Attributes = sid, 0x20
                if not _advapi32.SetTokenInformation(low, 25, ctypes.byref(label), ctypes.sizeof(label) + _advapi32.GetLengthSid(sid)):
                    raise _fail("SetTokenInformation")
            finally:
                _kernel32.LocalFree(sid)
        except SandboxError:
            if low:
                _kernel32.CloseHandle(low)
            raise
        finally:
            _kernel32.CloseHandle(token)
        return low

    def _job(limits: Limits) -> Any:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            raise _fail("CreateJobObject")
        info = _EXTENDED_LIMITS()
        info.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE | _JOB_MEMORY | _JOB_ACTIVE_PROCESS | _JOB_DIE_ON_EXCEPTION
        info.BasicLimitInformation.ActiveProcessLimit = max(1, int(limits.processes))
        info.JobMemoryLimit = max(16, int(limits.memory_mb)) * 1024 * 1024
        if not _kernel32.SetInformationJobObject(job, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
            _kernel32.CloseHandle(job)
            raise _fail("SetInformationJobObject")
        return job

    def _run_windows(argv: list[str], cwd: Path, env: dict[str, str], limits: Limits, confine_writes: bool, cancel: threading.Event | None) -> RunResult:
        inherit = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
        started = time.perf_counter()
        job = _job(limits)
        token = None
        process = _PROCESS_INFORMATION()
        readers: list[_Collector] = []
        try:
            if confine_writes:
                token = _low_integrity_token()
            with _launch_lock:
                pipes = []
                for _stream in range(2):
                    read_end, write_end = wt.HANDLE(), wt.HANDLE()
                    if not _kernel32.CreatePipe(ctypes.byref(read_end), ctypes.byref(write_end), ctypes.byref(inherit), 0):
                        raise _fail("CreatePipe")
                    _kernel32.SetHandleInformation(read_end, _HANDLE_FLAG_INHERIT, 0)
                    pipes.append((read_end, write_end))
                nul = _kernel32.CreateFileW("NUL", 0x80000000, 3, ctypes.byref(inherit), 3, 0, None)
                startup = _STARTUPINFOW()
                startup.cb = ctypes.sizeof(startup)
                startup.dwFlags = _STARTF_USESTDHANDLES
                startup.hStdInput, startup.hStdOutput, startup.hStdError = nul, pipes[0][1], pipes[1][1]
                command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
                block = ctypes.create_unicode_buffer("".join(f"{name}={value}\0" for name, value in sorted(env.items())) + "\0")
                flags = _CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT | _NO_WINDOW
                if token is not None:
                    created = _advapi32.CreateProcessAsUserW(
                        token, None, command, None, None, True, flags, block, str(cwd), ctypes.byref(startup), ctypes.byref(process)
                    )
                else:
                    created = _kernel32.CreateProcessW(None, command, None, None, True, flags, block, str(cwd), ctypes.byref(startup), ctypes.byref(process))
                error = ctypes.get_last_error()
                for _read_end, write_end in pipes:
                    _kernel32.CloseHandle(write_end)
                _kernel32.CloseHandle(nul)
                if not created:
                    for read_end, _write_end in pipes:
                        _kernel32.CloseHandle(read_end)
                    raise SandboxError(f"Could not start {argv[0]!r}: {ctypes.WinError(error)}")
            for read_end, _write_end in pipes:
                reader = _Collector(os.fdopen(msvcrt.open_osfhandle(int(read_end.value or 0), os.O_RDONLY), "rb"), limits.output_chars)
                reader.start()
                readers.append(reader)
            # The process is still suspended: put it in the job before it can run or start anything.
            if not _kernel32.AssignProcessToJobObject(job, process.hProcess):
                _kernel32.TerminateJobObject(job, 1)
                raise _fail("AssignProcessToJobObject")
            _kernel32.ResumeThread(process.hThread)
            stopped = ""
            deadline = started + limits.seconds
            while _kernel32.WaitForSingleObject(process.hProcess, 100) != 0:
                if cancel is not None and cancel.is_set():
                    stopped = "cancelled"
                elif time.perf_counter() >= deadline:
                    stopped = "timeout"
                if stopped:
                    _kernel32.TerminateJobObject(job, 1)
                    _kernel32.WaitForSingleObject(process.hProcess, 5000)
                    break
            code = wt.DWORD()
            _kernel32.GetExitCodeProcess(process.hProcess, ctypes.byref(code))
            # Children of the program may still hold the pipes open; end them so reading can finish.
            _kernel32.TerminateJobObject(job, 1)
            for reader in readers:
                reader.join(5)
            info = _EXTENDED_LIMITS()
            peak = None
            if _kernel32.QueryInformationJobObject(job, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None):
                peak = round(info.PeakJobMemoryUsed / (1024 * 1024), 1)
            (stdout, cut_out), (stderr, cut_err) = readers[0].text(), readers[1].text()
            return RunResult(
                argv=list(argv),
                exit_code=None if stopped else ctypes.c_int32(code.value).value,
                stdout=stdout,
                stderr=stderr,
                seconds=round(time.perf_counter() - started, 3),
                stopped=stopped,
                truncated=cut_out or cut_err,
                peak_memory_mb=peak,
            )
        finally:
            for handle in (process.hThread, process.hProcess, token, job):
                if handle:
                    _kernel32.CloseHandle(handle)


# ---- Linux, macOS ------------------------------------------------------------------------------

else:

    def _run_posix(argv: list[str], cwd: Path, env: dict[str, str], limits: Limits, cancel: threading.Event | None) -> RunResult:
        import resource
        import signal

        def set_limits() -> None:
            memory = max(16, int(limits.memory_mb)) * 1024 * 1024
            # No RLIMIT_NPROC: it counts every process of the user, not this run's, so it would
            # either do nothing or stop the program from starting on a busy machine.
            for name, value in (("RLIMIT_AS", memory), ("RLIMIT_CPU", int(limits.seconds) + 5)):
                limit = getattr(resource, name, None)
                if limit is None:
                    continue
                try:
                    _soft, hard = resource.getrlimit(limit)
                    wanted = value if hard == resource.RLIM_INFINITY else min(value, hard)
                    resource.setrlimit(limit, (wanted, hard))
                except (ValueError, OSError):
                    pass

        started = time.perf_counter()
        try:
            process = subprocess.Popen(
                argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, preexec_fn=set_limits,
            )  # fmt: skip
        except OSError as exc:
            raise SandboxError(f"Could not start {argv[0]!r}: {exc}") from exc
        readers = [_Collector(process.stdout, limits.output_chars), _Collector(process.stderr, limits.output_chars)]
        for reader in readers:
            reader.start()
        stopped = ""
        deadline = started + limits.seconds
        while process.poll() is None:
            if cancel is not None and cancel.is_set():
                stopped = "cancelled"
            elif time.perf_counter() >= deadline:
                stopped = "timeout"
            if stopped:
                break
            time.sleep(0.05)
        # End the whole group: the program's children too, whether it finished or not.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait()
        for reader in readers:
            reader.join(5)
        (stdout, cut_out), (stderr, cut_err) = readers[0].text(), readers[1].text()
        return RunResult(
            argv=list(argv),
            exit_code=None if stopped else process.returncode,
            stdout=stdout,
            stderr=stderr,
            seconds=round(time.perf_counter() - started, 3),
            stopped=stopped,
            truncated=cut_out or cut_err,
        )


# ---- public ------------------------------------------------------------------------------------


def isolation_report(*, confine_writes: bool = True, allow_network: bool = False) -> dict[str, Any]:
    """What the operating system enforces for a run on this machine, in plain words."""

    if IS_WINDOWS:
        writes = "Windows refuses writes outside the workspace (Low integrity level)" if confine_writes else "not confined"
        limits = "Windows Job Object: memory, number of processes, the whole tree ends on time limit or cancel"
    else:
        writes = "not confined by the operating system on this platform"
        limits = "resource limits: memory and CPU time (the number of processes is not limited); the process group ends on time limit or cancel"
    return {
        "platform": sys.platform,
        "writes": writes,
        "writes_confined": bool(IS_WINDOWS and confine_writes),
        "limits": limits,
        "reads": "not confined: the program can read what the user can read",
        "network": "not blocked by the operating system" + ("" if allow_network else "; proxy settings point at a closed port"),
        "environment": "clean: no keys or tokens; home, temp and caches are inside the workspace",
        "shell": "none: arguments are passed as a list",
    }


def run(
    argv: list[str],
    workspace: Path,
    *,
    cwd: Path | None = None,
    limits: Limits | None = None,
    allow_network: bool = False,
    confine_writes: bool = True,
    extra_env: dict[str, str] | None = None,
    cancel: threading.Event | None = None,
) -> RunResult:
    """Run one program inside a prepared workspace (see prepare_workspace) and return what happened.

    Raises SandboxError when the program cannot be started under the limits; a program that
    starts and fails is a normal result with its exit code.
    """

    if not argv or not all(isinstance(part, str) for part in argv):
        raise SandboxError("A command is a non-empty list of text arguments.")
    workspace = Path(workspace).resolve()
    where = Path(cwd).resolve() if cwd is not None else workspace
    if where != workspace and workspace not in where.parents:
        raise SandboxError(f"The working folder {where} is outside the workspace {workspace}.")
    if not where.is_dir():
        raise SandboxError(f"The working folder {where} does not exist.")
    limits = limits or Limits()
    env = clean_environment(workspace, allow_network=allow_network, extra=extra_env)
    for folder in (workspace / TEMP_FOLDER, workspace / HOME_FOLDER):
        folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        result = _run_windows(list(argv), where, env, limits, confine_writes, cancel)
    else:
        result = _run_posix(list(argv), where, env, limits, cancel)
    result.isolation = isolation_report(confine_writes=confine_writes, allow_network=allow_network)
    return result
