"""The agent from a terminal.

    python -m agent task add --repo PATH --title "Fix the date parser" --test "python -m pytest tests/test_dates.py"
    python -m agent task run TASK            work on it now, with the local model
    python -m agent task list | show TASK | diff TASK
    python -m agent task accept TASK --by NAME            only this marks a task done
    python -m agent task changes TASK --by NAME "what to do differently"
    python -m agent task publish TASK        push its branch and open a draft pull request (asks for approval)
    python -m agent task cancel TASK | cleanup TASK

    python -m agent approvals                what is waiting for a person
    python -m agent approve REQUEST --by NAME     /     python -m agent deny REQUEST --by NAME --note "why"
    python -m agent history [--task TASK]    every action taken: inputs, approval, result

    python -m agent queue TASK               hand a task to the background worker
    python -m agent remind "Call the dentist" --in 2h
    python -m agent watch https://example.org/releases --every 6h [--phrase "version 3"]
    python -m agent jobs | schedules | notices
    python -m agent job cancel JOB | job retry JOB | schedule remove ID
    python -m agent worker                   run background jobs until stopped with Ctrl+C

    python -m agent tools                    every capability, with what it can affect
    python -m agent sandbox                  what the operating system enforces here

    python -m agent accounts                 linked accounts and what each may be used for
    python -m agent accounts link github --allow read push [--expires 2027-03-01] [--from-variable NAME]
                                             the token is asked for, or read from a variable; never typed as an argument
    python -m agent accounts allow github pull_request   /   accounts withhold github push
    python -m agent accounts unlink github   /   accounts check github
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shlex
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from agent import sandbox
from agent.coder import CodingAgent, default_agent, describe
from agent.github import publish, register_github_tools
from agent.handlers import default_handlers
from agent.jobs import JobQueue, Worker
from agent.model import RouterModel
from agent.store import AgentStore, StoreError
from agent.workspace import WorkspaceError
from modules import accounts

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)\s*(s|sec|m|min|h|hr|hour|hours|d|day|days)?$", re.IGNORECASE)


def parse_duration(text: str) -> float:
    """Seconds in "90", "10m", "2h", "1d"."""

    match = _DURATION.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"{text!r} is not a duration. Use for example 30s, 10m, 2h or 1d.")
    unit = (match.group(2) or "s").lower()[0]
    return float(match.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def build_agent(store: AgentStore, model_name: str = "", settings: dict[str, Any] | None = None) -> CodingAgent:
    """A coding agent that uses the app's configured providers, with the GitHub tools added."""

    from modules.nexus_config import load_runtime_config
    from modules.provider_router import ProviderRouter

    config = load_runtime_config()
    merged = {**config, **(settings or {})}
    model = RouterModel(ProviderRouter(config), model=model_name or str(merged.get("agent_model") or ""), provider_order=list(merged.get("provider_order") or []), num_ctx=int(merged.get("agent_num_ctx") or 4096))
    agent = default_agent(store, model, settings=merged)
    register_github_tools(agent.registry)
    return agent


