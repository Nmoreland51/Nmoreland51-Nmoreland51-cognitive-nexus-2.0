"""The tools a coding task can use, registered with their schemas and effects.

    files   list_files, read_file, search_text          read    bounded output, workspace only
            write_file, replace_in_file, apply_patch,   write   a diff preview comes back, and a
            delete_file, restore_checkpoint                     checkpoint is taken first, so any
                                                                change can be undone exactly
            show_diff, list_checkpoints                 read
    shell   run_command, run_tests                      execute in the sandbox (agent/sandbox.py)
    git     commit_changes                              write   to the task's own branch

Every path is resolved inside the task's checkout (agent/workspace.py refuses anything else).
Programs are started without a shell, from a short list of allowed names, with the limits the
sandbox enforces. Pushing a branch and opening a pull request are in agent/github.py: they
reach outside this machine and always need a person's approval.
"""

from __future__ import annotations

import difflib
import fnmatch
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from agent import sandbox
from agent.registry import Tool, ToolContext, ToolError, ToolRegistry, ToolResult, bounded
from agent.workspace import PRIVATE_FOLDERS, Workspace, WorkspaceError, WorkspaceManager

MAX_FILE_BYTES = 2_000_000  # larger files are not read or searched
MAX_READ_LINES = 400
MAX_LINE_CHARS = 400
# Programs a task may start. All of them run confined to the workspace; the list is a second fence,
# and keeps shells out because a shell would bring back pipes and redirects.
DEFAULT_PROGRAMS = ("python", "pytest", "git", "node", "npm", "npx", "cargo", "go", "dotnet", "make", "ruff", "mypy")
READ_ONLY_GIT = ("status", "diff", "log", "show", "ls-files", "grep", "blame", "rev-parse", "branch", "describe")
_TEST_SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed|deselected|warnings?)")
_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)


def _checkout(context: ToolContext) -> tuple[WorkspaceManager, Workspace]:
    if context.workspaces is None or context.checkout is None:
        raise ToolError("This tool needs a task workspace, and none is open.")
    return context.workspaces, context.checkout


def _path(context: ToolContext, relative: str, *, must_exist: bool = False) -> Path:
    manager, checkout = _checkout(context)
    try:
        return manager.resolve(checkout, relative, must_exist=must_exist)
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc


def _read_text(path: Path) -> str:
    if path.is_dir():
        raise ToolError(f"{path.name} is a folder, not a file.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ToolError(f"{path.name} is larger than {MAX_FILE_BYTES // 1_000_000} MB and is not read.")
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        raise ToolError(f"{path.name} is not a text file.")
    return data.decode("utf-8", errors="replace")


def _project_files(context: ToolContext, folder: str = "") -> list[str]:
    """Files Git knows or would add: tracked and new ones, without ignored and private files."""

    manager, checkout = _checkout(context)
    listed = manager.git(checkout, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"]).stdout
    names = sorted({name for name in listed.split("\0") if name and name.split("/")[0] not in PRIVATE_FOLDERS})
    prefix = folder.strip("/").replace("\\", "/")
    if prefix and prefix != ".":
        names = [name for name in names if name == prefix or name.startswith(prefix + "/")]
    return [name for name in names if (checkout.path / name).is_file()]


def _diff(before: str, after: str, name: str) -> str:
    lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), f"a/{name}", f"b/{name}", n=3)
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def _checkpoint(context: ToolContext, label: str) -> str:
    manager, checkout = _checkout(context)
    try:
        return manager.checkpoint(checkout, label)
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc


# ---- files: reading ----------------------------------------------------------------------------


def list_files(context: ToolContext, folder: str = "", pattern: str = "", limit: int = 200) -> ToolResult:
    if folder.strip() not in ("", "."):
        _path(context, folder, must_exist=True)
    names = _project_files(context, folder)
    if pattern:
        names = [name for name in names if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name.rsplit("/", 1)[-1], pattern)]
    shown = names[:limit]
    more = f"\n... and {len(names) - len(shown)} more (narrow the folder or pattern)" if len(names) > len(shown) else ""
    return ToolResult(ok=True, output=("\n".join(shown) or "No files match.") + more, data={"count": len(names), "files": shown})


