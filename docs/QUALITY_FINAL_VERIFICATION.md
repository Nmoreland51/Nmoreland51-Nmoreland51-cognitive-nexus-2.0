# Corrective quality phase: final verification

The owner's live testing on 2026-11-23 found seven problems (CN-QA-001 to CN-QA-007). This is the
evidence of what was found, what was changed and what it achieved, at three levels kept apart:
**automated** (the app's own logic, model replies scripted), **real model** (the actual
`dolphin3:8b`, no canned answers), **full integration** (through the running app's chat path, live
web included where it says so).

Branch `quality/corrective-phase`, made from `44c49e7` (CI green). Pull request: see the end.

## In plain words

- **Your adult request is no longer stopped.** It was stopped because an earlier question about a
  child was read together with it, and because the check's answer ("Label: NO") was misread and then
  shown as if the rule had been broken. Both are fixed. Your rule itself is unchanged: the requests it
  covers are still stopped, in every test set. One picture request in the tests is still stopped, by
  the stricter line for pictures that is mine and waits for your decision (D7).
- **The app no longer shortens or cuts answers.** It never read a length you asked for, and its
  default speed setting capped every answer at about 290 words. Now the length you ask for sets the
  limit, an answer that still runs into a limit says so, and when the model itself ends well short of
  or beyond what you asked, a note under the answer says that and that the app did not cut it.
  The model is still not exact about length: 1 of 7 within the range in the last run, 2 of 7 in the one before
  (2 of 7 when the same requests go straight to Ollama).
- **Arithmetic is worked out by the app, not guessed.** 27 of 27 right on your set (24 before). For
  word problems the model writes the sum and the app works it out, showing it: 15 of 18 on
  six problems written afterwards (7 of 18 on the same problems without the change).
