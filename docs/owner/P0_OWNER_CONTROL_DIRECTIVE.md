# SEND TO CLAUDE NOW
## COGNITIVE NEXUS — P0 OWNER-CONTROLLED BEHAVIOR, COMPLETE RESTRICTION AUDIT, AND PHASED IMPLEMENTATION

**Owner instruction — apply immediately, without abandoning the ongoing 146-item roadmap.**

The intended Cognitive Nexus product is a highly capable, user-directed AI with broad conversational freedom, selectable local/cloud models, deep research, durable memory, autonomous coding and tools, recurring jobs, and Android access. It must not automatically inherit the behavioral restrictions, refusal templates, content policy choices, approval-heavy workflow, or product philosophy of the AI assistants writing its code.

My reference to “DAN mode” describes the degree of owner control and freedom I want; do **not** implement it as a fake GPT mode, a jailbreak-persona gimmick, or a promise that remote APIs will abandon their own provider rules. Design an actual owner-controlled architecture instead.

## 1. Register this P0 requirement now

Add this directive to the authoritative specification and the 146-item audit/progress ledger. Tie it to current Phase 2 work and revisit affected Phase 1 model routing, prompt assembly, profile settings, and research logic. Continue independent approved work while you audit; do not stop after the first few fixes or repeatedly ask me for ordinary development instructions.

## 2. Inventory all restrictions and behavior-affecting mechanisms

Inspect the **current** working tree, not just public `main`. Include all Python core modules, Streamlit UI, backend APIs, Android code, provider adapters, model prompts, memory, research, autonomous coding, tools, scheduled jobs, configuration, tests and deployment.

Search for and trace:

- Content filters, topic classifications, refusal prompts and fallback answers.
- “Safety levels,” hidden defaults, user-facing mode selectors, and behavior overrides.
- Locked system prompts, persona precedence, developer/runtime prompts and prompt transformations.
- Prompt-injection trust rules and their treatment of genuine owner instructions versus third-party content.
- Tool permission gates, shell/file allowlists, Git approvals, network limits, scheduled job scopes and external publication permissions.
- Provider/SDK restrictions that cannot be changed by local code.
- Security and integrity protections, including credentials, backups, authentication and safe handling of external web content.

For every control, record the exact file/function/line, condition, effect, default, purpose, origin, whether the owner requested it, configurability, alternatives, and tests in `docs/OWNER_CONTROL_RESTRICTIONS.md` (or a documented equivalent).

## 3. Pay special attention to these verified baseline mechanisms

I had an independent reviewer inspect the publicly accessible original `main` branch at commit `dce9ee092345eb82d7f6400dac7ee0e8b0eb5f50`. The new worktree may differ. **Recheck all findings against your current code rather than assuming they're unchanged.**

1. `app.py`: `safety_config` has `strict`, `balanced`, `loose`, `unhinged`, but strict mode uses context-blind substring checks including `cp` and `illegal`. Review false positives and what each mode actually changes.
2. `modules/internal_prompts.py`: `LOCKED_SYSTEM_PROMPT` tells the model that user persona settings cannot override internal rules. Classify which statements are product requirements versus optional limitations.
3. `modules/chat_profile.py`: profile construction inserts fixed limits and conditional content guidance. Verify owner setting names accurately match resulting behavior.
4. `modules/response_planner.py` and `modules/nexus_core.py`: topic-sensitive classification and fixed redirection templates. Inspect for legitimate-task overblocking and unintended refusals.
5. `core/reality_grounding/prompt_firewall.py`: source provenance and instruction hierarchy. Distinguish protection against hostile documents from treatment of actual owner input.
6. `app.py`: the advanced safety settings appear disabled while auto-precision mode is active. Verify UI and effective runtime configuration align.
7. Agent GitHub action approvals were reported in recent progress. Inspect actual triggers, defaults and owner-approved autonomy scope.

## 4. Separate three technical layers

**A. Conversation and model behavior** — topic handling, response styles, model selection, local configuration, factuality, refusals, and provider-origin limitations.