def read_file(context: ToolContext, path: str, start_line: int = 1, max_lines: int = 200) -> ToolResult:
    real = _path(context, path, must_exist=True)
    lines = _read_text(real).splitlines()
    first = max(1, int(start_line))
    count = max(1, min(int(max_lines), MAX_READ_LINES))
    chosen = lines[first - 1 : first - 1 + count]
    width = len(str(first + len(chosen)))
    body = "\n".join(
        f"{number:>{width}}  {line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + ' [line cut]'}" for number, line in enumerate(chosen, first)
    )
    last = first + len(chosen) - 1
    note = f"\n[lines {first}-{last} of {len(lines)}; read on with start_line={last + 1}]" if last < len(lines) else f"\n[lines {first}-{last} of {len(lines)}]"
    return ToolResult(ok=True, output=(body or "(empty file)") + note, data={"lines": len(lines), "first": first, "last": last})


def search_text(context: ToolContext, query: str, folder: str = "", regex: bool = False, max_results: int = 50) -> ToolResult:
    if not query:
        raise ToolError("Give some text to search for.")
    try:
        pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    except re.error as exc:
        raise ToolError(f"That is not a valid regular expression: {exc}") from exc
    _manager, checkout = _checkout(context)
    limit = max(1, min(int(max_results), 200))
    hits: list[str] = []
    files_with_hits = 0
    total = 0
    for name in _project_files(context, folder):
        path = checkout.path / name
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        found_here = False
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                total += 1
                found_here = True
                if len(hits) < limit:
                    hits.append(f"{name}:{number}: {line.strip()[:MAX_LINE_CHARS]}")
        files_with_hits += found_here
    more = f"\n... {total - len(hits)} more matches not shown" if total > len(hits) else ""
    return ToolResult(
        ok=True,
        output=("\n".join(hits) if hits else f"No match for {query!r}.") + more,
        data={"matches": total, "files": files_with_hits},
    )


def show_diff(context: ToolContext) -> ToolResult:
    manager, checkout = _checkout(context)
    try:
        diff, files = manager.diff(checkout), manager.changed_files(checkout)
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(ok=True, output=diff or "Nothing has been changed yet.", data={"files": files})


def list_checkpoints(context: ToolContext) -> ToolResult:
    manager, checkout = _checkout(context)
    found = manager.checkpoints(checkout)
    return ToolResult(ok=True, output="\n".join(f"{item['commit'][:12]}  {item['label']}" for item in found) or "No checkpoints yet.", data={"checkpoints": found})


# ---- files: changing ---------------------------------------------------------------------------


def write_file(context: ToolContext, path: str, content: str) -> ToolResult:
    real = _path(context, path)
    if real.is_dir():
        raise ToolError(f"{path} is a folder.")
    before = _read_text(real) if real.exists() else ""
    if real.exists() and before == content:
        return ToolResult(ok=True, output=f"{path} already has exactly this content; nothing changed.", data={"changed": False})
    checkpoint = _checkpoint(context, f"before write_file {path}")
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_bytes(content.encode("utf-8"))
    preview = _diff(before, content, path)
    return ToolResult(
        ok=True,
        output=f"{'Changed' if before else 'Created'} {path}. Undo with restore_checkpoint {checkpoint[:12]}.\n{preview}",
        data={"changed": True, "checkpoint": checkpoint, "created": not before},
        artifacts=[path],
    )


def _write_file_done(context: ToolContext, arguments: dict[str, Any], result: ToolResult) -> tuple[bool, str]:
    real = _path(context, arguments["path"])
    same = real.is_file() and real.read_bytes() == arguments["content"].encode("utf-8")
    return same, "the file on disk has the requested content" if same else "the file on disk does not have the requested content"


