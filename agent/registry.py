"""The capability registry: every tool the assistant can run, what it takes and what it can affect.

A tool is a function with a name, a JSON Schema for its arguments, and a declared effect:

    read      looks at files or state on this machine, changes nothing
    write     changes files inside the task's workspace
    execute   runs a program (inside the sandbox)
    network   contacts another machine without changing anything there
    external  changes something outside this machine: a push, a pull request, a message

Nothing runs except through ToolRegistry.call, which does the same things for every tool, in this
order: check the arguments against the schema, ask the approval policy, refuse to repeat a
completed non-repeatable action (so a resumed task does not redo its writes), write the action down
before running it, run it, check what came back against the schema the tool declares for its
result (where it declares one), check the outcome against observable state where the tool can, and
write down how it ended. The record is the user's action history.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import jsonschema

from agent.approvals import ApprovalPolicy
from agent.store import AgentStore
from modules.event_log import record_event

EFFECTS = ("read", "write", "execute", "network", "external")
MAX_OUTPUT_CHARS = 16_000  # what one tool call may return to the model or the history


class ToolError(Exception):
    """A tool could not do what was asked. The message is shown to the model and the user."""


@dataclass
class ToolResult:
    ok: bool
    output: str = ""  # bounded text for the model and the user
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    artifacts: list[str] = field(default_factory=list)  # files the action produced
    # Checked against observable state after the action; None when the tool has no such check.
    verified: bool | None = None
    verification: str = ""
    # ok, failed, invalid (bad arguments or unknown tool), denied, needs_approval, cancelled,
    # or replayed (already done earlier; the recorded result is returned without running again).
    status: str = ""
    action_id: str = ""
    approval_id: str = ""
    duration: float = 0.0

    @property
    def replayed(self) -> bool:
        return self.status == "replayed"


@dataclass
class ToolContext:
    """What a tool call happens in: whose task, which folder, under which approval policy."""

    store: AgentStore
    policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)
    workspace: Path | None = None  # the folder file and shell tools are confined to
    task_id: str = ""
    session: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    settings: dict[str, Any] = field(default_factory=dict)
    # For tools that work on a task's Git checkout (agent/workspace.py): the manager and the checkout.
    workspaces: Any = None
    checkout: Any = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema of the arguments (an object)
    effect: str
    run: Callable[..., ToolResult]  # run(context, **arguments)
    adapter: str = "core"  # which group of tools it belongs to: files, shell, git, github, web, ...
    # Running it again with the same arguments is harmless (reads, test runs): a call that is not
    # part of a named step simply runs. Other tools are never repeated once they have succeeded
    # with the same arguments for the same task. Inside a named step no tool is repeated: a task
    # that continues after a pause picks up its finished steps from the record.
    repeatable: bool = False
    # verify(context, arguments, result) -> (true?, what was checked). Looks at the world, not at the result text.
    verify: Callable[[ToolContext, dict[str, Any], ToolResult], tuple[bool, str]] | None = None
    # One line describing a call for approval requests and the history.
    summarize: Callable[[dict[str, Any]], str] | None = None
    # JSON Schema of the data a successful call returns. A result that does not match is a failure:
    # whatever reads the data next (a model, the app) is promised this shape.
    returns: dict[str, Any] | None = None

    def summary(self, arguments: dict[str, Any]) -> str:
        if self.summarize is not None:
            try:
                return self.summarize(arguments)
            except Exception:
                pass
        shown = json.dumps(arguments, ensure_ascii=False, default=str)
        return f"{self.name} {shown if len(shown) <= 200 else shown[:197] + '...'}"


def bounded(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Text cut to a size a small model can read, keeping its start and its end."""

    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - 2 * half:,} characters left out ...]\n{text[-half:]}"