**B. Autonomous-agent/tool permissions** — what the system can do on the owner's behalf within a defined scope, including filesystem operations, terminal commands, tests, commits, branch pushes, external publishing, scheduled jobs, and recovery. Design explicit owner-approved capabilities; do not automatically impose a stop-and-confirm dialog before every routine step.

**C. Integrity and security** — credential protection, data corruption prevention, authentication, backups, provenance boundaries and resistance to malicious instructions inside untrusted pages. Do not silently remove these or conflate them with restrictions on ordinary conversation. Explain any meaningful functional limitations they introduce.

The architecture should expose **configured policy**, **effective application behavior**, and **external provider constraints** separately.

## 5. Implement the owner's intended behavior

- Permit broad legitimate discussion, research, technical help, fictional writing and analysis without unnecessary generic refusals from the Nexus application layer.
- Prefer strong models for reasoning/coding; offer owner-selected local models for privacy, offline use and direct configuration. Keep cloud fallback policy limitations transparent.
- Never market “unhinged” or another mode as genuinely unrestricted if independent fixed instructions still narrow behavior.
- Do not install additional content restrictions or optional approval gates without first identifying their purpose, user-facing impact, alternatives, and asking me about the material choice.
- Remove contradictions, misleading labels and unjustified false positives from approved behavior configurations.
- Preserve correct factual grounding and clear uncertainty; do not let reality checks silently turn creative or exploratory questions into refusals.
- Maintain ordinary system integrity and secure handling of data. Record any remaining unavoidable constraints rather than misrepresenting them.

You must still comply with your own operating requirements. When those requirements prevent a requested implementation, disclose the limitation explicitly; **do not secretly replace my requirement with a different implementation**.

## 6. Work in phases, not one-fix-at-a-time

**OC-0 / now:** Record this specification, decisions and test cases in the master roadmap.  
**OC-1 / inventory:** Inspect all current controls and populate the restriction register.  
**OC-2 / design:** Give me a *single consolidated list* of material owner decisions, with recommended alternatives and trade-offs; avoid repeated micro-approvals.  
**OC-3 / implementation:** Integrate the agreed design into the existing 146-item roadmap; refactor where needed while maintaining working checkpoints.  
**OC-4 / testing:** Run automated tests and real local/cloud/backend/Android workflows where available.  
**OC-5 / handoff:** Supply implementation evidence, restriction register, current commit SHAs, test logs and remaining limitations for an independent final audit.

Complete the approved phases autonomously as far as tools, time, budget and external dependencies permit. Preserve progress across sessions and describe genuine blockers rather than declaring premature success.

## 7. Required proof and acceptance

Build and run representative tests showing:

1. Ordinary questions with potentially sensitive words do not trigger accidental substring refusals.
2. Explicitly selected response modes retain their effective settings across restarts and different provider routes.
3. Honest distinction between local application behavior and external provider behavior.
4. Hostile instructions embedded in a retrieved webpage cannot impersonate the owner or runtime instructions.
5. Direct legitimate owner requests are interpreted correctly.
6. The coding agent can take a task, edit a test repository, run tests, repair an error, and return a usable result without needless routine interruptions.
7. Any approval gate matches the owner-approved execution scope and is visible in logs/documentation.
8. Android and desktop/backend use the same effective behavior settings where applicable.
9. Protected credentials/data remain intact and no release or tool action is falsely reported as successful.
10. Every applicable original audit item has implementation and test references, with outstanding items identified honestly.

## 8. Final delivery

Return:

- Updated `PROJECT_SPEC` and 146-item ledger references.
- Complete restrictions register, with every nontrivial optional limitation disclosed.
- Owner decision log showing what was requested, approved, or deferred.
- Commit references for all changed repositories.
- Reproducible tests, real-world demonstrations, known limitations and release artifacts.
- Explicit statement of what was **verified**, **only simulated**, **blocked by missing credentials/hardware**, or **not yet done**.

**Final governing principle: I define what Cognitive Nexus is meant to become. You bring technical expertise, recommend better methods, implement my approved design, test it thoroughly, and tell me when a real limitation exists. You do not quietly substitute your own design philosophy for mine.**

**Do not stop at this instruction. Incorporate it into the full development roadmap and continue the 146-item audit until all applicable requirements are verified or genuinely blocked.**
