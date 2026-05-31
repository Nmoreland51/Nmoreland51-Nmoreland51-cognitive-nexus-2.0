"""Import smoke test for the active Cognitive Nexus app stack."""

from __future__ import annotations

import importlib


MODULES = (
    "app",
    "modules.nexus_core",
    "modules.provider_router",
    "modules.reality_research_agent",
    "modules.core_health",
    "core",
    "search.bloodhound_search",
)


def main() -> int:
    for module_name in MODULES:
        importlib.import_module(module_name)
    print("Cognitive Nexus smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