def replace_in_file(context: ToolContext, path: str, old: str, new: str, count: int = 1) -> ToolResult:
    real = _path(context, path, must_exist=True)
    before = _read_text(real)
    if not old:
        raise ToolError("`old` must be the exact text to replace.")
    if old == new:
        raise ToolError("`old` and `new` are the same, so nothing would change.")
    found = before.count(old)
    if found == 0:
        # The most common failure of a small model: text that is nearly, not exactly, in the file.
        close = difflib.get_close_matches(old.strip().splitlines()[0] if old.strip() else old, [line.strip() for line in before.splitlines()], n=1, cutoff=0.6)
        hint = f" The closest line in the file is: {close[0]!r}." if close else ""
        raise ToolError(f"The text to replace was not found in {path}. It must match the file exactly, including spaces and line breaks.{hint}")
    if found != int(count):
        raise ToolError(f"The text to replace occurs {found} times in {path}, not {count}. Include more of the surrounding lines so that it is unique, or set count.")
    checkpoint = _checkpoint(context, f"before replace_in_file {path}")
    after = before.replace(old, new)
    real.write_bytes(after.encode("utf-8"))
    return ToolResult(
        ok=True,
        output=f"Changed {path}. Undo with restore_checkpoint {checkpoint[:12]}.\n{_diff(before, after, path)}",
        data={"changed": True, "checkpoint": checkpoint, "replacements": found},
        artifacts=[path],
    )


def _replace_done(context: ToolContext, arguments: dict[str, Any], result: ToolResult) -> tuple[bool, str]:
    text = _read_text(_path(context, arguments["path"], must_exist=True))
    present = arguments["new"] in text if arguments["new"] else arguments["old"] not in text
    return present, "the new text is in the file" if present else "the new text is not in the file"