def _print_task(store: AgentStore, task_id: str) -> None:
    task = store.get_task(task_id)
    print(f"{task.id}  [{task.status}]  {task.title}")
    print(f"  {describe(task)}")
    print(f"  repository: {task.repo}   branch: {task.branch or '(none yet)'}   owner: {task.owner}")
    print(f"  acceptance: {'; '.join(' '.join(command) for command in task.acceptance) or '(none)'}")
    spent = task.spent or {}
    print(f"  used: {spent.get('attempts', 0)} attempt(s), {float(spent.get('seconds', 0)):.0f} s, {int(spent.get('model_tokens', 0)):,} model tokens, ${float(spent.get('usd', 0)):.4f}")
    if task.blockers:
        print("  blocked by: " + "; ".join(task.blockers))
    for attempt in task.state.get("attempts", []):
        print(f"  attempt {attempt['number']}: {(attempt.get('problem') or 'worked').splitlines()[0][:150]}")
    if task.result.get("what_a_person_can_do"):
        print(f"  what you can do: {task.result['what_a_person_can_do']}")
    if task.result.get("pull_request"):
        print(f"  pull request: {task.result['pull_request']['url']}")
    print("  history:")
    for event in store.events(task.id)[-12:]:
        print(f"    {event['at'][11:19]}  {event['message'][:140]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=None, help="the agent database (default: data/agent/agent.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    task = sub.add_parser("task").add_subparsers(dest="action", required=True)
    add = task.add_parser("add")
    add.add_argument("--repo", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--description", default="")
    add.add_argument("--test", action="append", default=[], help="a command that fails now and must pass when the task is done (repeatable)")
    add.add_argument("--regression", action="append", default=[], help="a wider test command that must still pass (repeatable)")
    add.add_argument("--base", default="HEAD")
    add.add_argument("--attempts", type=int, default=3)
    add.add_argument("--time", type=parse_duration, default=1800.0)
    add.add_argument("--after", action="append", default=[], help="a task that must be done first (repeatable)")
    add.add_argument("--priority", type=int, default=0)
    for name in ("run", "show", "diff", "cancel", "cleanup", "publish"):
        action = task.add_parser(name)
        action.add_argument("task")
        if name == "run":
            action.add_argument("--model", default="")
    task.add_parser("list")
    accept = task.add_parser("accept")
    accept.add_argument("task")
    accept.add_argument("--by", required=True)
    changes = task.add_parser("changes")
    changes.add_argument("task")
    changes.add_argument("feedback")
    changes.add_argument("--by", required=True)

    sub.add_parser("approvals")
    for name in ("approve", "deny"):
        decide = sub.add_parser(name)
        decide.add_argument("request")
        decide.add_argument("--by", required=True)
        decide.add_argument("--note", default="")
    history = sub.add_parser("history")
    history.add_argument("--task", default=None)
    history.add_argument("--limit", type=int, default=30)

    queue_task = sub.add_parser("queue")
    queue_task.add_argument("task")
    remind = sub.add_parser("remind")
    remind.add_argument("title")
    remind.add_argument("--in", dest="delay", type=parse_duration, default=None)
    remind.add_argument("--every", type=parse_duration, default=None)
    remind.add_argument("--daily-at", default="")
    watch = sub.add_parser("watch")
    watch.add_argument("url")
    watch.add_argument("--every", type=parse_duration, default=3600.0)
    watch.add_argument("--phrase", default="")
    for name in ("jobs", "schedules", "notices", "tools", "sandbox"):
        sub.add_parser(name)
    job = sub.add_parser("job").add_subparsers(dest="action", required=True)
    for name in ("cancel", "retry"):
        job.add_parser(name).add_argument("job")
    schedule = sub.add_parser("schedule").add_subparsers(dest="action", required=True)
    schedule.add_parser("remove").add_argument("id")
    linked = sub.add_parser("accounts").add_subparsers(dest="action")
    link = linked.add_parser("link")
    link.add_argument("service")
    link.add_argument("--allow", nargs="*", default=[], metavar="PERMISSION")
    link.add_argument("--expires", default="", help="YYYY-MM-DD")
    link.add_argument("--from-variable", default="", help="read the credential from this environment variable instead of asking")
    for name in ("allow", "withhold"):
        change = linked.add_parser(name)
        change.add_argument("service")
        change.add_argument("permission")
    for name in ("unlink", "check"):
        linked.add_parser(name).add_argument("service")
    worker = sub.add_parser("worker")
    worker.add_argument("--capacity", type=int, default=2)
    worker.add_argument("--model", default="")
    worker.add_argument("--once", action="store_true", help="run what is due, wait for it, and exit")

    args = parser.parse_args(argv)
    store = AgentStore(args.db)
    queue = JobQueue(store)
    try:
        return _dispatch(args, store, queue)
    except (StoreError, WorkspaceError, ValueError, accounts.AccountError) as exc:
        print(f"Cannot do that: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


def _accounts(args: argparse.Namespace) -> int:
    """Linked accounts from a terminal. A credential is never taken from the command line: it would stay in the shell's history."""

    action = args.action
    if action == "link":
        if args.from_variable:
            secret = os.environ.get(args.from_variable, "")
            if not secret:
                raise ValueError(f"The environment variable {args.from_variable} is empty or not set.")
        else:
            secret = getpass.getpass(f"Token or key for {args.service} (not shown): ")
        entry = accounts.link(args.service, secret, permissions=args.allow, expires_at=f"{args.expires}T00:00:00+00:00" if args.expires else "")
        print(f"{entry['name']} is linked and may be used for: {', '.join(entry['permissions']) or 'nothing yet'}. {entry['kept']}")
    elif action in {"allow", "withhold"}:
        entry = (accounts.grant if action == "allow" else accounts.withdraw)(args.service, args.permission)
        print(f"{entry['name']} may now be used for: {', '.join(entry['permissions']) or 'nothing'}.")
    elif action == "unlink":
        outcome = accounts.unlink(args.service)
        print(("Deleted from this machine. " if outcome["deleted_here"] else "Nothing was stored here. ") + ("The service confirmed that it cancelled it. " if outcome["cancelled_at_the_service"] else "") + outcome["still_to_do"])
    elif action == "check":
        if args.service != "github":
            raise ValueError("Only GitHub can be asked about a token from here.")
        answer = accounts.check_github()
        print(f"GitHub accepts the token (account {answer['login']}, {'valid until ' + answer['expires_at'][:10] if answer['expires_at'] else 'no expiry date'})." if answer["accepted"] else f"GitHub does not accept the token (it answered {answer['status']}).")
        return 0 if answer["accepted"] else 1
    else:
        for entry in accounts.accounts():
            state = "not linked"
            if entry["linked"]:
                state = f"linked ({entry['how']}), may be used for: {', '.join(entry['permissions']) or 'nothing'}"
                if entry["expires_at"]:
                    state += f"; runs out {entry['expires_at'][:10]}" + (", renews itself" if entry["renews_itself"] else "")
                if entry["problem"]:
                    state += f"; {entry['problem']}"
            print(f"{entry['service']:<13} {state}")
        print(accounts.protection()[1])
    return 0


def _dispatch(args: argparse.Namespace, store: AgentStore, queue: JobQueue) -> int:
    command = args.command
    if command == "task":
        action = args.action
        if action == "add":
            if not args.test:
                print("Note: without --test the agent has no way to tell when the task is done, and will hand it straight back.", file=sys.stderr)
            budget: dict[str, Any] = {"attempts": args.attempts, "seconds": args.time}
            if args.regression:
                budget["regression"] = [shlex.split(item) for item in args.regression]
            made = store.create_task(args.title, args.description, repo=args.repo, base_ref=args.base, acceptance=[shlex.split(item) for item in args.test], budget=budget, depends_on=args.after, priority=args.priority)
            print(made.id)
        elif action == "list":
            for item in store.list_tasks():
                print(f"{item.id}  [{item.status:<16}] {item.title[:60]:<60} {describe(item)[:80]}")
        elif action == "show":
            _print_task(store, args.task)
        elif action == "run":
            done = build_agent(store, args.model).run(args.task)
            _print_task(store, done.id)
            return 0 if done.status in {"review", "done"} else 1
        elif action == "diff":
            item = store.get_task(args.task)
            agent = build_agent(store)
            print(agent.workspaces.diff(agent.workspaces.open(item.id, item.repo, item.workspace, item.branch, item.base_ref)))
        elif action == "accept":
            print(build_agent(store).accept(args.task, args.by).status)
        elif action == "changes":
            print(build_agent(store).request_changes(args.task, args.by, args.feedback).status)
        elif action == "cancel":
            print(store.update_task(args.task, status="cancelled", note="Cancelled from the command line").status)
        elif action == "cleanup":
            item = store.get_task(args.task)
            agent = build_agent(store)
            agent.workspaces.remove(agent.workspaces.open(item.id, item.repo, item.workspace, item.branch, item.base_ref))
            store.update_task(item.id, workspace="")
            print(f"Removed the workspace. The branch {item.branch} and its commits are still in {item.repo}.")
        elif action == "publish":
            outcome = publish(build_agent(store), args.task)
            print(json.dumps(outcome, indent=2))
            if outcome["status"] == "needs_approval":
                print(f"Approve with: python -m agent approve {outcome['approval']} --by YOUR_NAME   and run this command again.")
            return 0 if outcome["status"] == "published" else 1
    elif command == "approvals":
        for request in store.approvals():
            print(f"{request['id']}  {request['effect']:<8} {request['summary'][:110]}  (task {request['task_id'] or '-'})")
    elif command in {"approve", "deny"}:
        decided = store.decide_approval(args.request, approved=command == "approve", by=args.by, note=args.note)
        print(f"{decided['status']}: {decided['summary']}")
    elif command == "history":
        for action_row in reversed(store.actions(args.task, limit=args.limit)):
            checked = "" if action_row["verified"] is None else (" checked" if action_row["verified"] else " CHECK FAILED")
            shown = json.dumps(action_row["arguments"], ensure_ascii=False)
            print(f"{action_row['started_at'][11:19]}  {action_row['status']:<11} {action_row['effect']:<8} {action_row['tool']:<18} {shown[:70]}{checked}")
    elif command == "queue":
        store.get_task(args.task)
        print(queue.enqueue("coding_task", {"task_id": args.task}, timeout_seconds=7200, max_attempts=2, idempotency_key=f"coding:{args.task}:{store.get_task(args.task).updated_at}"))
    elif command == "remind":
        if args.every or args.daily_at:
            print(queue.add_schedule(args.title, "reminder", {"title": args.title}, every_seconds=int(args.every or 0), daily_at=args.daily_at))
        else:
            print(queue.enqueue("reminder", {"title": args.title}, delay_seconds=args.delay or 0.0))
    elif command == "watch":
        print(queue.add_schedule(f"Watch {args.url}", "watch_url", {"url": args.url, "phrase": args.phrase}, every_seconds=int(args.every), first_run=datetime.now(timezone.utc) + timedelta(seconds=1)))
    elif command == "jobs":
        for job_row in queue.jobs(limit=40):
            print(f"{job_row.id}  [{job_row.status:<9}] {job_row.kind:<12} try {job_row.attempts}/{job_row.max_attempts}  {job_row.progress:>4.0%}  {job_row.progress_note or job_row.error[:80]}")
    elif command == "job":
        if args.action == "cancel":
            print(queue.cancel(args.job))
        else:
            queue.retry(args.job)
            print("queued")
    elif command == "schedules":
        for schedule_row in queue.schedules():
            how = f"every {schedule_row['every_seconds']} s" if schedule_row["every_seconds"] else f"daily at {schedule_row['daily_at']}"
            print(f"{schedule_row['id']}  {'on ' if schedule_row['enabled'] else 'off'}  {schedule_row['kind']:<10} {how:<16} next {schedule_row['next_run'][:19]}  {schedule_row['name'][:50]}")
    elif command == "schedule":
        queue.remove_schedule(args.id)
    elif command == "notices":
        for notice in queue.notices():
            print(f"{notice['at'][:19]}  {'   ' if notice['seen'] else 'new'}  {notice['title']}")
            queue.mark_seen(notice["id"])
    elif command == "tools":
        agent = build_agent(store)
        for tool in agent.registry.describe():
            print(f"{tool['adapter']:<7} {tool['name']:<19} {tool['effect']:<8} {'checks its outcome' if tool['checks_its_outcome'] else '':<19} {tool['description'][:70]}")
    elif command == "sandbox":
        for key, value in sandbox.isolation_report().items():
            print(f"{key:<12} {value}")
    elif command == "accounts":
        return _accounts(args)
    elif command == "worker":
        worker = Worker(queue, default_handlers(queue, lambda: build_agent(store, args.model)), capacity=args.capacity)
        if args.once:
            queue.recover()
            queue.tick()
            started = worker.run_once()
            worker.wait(7200)
            print(f"Ran {started} job(s).")
            return 0
        stop = threading.Event()
        print(f"Worker {worker.name} running. Stop with Ctrl+C.")
        try:
            worker.run_forever(stop)
        except KeyboardInterrupt:
            stop.set()
            print("Stopping: waiting for running jobs to end.")
            worker.wait(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