- **Web search now works out what you mean and throws out results about something else.** For your
  Omaha question it searches for cannabis, not lawn care; the model checks doubtful results; a poor
  search is tried again with better words; and names in the answer that no source contains are listed
  under it. Live, your question now reads pages about cannabis in Omaha (dispensaries, medical cards,
  legal status) and no lawn care. **Two things did not work:** the answer is still one sentence ("The
  web results do not say which weed in Omaha is the best."), and the search for what the law allows,
  which is built, never ran, because the model always left it empty.
- **Speed.** The app's own delays were two: it held back the first words until 160 characters had
  arrived (about 8 seconds here), and one speed setting made Ollama reload the model between calls
  (about 4.6 seconds each time). Both are gone. The first word now comes 1.9 to 2.6 seconds after
  Ollama alone would give it (10 to 11 seconds before), not "within 0 to 1.6 seconds" as this report
  first said: that figure came from a faulty measurement, corrected on 2026-11-24 (see CN-QA-007
  below). Almost all of the remaining 2 seconds is a new connection opened for every answer, fixed
  on the next branch. The rest is the model, writing about five tokens (roughly four words) a
  second here: a 500-word story takes about two and a half minutes. Web questions take longer than
  before (41 to 48 seconds for yours, 32 in your run) because the model now plans the search and
  checks the results.
- **What this does not change:** the model is an 8B model on a processor. It writes about four
  words a second, is not exact about length, sometimes sets a word problem up wrongly (you see the
  sum it used), and its relevance judgements are sometimes wrong.

## Before and after

All with `dolphin3:8b` on this machine (6-core AMD, 31.2 GB, no graphics card), with the app's own
sidebar defaults (throughput "Fast", Auto Precision on). Before: commit `44c49e7`. After: the commits
named. Each case was run once (lengths) or three times (arithmetic): these are tendencies on small
sets, not rates.

| Finding | Measured | Before | After | Level |
|---|---|---|---|---|
| CN-QA-001 | Adult-only requests wrongly stopped (the owner's cases) | 1 of 6 | **0 of 6** | real model as judge |
| CN-QA-001 | Adult-only requests that depended on the judge | 4 of 6 | **0 of 6** | real model as judge |
| CN-QA-001 | Requests the rule covers, stopped | 2 of 2 | 2 of 2 | real model as judge |
| CN-QA-001 | Full benchmark of the rule, 148 cases in four sets | 147 of 148 | 147 of 148, the same cases | real model as judge |
| CN-QA-004 | Ordinary questions about children, puberty, sex education, a teenager | 4 of 4 answered | 4 of 4 answered | real model as judge |
| CN-QA-002, 003 | Length requests cut off at a token limit | 3 of 7 | **0 of 7** | full chat path |
| CN-QA-002, 003 | Length requests ended complete | 4 of 7 | **7 of 7** | full chat path |
| CN-QA-002, 003 | Within the asked range (±10%) | 0 of 7 | 1 of 7 (2 of 7 in an earlier run) | full chat path |
| CN-QA-002, 003 | The same, straight to Ollama | 2 of 7 | | the model alone |
| CN-QA-002 | An answer outside the asked range says so | never | 6 of 6 that were outside | full chat path |
| CN-QA-004 | 300-word cerebral palsy explanation | 68 words | 215 words | full chat path |
| CN-QA-005 | The owner's arithmetic set, 9 questions × 3 | 24 of 27 | **27 of 27** | full chat path |
| CN-QA-005 | Six word problems written afterwards, × 3 | 7 of 18 | **15 of 18** | full chat path |
| CN-QA-006 | Off-topic results reaching the model, 5 questions written before round three ran | 10 (searched as typed) | **0**; 1 of 15 relevant thrown out | real model, fixed pools |
| CN-QA-006 | The same over all three held-out sets (17 questions) | 33 | 1; 7 of 51 relevant thrown out | real model, fixed pools |
| CN-QA-006 | The owner's question, live: lawn-care pages among those read | 1 of 5 | 0 of 5 (two runs) | full chat path, live web |
| CN-QA-006 | The owner's question, live: the answer | lawn-care sources, an unsupported shop name (the owner's run) | "The web results do not say which weed in Omaha is the best." | full chat path, live web |
| CN-QA-006 | Research answers from fixed sources (9 answerable, 3 not) | 9 right, 0 outside the sources, 1 of 3 said so | 9 right, 0 outside the sources, 1 of 3 said so | real model |
| CN-QA-006 | Planted instructions in web pages obeyed | 0 of 12 | 0 of 12 | real model |
| CN-QA-007 | Time to the first word, the seven length requests (median) | 16.2 s | **6.9 s** | full chat path |
| CN-QA-007 | First word, app against Ollama alone with the same settings (corrected 2026-11-24) | +10.2 to +11.4 s (`44c49e7`) | **+1.9 to +2.6 s** | real model |
| CN-QA-007 | Writing speed, app and Ollama alone | 4.8 to 5.1 tokens a second | the same | real model |
| CN-QA-007 | The owner's Omaha question, start to finish | 32.3 s (the owner's run) | 41 to 48 s (planning and judging added) | full chat path, live web |

## Finding by finding

### CN-QA-001 (P0): an adult request stopped by the content rule — fixed

- **Root cause** (reproduced on `44c49e7`): earlier turns were always read with a new message, so a
  child mentioned in an unrelated earlier question made the adult request a candidate for the closer
  look; with that text in its question the judging model answered "Label: NO"; the reader took the first
  word, found no answer, and the "could not decide" result was shown as a violation.
- **Fix** (`0b7126d`): earlier turns count only when the message does not itself settle that only adults
  are involved, or when it refers back; negations ("no minors", "nobody under 18") and "girls" or "boys"
  with adult ages are not mentions of minors; "Label: NO" is read; an unreadable answer gets its own reply,
  which says it is not a finding. The rule is unchanged.
- **Automated:** 6 adult-only cases are not candidates; 6 guarded cases still are; covered requests
  stopped; ordinary questions about children not looked at (`tests/test_quality_corrective.py`).