def action_key(tool: str, arguments: dict[str, Any], *, task_id: str = "", session: str = "", step: str = "") -> str:
    """Identifies one intended action: the same tool, arguments, task and step give the same key.

    `step` separates intended repetitions (the patch of attempt 2 from the same patch in attempt 1),
    and marks a call as one step of a recorded plan: such a step is done once.
    """

    canonical = json.dumps([task_id or session, step, tool, arguments], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.effect not in EFFECTS:
            raise ValueError(f"{tool.name}: {tool.effect!r} is not an effect. Use one of {', '.join(EFFECTS)}.")
        if tool.name in self._tools:
            raise ValueError(f"A tool named {tool.name!r} is already registered.")
        if tool.parameters.get("type") != "object":
            raise ValueError(f"{tool.name}: the parameter schema must describe an object.")
        jsonschema.Draft202012Validator.check_schema(tool.parameters)
        if tool.returns is not None:
            jsonschema.Draft202012Validator.check_schema(tool.returns)
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self, effects: tuple[str, ...] | None = None, adapters: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        """The registry as data: for a model's prompt, the app's capability list, or documentation."""

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "effect": tool.effect,
                "adapter": tool.adapter,
                "repeatable": tool.repeatable,
                "checks_its_outcome": tool.verify is not None,
                "parameters": tool.parameters,
                "returns": tool.returns,
            }
            for tool in sorted(self._tools.values(), key=lambda item: (item.adapter, item.name))
            if (effects is None or tool.effect in effects) and (adapters is None or tool.adapter in adapters)
        ]

    def call(self, name: str, arguments: dict[str, Any], context: ToolContext, *, step: str = "") -> ToolResult:
        """Run one tool. Never raises for something the caller did: every outcome is a ToolResult."""

        arguments = dict(arguments or {})
        tool = self._tools.get(name)
        key = action_key(name, arguments, task_id=context.task_id, session=context.session, step=step)
        common: dict[str, Any] = {"key": key, "tool": name, "arguments": arguments, "task_id": context.task_id, "session": context.session}
        if tool is None:
            error = f"There is no tool named {name!r}. Available: {', '.join(self.names())}."
            action_id = context.store.record_refusal(effect="", status="invalid", error=error, **common)
            return ToolResult(ok=False, error=error, status="invalid", action_id=action_id)
        problems = sorted(jsonschema.Draft202012Validator(tool.parameters).iter_errors(arguments), key=lambda item: list(item.path))
        if problems:
            where = "; ".join(f"{'/'.join(map(str, problem.path)) or 'arguments'}: {problem.message}" for problem in problems[:4])
            error = f"The arguments for {name} are not valid: {where}"
            action_id = context.store.record_refusal(effect=tool.effect, status="invalid", error=error, **common)
            return ToolResult(ok=False, error=error, status="invalid", action_id=action_id)
        if context.cancel.is_set():
            return ToolResult(ok=False, error="Cancelled before the action started.", status="cancelled")

        if step or not tool.repeatable:
            done = context.store.completed_action(key)
            if done is not None:
                return ToolResult(
                    ok=True,
                    output=done["output"],
                    data=done["data"],
                    artifacts=done["artifacts"],
                    verified=done["verified"],
                    verification=done["verification"],
                    status="replayed",
                    action_id=done["id"],
                )

        approval_id = ""
        decision = context.policy.decide(tool.name, tool.effect)
        if decision == "deny":
            error = f"{name} is not allowed here: the approval policy ({context.policy.mode}) refuses actions with the effect '{tool.effect}'."
            action_id = context.store.record_refusal(effect=tool.effect, status="denied", error=error, **common)
            return ToolResult(ok=False, error=error, status="denied", action_id=action_id)
        if decision == "ask":
            approval = context.store.approval_for(key)
            if approval is not None and approval["status"] == "denied":
                error = f"{approval['decided_by']} refused this action" + (f": {approval['note']}" if approval["note"] else ".")
                action_id = context.store.record_refusal(effect=tool.effect, status="denied", error=error, **common)
                return ToolResult(ok=False, error=error, status="denied", action_id=action_id, approval_id=approval["id"])
            if approval is None or approval["status"] != "approved" or not context.store.use_approval(approval["id"]):
                approval_id = context.store.request_approval(
                    key=key, tool=name, effect=tool.effect, summary=tool.summary(arguments), arguments=arguments, task_id=context.task_id
                )
                return ToolResult(
                    ok=False,
                    error=f"This action needs a person's approval first (request {approval_id}): {tool.summary(arguments)}",
                    status="needs_approval",
                    approval_id=approval_id,
                )
            approval_id = approval["id"]

        action_id = context.store.begin_action(effect=tool.effect, approval_id=approval_id, **common)
        started = time.perf_counter()
        try:
            result = tool.run(context, **arguments)
            if not isinstance(result, ToolResult):
                raise TypeError(f"{name} returned {type(result).__name__}, not a ToolResult")
        except ToolError as exc:
            result = ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # a bug in a tool must not take the agent down with it
            result = ToolResult(ok=False, error=f"{name} failed unexpectedly: {type(exc).__name__}: {exc}")
        if result.ok and tool.returns is not None:
            wrong = sorted(jsonschema.Draft202012Validator(tool.returns).iter_errors(result.data), key=lambda item: list(item.path))
            if wrong:
                where = "; ".join(f"{'/'.join(map(str, problem.path)) or 'result'}: {problem.message[:160]}" for problem in wrong[:3])
                result.ok = False
                result.error = f"{name} returned data that does not match what it declares: {where}"
        if result.ok and tool.verify is not None:
            try:
                result.verified, result.verification = tool.verify(context, arguments, result)
            except Exception as exc:
                result.verified, result.verification = False, f"The outcome could not be checked: {type(exc).__name__}: {exc}"
            if not result.verified:
                result.ok = False
                result.error = f"{name} reported success, but checking the result showed otherwise: {result.verification}"
        result.output = bounded(result.output)
        result.duration = round(time.perf_counter() - started, 3)
        result.status = "ok" if result.ok else "failed"
        result.action_id, result.approval_id = action_id, approval_id
        context.store.finish_action(
            action_id,
            status=result.status,
            output=result.output,
            data=result.data,
            error=result.error,
            artifacts=result.artifacts,
            verified=result.verified,
            verification=result.verification,
            duration=result.duration,
        )
        if not result.ok:
            record_event("tool_failure", f"{name} failed", tool=name, effect=tool.effect, error=result.error[:300], task=context.task_id)
        return result