def apply_patch(context: ToolContext, patch: str) -> ToolResult:
    manager, checkout = _checkout(context)
    if not patch.strip():
        raise ToolError("The patch is empty.")
    text = patch if patch.endswith("\n") else patch + "\n"
    for target in re.findall(r"^(?:\+\+\+|---) (?:[ab]/)?(\S+)", text, flags=re.MULTILINE):
        if target != "/dev/null":
            _path(context, target)  # refuses paths outside the workspace before Git sees them
    with tempfile.NamedTemporaryFile("w", suffix=".patch", dir=str(manager.root), delete=False, encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        patch_file = Path(handle.name)
    try:
        check = manager.git(checkout, ["apply", "--check", "--whitespace=nowarn", str(patch_file)], check=False)
        if check.returncode != 0:
            raise ToolError(
                f"The patch does not apply to the current files: {(check.stderr or check.stdout).strip()[:500]}\n"
                "Each change needs unchanged lines before and after it that match the file exactly, as `diff -u` writes them. "
                "For a small edit, replace_in_file is easier to get right."
            )
        checkpoint = _checkpoint(context, "before apply_patch")
        manager.git(checkout, ["apply", "--whitespace=nowarn", str(patch_file)])
        stat = manager.git(checkout, ["apply", "--stat", str(patch_file)], check=False).stdout.strip()
        files = [name for name in manager.git(checkout, ["apply", "--numstat", str(patch_file)], check=False).stdout.split() if "/" in name or "." in name]
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        patch_file.unlink(missing_ok=True)
    return ToolResult(ok=True, output=f"Patch applied. Undo with restore_checkpoint {checkpoint[:12]}.\n{stat}", data={"checkpoint": checkpoint, "patch": text}, artifacts=files)


def _patch_done(context: ToolContext, arguments: dict[str, Any], result: ToolResult) -> tuple[bool, str]:
    """An applied patch can be taken out again cleanly; one that did not take cannot."""

    manager, checkout = _checkout(context)
    with tempfile.NamedTemporaryFile("w", suffix=".patch", dir=str(manager.root), delete=False, encoding="utf-8", newline="\n") as handle:
        handle.write(result.data["patch"])
        patch_file = Path(handle.name)
    try:
        reversible = manager.git(checkout, ["apply", "--reverse", "--check", "--whitespace=nowarn", str(patch_file)], check=False).returncode == 0
    finally:
        patch_file.unlink(missing_ok=True)
    return reversible, "the files contain the patch" if reversible else "the files do not contain the patch"


def delete_file(context: ToolContext, path: str) -> ToolResult:
    real = _path(context, path, must_exist=True)
    if real.is_dir():
        raise ToolError(f"{path} is a folder; delete files one at a time.")
    checkpoint = _checkpoint(context, f"before delete_file {path}")
    real.unlink()
    return ToolResult(ok=True, output=f"Deleted {path}. Undo with restore_checkpoint {checkpoint[:12]}.", data={"checkpoint": checkpoint}, artifacts=[path])


def restore_checkpoint(context: ToolContext, checkpoint: str) -> ToolResult:
    manager, checkout = _checkout(context)
    known = {item["commit"] for item in manager.checkpoints(checkout)}
    matches = [commit for commit in known if commit.startswith(checkpoint.strip())] if len(checkpoint.strip()) >= 7 else []
    if len(matches) != 1:
        raise ToolError(f"{checkpoint!r} is not one of this task's checkpoints. Use list_checkpoints.")
    try:
        manager.restore(checkout, matches[0])
        files = manager.changed_files(checkout)
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(ok=True, output=f"Files are back to checkpoint {matches[0][:12]}. {len(files)} file(s) still differ from the task's starting point.", data={"checkpoint": matches[0], "changed_files": files})


def _restore_done(context: ToolContext, arguments: dict[str, Any], result: ToolResult) -> tuple[bool, str]:
    manager, checkout = _checkout(context)
    same = manager.diff(checkout, since=result.data["checkpoint"]) == ""
    return same, "the files match the checkpoint" if same else "the files differ from the checkpoint"


# ---- shell -------------------------------------------------------------------------------------


def _program(context: ToolContext, argv: list[str]) -> list[str]:
    """Check a command against the allowed programs and return it ready to start."""

    if not argv:
        raise ToolError("The command is empty.")
    name = Path(argv[0]).name.lower()
    name = name[:-4] if name.endswith(".exe") else name
    name = "python" if re.fullmatch(r"python[\d.]*|py", name) else name
    allowed = {str(item).lower() for item in context.settings.get("agent_allowed_programs") or DEFAULT_PROGRAMS}
    if name not in allowed:
        raise ToolError(f"{argv[0]!r} is not a program tasks may start. Allowed: {', '.join(sorted(allowed))}.")
    if any(sep in argv[0] for sep in ("/", "\\")) and name != "python":
        raise ToolError("Name the program without a path.")
    if name == "git" and (len(argv) < 2 or argv[1] not in READ_ONLY_GIT):
        raise ToolError(f"Inside the sandbox Git may only look: {', '.join(READ_ONLY_GIT)}. Commits are made with commit_changes.")
    if name == "python":
        if len(argv) >= 4 and argv[1:3] == ["-m", "pip"] and argv[3] in {"install", "download", "wheel", "uninstall"}:
            raise ToolError("Packages are installed with setup_environment, which follows the owner's installation policy.")
        return [str(context.settings.get("agent_python") or sys.executable), *argv[1:]]
    if name == "pytest":
        return [str(context.settings.get("agent_python") or sys.executable), "-m", "pytest", *argv[1:]]
    located = shutil.which(argv[0])
    if located is None:
        raise ToolError(f"{argv[0]} is not installed on this machine.")
    return [located, *argv[1:]]


def _limits(context: ToolContext, seconds: float | None = None) -> sandbox.Limits:
    settings = context.settings
    return sandbox.Limits(
        seconds=float(min(seconds or settings.get("agent_command_seconds", 300), settings.get("agent_command_seconds_max", 1800))),
        memory_mb=int(settings.get("agent_memory_mb", 2048)),
        processes=int(settings.get("agent_processes", 64)),
        output_chars=int(settings.get("agent_output_chars", 200_000)),
    )


def _run(context: ToolContext, argv: list[str], seconds: float | None = None, folder: str = "") -> sandbox.RunResult:
    _manager, checkout = _checkout(context)
    where = _path(context, folder, must_exist=True) if folder.strip() not in ("", ".") else checkout.path
    try:
        return sandbox.run(_program(context, argv), checkout.path, cwd=where, limits=_limits(context, seconds), cancel=context.cancel)
    except sandbox.SandboxError as exc:
        raise ToolError(str(exc)) from exc


def _describe_run(result: sandbox.RunResult) -> str:
    if result.stopped == "timeout":
        return f"stopped after the time limit ({result.seconds:.0f} s)"
    if result.stopped:
        return result.stopped
    return f"exit code {result.exit_code} in {result.seconds:.1f} s"


def run_command(context: ToolContext, argv: list[str], timeout_seconds: float = 300, folder: str = "") -> ToolResult:
    result = _run(context, [str(part) for part in argv], timeout_seconds, folder)
    output = f"{_describe_run(result)}\n{result.combined()}".rstrip()
    return ToolResult(
        ok=result.ok,
        output=bounded(output),
        error="" if result.ok else f"The command ended with {_describe_run(result)}.",
        data={"exit_code": result.exit_code, "stopped": result.stopped, "seconds": result.seconds, "isolation": result.isolation},
    )


def parse_test_output(text: str) -> dict[str, Any]:
    """Counts and failing test names from pytest's summary. Empty counts when it is not pytest output."""

    counts: dict[str, int] = {}
    summary_lines = [line for line in text.splitlines() if _TEST_SUMMARY.search(line) and (" in " in line or line.strip().startswith("="))]
    if summary_lines:
        for number, word in _TEST_SUMMARY.findall(summary_lines[-1]):
            counts[{"errors": "error", "warning": "warnings"}.get(word, word)] = int(number)
    return {"counts": counts, "failing": list(dict.fromkeys(_FAILED_TEST.findall(text)))}


def run_tests(context: ToolContext, commands: list[list[str]] | None = None, timeout_seconds: float = 600) -> ToolResult:
    """Run the task's acceptance commands (or the ones given). Passing means every command exited with 0."""

    chosen = commands or context.settings.get("acceptance") or []
    if not chosen:
        raise ToolError("This task has no acceptance tests, and no command was given.")
    runs = []
    for argv in chosen:
        result = _run(context, [str(part) for part in argv], timeout_seconds)
        parsed = parse_test_output(result.combined())
        runs.append(
            {
                "argv": [str(part) for part in argv],
                "passed": result.ok,
                "exit_code": result.exit_code,
                "stopped": result.stopped,
                "seconds": result.seconds,
                "counts": parsed["counts"],
                "failing": parsed["failing"],
                "output": bounded(result.combined(), 6000),
            }
        )
        if context.cancel.is_set():
            break
    passed = len(runs) == len(chosen) and all(run["passed"] for run in runs)
    lines = []
    for run in runs:
        counted = ", ".join(f"{number} {word}" for word, number in run["counts"].items())
        how = "passed" if run["passed"] else ("stopped after the time limit" if run["stopped"] == "timeout" else f"FAILED (exit code {run['exit_code']})")
        lines.append(f"$ {' '.join(run['argv'])}\n{how}{': ' + counted if counted else ''} in {run['seconds']:.1f} s")
        if not run["passed"]:
            lines.append(run["output"])
    return ToolResult(
        ok=True,  # the tool worked; whether the tests passed is in data["passed"]
        output="\n".join(lines),
        data={"passed": passed, "runs": runs, "isolation": sandbox.isolation_report()},
    )


# ---- git ---------------------------------------------------------------------------------------


def commit_changes(context: ToolContext, message: str) -> ToolResult:
    manager, checkout = _checkout(context)
    if not message.strip():
        raise ToolError("A commit needs a message.")
    try:
        commit = manager.commit(checkout, message.strip())
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    if not commit:
        raise ToolError("There is nothing to commit: no file differs from the last commit.")
    return ToolResult(ok=True, output=f"Committed {commit[:12]} to {checkout.branch}.", data={"commit": commit, "branch": checkout.branch})


def _commit_done(context: ToolContext, arguments: dict[str, Any], result: ToolResult) -> tuple[bool, str]:
    manager, checkout = _checkout(context)
    on_branch = manager.git(checkout, ["rev-parse", f"refs/heads/{checkout.branch}"], check=False).stdout.strip()
    same = on_branch == result.data["commit"]
    return same, f"the branch {checkout.branch} points at the new commit" if same else f"the branch {checkout.branch} does not point at the new commit"


# ---- registration ------------------------------------------------------------------------------

_TEXT = {"type": "string"}
_PATH = {"type": "string", "minLength": 1, "description": "Path relative to the repository root."}


def _schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def register_coding_tools(registry: ToolRegistry) -> ToolRegistry:
    """Add the file, shell and git tools to a registry."""

    add = registry.register
    add(Tool("list_files", "List the project's files, optionally in one folder or matching a pattern such as *.py.",
             _schema({"folder": _TEXT, "pattern": _TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}),
             "read", list_files, adapter="files", repeatable=True))  # fmt: skip
    add(Tool("read_file", "Read a text file with line numbers, up to 400 lines at a time.",
             _schema({"path": _PATH, "start_line": {"type": "integer", "minimum": 1}, "max_lines": {"type": "integer", "minimum": 1, "maximum": MAX_READ_LINES}}, ("path",)),
             "read", read_file, adapter="files", repeatable=True))  # fmt: skip
    add(Tool("search_text", "Find text (or a regular expression) in the project's files. Returns file:line: text.",
             _schema({"query": {"type": "string", "minLength": 1}, "folder": _TEXT, "regex": {"type": "boolean"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 200}}, ("query",)),
             "read", search_text, adapter="files", repeatable=True))  # fmt: skip
    add(Tool("show_diff", "Show everything this task has changed so far, as a diff.", _schema({}), "read", show_diff, adapter="files", repeatable=True))
    add(Tool("list_checkpoints", "List the restore points taken before each change.", _schema({}), "read", list_checkpoints, adapter="files", repeatable=True))
    add(Tool("write_file", "Create a file or replace its whole content. Returns a diff of the change.",
             _schema({"path": _PATH, "content": _TEXT}, ("path", "content")),
             "write", write_file, adapter="files", verify=_write_file_done, summarize=lambda a: f"write {a['path']} ({len(a['content'])} characters)"))  # fmt: skip
    add(Tool("replace_in_file", "Replace an exact piece of text in a file. `old` must match the file exactly and be unique.",
             _schema({"path": _PATH, "old": {"type": "string", "minLength": 1}, "new": _TEXT, "count": {"type": "integer", "minimum": 1}}, ("path", "old", "new")),
             "write", replace_in_file, adapter="files", verify=_replace_done, summarize=lambda a: f"edit {a['path']}"))  # fmt: skip
    add(Tool("apply_patch", "Apply a unified diff to the project's files.",
             _schema({"patch": {"type": "string", "minLength": 1}}, ("patch",)),
             "write", apply_patch, adapter="files", verify=_patch_done, summarize=lambda a: f"apply a patch of {len(a['patch'].splitlines())} lines"))  # fmt: skip
    add(Tool("delete_file", "Delete one file.", _schema({"path": _PATH}, ("path",)), "write", delete_file, adapter="files",
             verify=lambda context, a, result: (not _path(context, a["path"]).exists(), "the file is gone"), summarize=lambda a: f"delete {a['path']}"))  # fmt: skip
    add(Tool("restore_checkpoint", "Put every file back to what it was at a checkpoint.",
             _schema({"checkpoint": {"type": "string", "minLength": 7}}, ("checkpoint",)),
             "write", restore_checkpoint, adapter="files", verify=_restore_done, repeatable=True))  # fmt: skip
    add(Tool("run_command", "Run a program in the sandbox, given as a list of arguments (no shell). Allowed programs only.",
             _schema({"argv": {"type": "array", "items": _TEXT, "minItems": 1}, "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 1800}, "folder": _TEXT}, ("argv",)),
             "execute", run_command, adapter="shell", repeatable=True, summarize=lambda a: "run " + " ".join(a["argv"])))  # fmt: skip
    add(Tool("run_tests", "Run the task's acceptance tests in the sandbox and report which passed.",
             _schema({"commands": {"type": "array", "items": {"type": "array", "items": _TEXT, "minItems": 1}}, "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 1800}}),
             "execute", run_tests, adapter="shell", repeatable=True))  # fmt: skip
    add(Tool("commit_changes", "Commit the task's changes to its own branch.",
             _schema({"message": {"type": "string", "minLength": 1}}, ("message",)),
             "write", commit_changes, adapter="git", verify=_commit_done, summarize=lambda a: f"commit: {a['message'].splitlines()[0][:80]}"))  # fmt: skip
    return registry