- **Real model:** the owner's cases, adult-only requests wrongly stopped 1 of 6 before, **0 of 6** after;
  covered requests stopped 2 of 2 both times; ordinary questions about children, puberty, sex education
  and a teenager's story answered 4 of 4. Full benchmark of the rule, 148 cases in four sets: the same
  147 of 148 as before, case for case; the miss is the picture case under the assistant's stricter line.
- **Full integration:** the owner's request after the cerebral palsy conversation goes through the chat
  path and is answered (stage `not_a_candidate`).
- **Not the same as the model writing it:** when the app lets a request through, the model may still
  decline; that is labelled as the model's refusal, never as the app's rule.

### CN-QA-002 (P1): requested content silently shortened — fixed

- **Root cause:** the planner never read a stated length and added short-answer rules for the kind of
  question; the default "Fast" profile capped every answer at 384 tokens. Nothing after generation
  shortens or rewrites the model's text (traced stage by stage in `docs/GENERATION_RELIABILITY_REPORT.md`).
- **Fix** (`7a07f56`, `e5d289e`, `2a06d88`): a stated length sets the budget, removes the
  short-answer rules and outranks the profile; an answer that hits its limit says so; an answer the model
  ends outside the asked length says so under it, and that the app did not cut it.
- **Automated:** the length is read in its usual forms; the budget outranks "Fast"; the notes appear
  exactly when they should and the text above them is the model's, uncut.
- **Real model:** see CN-QA-003. The owner's own adult request was not generated again: its length went
  through the same planning, now fixed, and the content of that request is not needed to show it.

### CN-QA-003 (P0): long answers stop before completion — fixed for the app; length is the model's

- **Root cause:** the 384-token cap of "Fast" (about 290 words): the 500-word story, the astronaut story
  and the 800-word guide all stopped mid-sentence at it.
- **Fix:** as CN-QA-002.
- **Real model:** seven requests of 100 to 800 words through the chat path. Cut off at a limit: 3 of 7 before, 0 of 7 after. Ended complete: 4 of 7 before, 7 of 7 after. Within ±10%: 0 of 7 before, 1 of 7 after (2 of 7 in the first after-run). The astronaut story: 307 words, cut mid-sentence, before; 580 words, finished, after. Each answer outside its range now says so under it (6 of 6).
- **What is the model's:** sent straight to Ollama, the same seven requests came back within ±10% in 2 of
  7. The app now passes the length on, cuts nothing, and says when the model missed it.

### CN-QA-004 (P1): the educational explanation came back too short — improved, not fully

- **Root cause:** the cerebral palsy request is classed as a simple fact, which brought "Answer in 1-3
  short sentences", "under 75 words" and, after the first fix, "one short paragraph": 68 words before,
  114 after the first fix.
- **Fix** (`7a07f56`, `e5d289e`): a stated length removes all of them.
- **Real model:** 68 words before, 114 after the first fix, 215 after the second: useful, but not the 300 asked for (straight to Ollama: 266).
- Ordinary questions containing child, puberty, sexual education, teenager are answered and not looked
  at by the content rule (real model, 4 of 4; automated tests for the words the owner listed).

### CN-QA-005 (P1): wrong answers to simple arithmetic — fixed for arithmetic; word problems depend on the model's setup

- **Root cause:** every answer was sampled from the model at the chat's temperature (0.35 to 0.7); nothing
  could work a sum out exactly. 24 of 27 right before; "7 times 6" was answered 84 once in the owner's test.
- **Fix** (`7a07f56`, `e5d289e`): plain arithmetic is calculated by the app (a syntax-tree evaluator,
  nothing run as code); for a word problem the model writes only the expression, held to a schema, the app
  refuses one with numbers the question does not give, works it out and shows it; short factual answers
  are sampled at 0.1.
- **Real model:** the owner's set **27 of 27** (24 before), each question three times, with which part
  answered recorded (21 by the calculator, 6 set up by the model and worked out by the app); six word
  problems written afterwards: 15 of 18 (7 of 18 with the unchanged code); the bus problem was set up wrongly every time, and the wrong sum is shown in the answer.
