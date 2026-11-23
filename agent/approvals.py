"""Which actions run on their own, which wait for a person, and which are refused.

The decision depends on what an action can affect (its effect, declared in the registry), not on
what the model says about it:

    mode         read     write/execute in the workspace     network     external
    read_only    allow    deny                               deny        deny
    ask          allow    ask                                ask         ask
    workspace    allow    allow                              ask         ask
    trusted      allow    allow                              allow       ask

"external" (a push, a pull request, a message: anything another person or system will see) is
never allowed by a mode. It runs only with an approval for that one action, or when the user has
named that tool in `always_allow`, which is their standing decision and is recorded as such.

An approval is for one action: it is tied to the action's key (tool, arguments, task, step) and is
used up when the action runs.

The owner chooses with one setting, `agent_autonomy` (see modules/behavior_policy.py):

    agent_autonomy     mode         standing permissions
    publishing_asks    trusted      none: pushing a branch or opening a pull request asks once   (the default)
    publish_drafts     trusted      push_branch, open_pull_request
    ask_first          ask          none
    read_only          read_only    none

These are permissions for actions. They say nothing about what the assistant may talk about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MODES = ("read_only", "ask", "workspace", "trusted")
# agent_autonomy -> (mode, tools the owner has thereby approved once and for all)
AUTONOMY: dict[str, tuple[str, tuple[str, ...]]] = {
    "publishing_asks": ("trusted", ()),
    "publish_drafts": ("trusted", ("push_branch", "open_pull_request")),
    "ask_first": ("ask", ()),
    "read_only": ("read_only", ()),
}
DEFAULT_AUTONOMY = "publishing_asks"
_TABLE: dict[str, dict[str, str]] = {
    "read_only": {"read": "allow", "write": "deny", "execute": "deny", "network": "deny", "external": "deny"},
    "ask": {"read": "allow", "write": "ask", "execute": "ask", "network": "ask", "external": "ask"},
    "workspace": {"read": "allow", "write": "allow", "execute": "allow", "network": "ask", "external": "ask"},
    "trusted": {"read": "allow", "write": "allow", "execute": "allow", "network": "allow", "external": "ask"},
}


@dataclass
class ApprovalPolicy:
    mode: str = "workspace"
    always_allow: tuple[str, ...] = ()  # tool names the user has approved once and for all
    never_allow: tuple[str, ...] = ()  # tool names that are refused whatever the mode
    always_ask: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"{self.mode!r} is not an approval mode. Use one of {', '.join(MODES)}.")

    def decide(self, tool: str, effect: str) -> str:
        """"allow", "ask" or "deny" for one tool."""

        if tool in self.never_allow:
            return "deny"
        if self.mode == "read_only" and effect != "read":
            return "deny"  # a standing permission does not turn a read-only session into a writing one
        if tool in self.always_ask and effect != "read":
            return "ask"
        if tool in self.always_allow:
            return "allow"
        return _TABLE[self.mode].get(effect, "ask")

    @classmethod
    def from_settings(cls, settings: dict[str, object] | None) -> "ApprovalPolicy":
        settings = settings or {}

        def names(key: str) -> tuple[str, ...]:
            value = settings.get(key) or ()
            items = value.split(",") if isinstance(value, str) else list(value) if isinstance(value, (list, tuple, set)) else []
            return tuple(str(item).strip() for item in items if str(item).strip())

        # The owner's one switch. An unknown value falls back to asking before every change.
        autonomy = str(settings.get("agent_autonomy") or DEFAULT_AUTONOMY).strip().lower()
        mode, standing = AUTONOMY.get(autonomy, ("ask", ()))
        # agent_approval_mode, when given, sets the mode directly (finer control, and what tests use).
        explicit = str(settings.get("agent_approval_mode") or "").strip()
        if explicit:
            mode, standing = (explicit, ()) if explicit in MODES else ("ask", ())
        return cls(
            mode=mode,
            always_allow=tuple(dict.fromkeys(standing + names("agent_always_allow"))),
            never_allow=names("agent_never_allow"),
            always_ask=names("agent_always_ask"),
        )
