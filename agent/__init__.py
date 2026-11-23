"""The parts of Cognitive Nexus that act: tools, approvals, a coding agent and background jobs.

Everything here runs for real on the user's machine, so the package is built around four rules:

* every capability is a registered tool with a schema and a declared effect (agent/registry.py);
* anything that changes state outside a task's own workspace needs approval (agent/approvals.py);
* every action is written down before it runs and again when it ends (agent/store.py), so a crash
  can be recovered from without repeating a write;
* a result is believed because it was checked against observable state (an exit code, a file on
  disk, a diff), never because a model said it worked.

The coding agent (agent/coder.py) is a harness around a language model. What it can fix is bounded
by the model it is given: with the small local model this project ships with, that means small,
well-specified changes with a test that tells it when it is done.
"""