- **Full integration:** the arithmetic path is the chat path (`NexusCore`), with the answer labelled
  "Calculated exactly by the app; no model used" or "set up by the model, worked out by the app".

### CN-QA-006 (P0): poor web-search relevance — much improved, three rounds; not perfect

- **Root cause:** the question was searched as typed, whatever came back went to the model, there was
  no second search, legal context was found only by chance, and names in the answer were not checked.
- **Fix** (`543daf9`, `7a07f56`, `e5d289e`, `2a06d88`): see `docs/WEB_RESEARCH_QUALITY_REPORT.md`:
  the model works out what is meant; it judges results that name nothing of the meant sense; queries that
  spell the meaning out go first; a poor search is refined; one search is made for the law or availability
  the answer depends on; names no source contains are listed under the answer; when the results cannot
  answer, the answer says so and then what they do say.
- **Real model, fixed pools:** on five questions written before round three ran, off-topic results reaching the model fell from 10 to 0, with 1 of 15 relevant results thrown out. Across the three held-out sets the judge threw out 7 of the 51 relevant results it saw and let 1 of 33 off-topic ones through. Round one achieved nothing (the model wrote no other-meaning words); round two halved the off-topic results on the set it had not seen.
- **Full integration, live web:** the owner's question. The old search read a lawn-care page among five; the planned search read none in both later runs (dispensaries, medical-marijuana cards, a news report on legal status). The answer stayed one sentence, "The web results do not say which weed in Omaha is the best.", and the search for legal context never ran: the model left it empty, for all 19 benchmark questions too. 41 to 48 s, against 32.3 s in the owner's run.

### CN-QA-007 (P1): slow answers — the app's own share measured and cut from 10 to 11 s to about 2 s; that 2 s is a new connection per answer, fixed on the next branch

- **Root cause:** two delays of the app's own. The first 160 characters of every answer were held back in case the model echoed the prompt (about 8 s at this machine's speed). And the "Fast" profile sent `num_batch` 256 with chat answers while no other call did, so Ollama reloaded the model (4.6 s) whenever a chat answer followed a content-rule check, a search plan or a judgement, and again after it. The rest is the model: reading the prompt and writing at about 5 tokens a second.
- **Fix** (`e5d289e`, `2a06d88`): text is shown as soon as it cannot be leaked prompt scaffolding
  (usually after a few words) instead of after 160 characters, short conversational replies still
  held until complete; the speed profiles send no load-time option.
- **Real model:** time to the first word through the app against Ollama alone with the same settings: +10.2 to +11.4 s with the code before this phase (`44c49e7`), +1.9 to +2.6 s after (`f7b4892`); writing speed the same, about 5 tokens a second. **Corrected on 2026-11-24:** this report first gave +5.0 to +6.2 s and -0.2 to +1.6 s. The measuring tool opened a new connection to `localhost` for each call straight to Ollama, which on Windows waits about 2 s for an IPv6 attempt first, so Ollama alone looked 2 s slower than it is. The remaining 2 s of the app's is the same cost on the app's side: it opened a new connection for every answer. Fixed after this phase, on the branch `audit/remaining-items`, where the same measurement gives +0.5 to +0.8 s (`quality_after.json`, `profile_after_connection_fix`). The seven length requests: first word after a median of 16.2 s before, 6.9 s after. Web questions now cost one or two more model calls (planning about 17 to 21 s, judging 9 to 30 s, on this machine alone): measured, disclosed, and switched off with `plan_web_search`.

## Regression evidence

**Automated, this machine** (Windows 11, Python 3.13.15), the final code, `python tools/run_checks.py`:
lint, types, secret and private-file hygiene, ledger, register and report checks pass, and the whole
test suite: **1565 passed, 9 skipped, 0 failed**. The 9 skipped are the tests against the real model,
which run only when `CN_LIVE_OLLAMA_URL` is set. New tests in this phase: 108, in
`tests/test_quality_corrective.py`, `tests/test_research_plan.py` and `tests/test_answer_diagnostics.py`.

**Continuous integration** runs the same on every push: Linux and Windows, Python 3.12 and 3.13, plus
an install check and the checks script. Its result for these commits is on the pull request below.

**Real-model regression runs, repeated because a prompt or a rule changed** (each saved result is
tied to the prompt it was made with, and a test fails when they drift apart):

| Measurement | Before this phase | After |
|---|---|---|
| Content rule, 148 cases | 147 of 148 | 147 of 148, the same cases |
| Research answers from fixed sources | 9 of 9 right, 0 of 12 outside the sources, 1 of 3 said so | the same |
| Instructions hidden in web pages | 0 of 12 obeyed, the fact kept 14 of 14 | the same |

**Existing tests changed on purpose**, each named in its commit:

- `tests/test_nexus_core.py`: with no search results the model may now be asked what a question means,
  but still not to answer it (`566c828`); the "turbo" test asserted `num_batch` 512 and now asserts
  that none is sent, the cause of the reloads (`2a06d88`).
- `tests/test_web_research.py`: the size bound of the snippet-cap test allows for the two sentences
  added to the answer prompt; the cap itself is still checked by the word count (`2a06d88`).

No test was disabled and no assertion removed.

**Commits on `quality/corrective-phase`:** `0b7126d` (content rule), `543daf9` (search planning),
`7a07f56` (length, stop reason, calculator), `566c828` (measuring tools, tests, the before-run),
`e5d289e` (second round: short-answer rule, word problems, first word), `cfab5f3` (Diagnostics),
`2a06d88` (the model judges results, legal-context search, length notes, no reloads), and the commit
with these results and reports.

## Roadmap

The seven findings are in the audit ledger as their own group (`docs/backlog/owner_control.json`,
group `quality`, statuses in `docs/backlog/status.json`, shown in `docs/AUDIT_146_PROGRESS.md` and
counted in `docs/FINAL_VERIFICATION_REPORT.md`). Items of the 146 that this phase gave new evidence
for: 011, 020, 023, 096, 097, 106, 108, 115, 126, 141 (statuses and evidence in the ledger; only 108
became complete, with evidence from the earlier security work).

## Not done, and why

- **Length within ±10% (CN-QA-003) and the 300-word explanation (CN-QA-004).** The app passes the
  length on, cuts nothing and says when the model missed it; the model kept to the range in 1 or 2 of
  7 through the app and 2 of 7 alone. Not tried: telling the model a paragraph count for a length, or
  asking it to continue when it ends far short (which would double the wait on this machine). A model
  that keeps to length better is your decision: you chose to keep `dolphin3:8b`.
- **Web answers to questions the results cannot settle (CN-QA-006).** The answer to your Omaha
  question is still one sentence. Not tried: showing the model an example of a good answer of that
  kind in the prompt.
- **Legal and availability context (CN-QA-006).** Built, tested, and never run with this model, which
  left the search empty every time. Not tried: a separate question to the model, or always making the
  search.
- **Comparisons and citations in chat answers (CN-QA-006).** A chat answer names the result a point
  comes from at most; the app shows the sources under it. Full research answers have source lists.
- **Wrong judgements of search results.** 7 of 51 relevant results thrown out on unseen questions.
- **Word problems the model sets up wrongly** (the bus problem) cannot be caught by the app; the sum it
  used is shown.
- **Live search sources.** Only the free search-page library and Wikipedia were available; a SearXNG
  server or a Brave Search key, yours to set up, would make live results more dependable.
- **Not re-measured with the new answer prompt:** the two weaker settings for outside text (mark only,
  no handling); the default was measured again.
- **The owner's adult-fiction request of CN-QA-002 was not generated again;** its length goes through
  the same planning as the measured requests.
- **Not done at all here:** the app clicked through by hand in the browser after these changes; a
  phone; cloud models.
- **Your decisions, unchanged by this phase:** the stricter line for pictures (D7, mine), which stops
  one ordinary picture request in the tests; the 16 private files still tracked in the repository.
