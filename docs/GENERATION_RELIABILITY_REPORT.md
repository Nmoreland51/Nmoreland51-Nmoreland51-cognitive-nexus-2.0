# Generation reliability (CN-QA-002, CN-QA-003, CN-QA-004, CN-QA-007)

Answers that were shorter than asked, answers that stopped mid-sentence, and slow answers. All
measured with `dolphin3:8b` on this machine (6-core AMD processor, 31.2 GB, no graphics card), with
the app's own sidebar defaults: throughput profile "Fast", Auto Precision on.

## Where a request's length could be changed, end to end

Traced in the code, message to screen. Each stage and what it could do to length or content:

| Stage | Could change | Before | Now |
|---|---|---|---|
| Content rule (`behavior_policy`) | whether it is answered | see `CONTENT_RULE_VERIFICATION.md` | |
| Routing (`nexus_router`) | kind of question, temperature | a temperature per route | unchanged |
| Response planner (`response_planner.plan_response`) | token budget, length rules | fixed budget per kind of question; never read a stated length; "Answer in 1-3 short sentences", "under 75 words", "one compact paragraph", "one short paragraph" | a stated length sets the budget and removes those rules |
| Answer rules (`build_planned_chat_prompt`) | the rules the model reads | "Maximum output: about N tokens" with the short rules | the length rule instead, when a length is stated |
| Throughput profile (`_apply_throughput_profile`) | token limit, window, temperature | "Fast" (the default) capped every answer at 384 tokens and a 2,048 window | a stated length outranks it |
| Context budget (`context_budget`) | window and reply room | sized to fit the prompt and reply | unchanged |
| Generation (Ollama) | stops at the limit or by itself | stop reason ignored | read: "length" is shown and recorded |
| Echo guard (`stream_chat_response`) | when text appears; drops a leaked prompt | held back the first 160 characters | shows text once it cannot be the prompt's scaffolding |
| Clean-up (`_clean_model_answer`) | removes leaked prompt lines only | unchanged | unchanged |
| Notes (unsourced numbers and names, cut-off notes) | appended, never replacing text | | the cut-off note is new |

Nothing after generation shortens or rewrites the model's text. The only removals are leaked prompt
scaffolding, which is not the model's answer.

## Causes, confirmed

See `QUALITY_BASELINE.md`. In short: the planner never read a stated length; the default speed
profile capped every answer at 384 tokens; nothing looked at why the model stopped; and the
simple-fact profile told the model to answer in "one short paragraph". The cerebral palsy request is
classed a simple fact. Sent straight to Ollama the same requests came back 2 to 3 times longer, so the
shortening was the app's.

## What changed

Commits `7a07f56` (length, stop reason), `e5d289e` (the last short-answer rule, the first word) and
`cfab5f3` (Diagnostics), and `2a06d88` (the length note, no reloads):

- `requested_length()` reads "about 300 words", "a 150-word ...", "450 to 550 words", "between ... and
  ...", "at least ...", "no more than ...", "three paragraphs". The token budget becomes the upper bound
  times 1.45 plus 80, and the length rule replaces the short-answer rules of the kind of question.
- That budget outranks the speed profile.
- When the model stops at its token limit, the answer ends with "[Stopped at the output limit of N
  tokens before the answer was finished. Say "continue" for the rest.]", and the record says why it
  stopped, with the limit, window, temperature and the requested and written lengths (shown in
  Diagnostics, "How the last answer was made").
- An answer that breaks off or times out keeps its text and says so, as before (tested now: QA-10, QA-12).
- The start of an answer is shown as soon as it cannot be leaked scaffolding, instead of after 160
  characters.

Continuing a cut-off answer is left to the owner ("continue"): an automatic second request would
double the wait on this machine and could repeat text.

- An answer the model ends outside the asked range, by itself, now says so under it, for example
  "[About 100 words, fewer than the 270 to 330 you asked for. The model ended here by itself; nothing
  in the app shortened it. Ask for more if you want it longer.]"
- Short conversational replies are still held until complete, because stock phrases are taken out of
  them then; found by an existing test when the first word was made faster.
- The speed profiles no longer send `num_batch`, which made Ollama reload the model (below).

## Results

### Length (CN-QA-002, CN-QA-003, CN-QA-004)

The seven requests through the app's whole chat path with its default settings, word counts of the
model's text (the app's notes left out). Before: `44c49e7`. First after-run: `566c828`. Final: every
change of this phase. Straight to Ollama: the same request with nothing added, before the change.

| Request | Asked | Before | First after-run | Final | Straight to Ollama |
|---|---|---|---|---|---|
| 100-word story | 90-110 | 74 | 147 | **96** | 118 |
| 150-word story | 135-165 | 171 | **152** | 167, noted | 204 |
| 300-word explanation of vaccines | 270-330 | 89 | 422 | 100, noted | **296** |
| 300-word cerebral palsy explanation | 270-330 | 68 | 114 | 215, noted | 266 |
| 500-word story | 450-550 | 313, cut off | **461** | 564, noted | **535** |
| The astronaut story | 450-550 | 307, cut off | 410 | 580, noted | 406 |
| 800-word guide | 720-880 | 302, cut off | 504 | 635, noted | 552 |
| **Cut off at a token limit** | | **3 of 7** | 0 of 7 | **0 of 7** | |
| **Ended by itself, complete** | | 4 of 7 | 7 of 7 | **7 of 7** | |
| **Within the asked range** | | 0 of 7 | 2 of 7 | 1 of 7 | 2 of 7 |

Bold in a row: within the range. "Noted": the answer ends with the new length note.

What this shows:

- **What the app did is fixed.** No answer is cut off any more, every answer ends by itself, and an
  answer outside the range says so and whose doing it is.
- **What is left is the model's.** Sent straight to Ollama with nothing added, the model kept to the
  range in 2 of 7; through the app now, 1 of 7 and 2 of 7 in two runs. It varies from run to run more
  than the app changes it: the vaccines explanation came back at 422 words in one run and 100 in the
  next, with the same settings. Long pieces come out short and short pieces slightly long.
- **The cerebral palsy explanation** grew from 68 words to 215: useful, but not the 300 asked for.

### Speed (CN-QA-007)

`tools/quality_check.py --only profile`: each prompt once through the app to load the model, then
straight to Ollama with the window, token limit and temperature the app used, then through the app
again. Same machine, model and settings throughout. The app is measured with the address it is given
(`http://localhost:11434`, the default); the calls straight to Ollama go to `127.0.0.1` on a
connection that is kept open, so they show Ollama's own time.

**Corrected on 2026-11-24.** The first version of this measurement opened a new connection to
`localhost` for every call straight to Ollama. On Windows a new connection to `localhost` is tried
over IPv6 first, which Ollama does not listen on, and that took 2.05 s every time on this machine
(against 0.04 s to `127.0.0.1`). So the "Ollama alone" times were about 2 s too long, and the app's
share came out too small: +5.0 to +6.2 s before the reload fix and −0.2 to +1.6 s after, figures this
report, `QUALITY_FINAL_VERIFICATION.md` and the ledger gave until then. Measured again with the
corrected tool, against the code before the corrective phase (`44c49e7`) and after it (`f7b4892`):

| Prompt | First word: app | First word: Ollama alone | The app's share | Writing: app / alone |
|---|---|---|---|---|
| Short question, before (`44c49e7`) | 16.33 s | 4.97 s (4.1 s of it loading the model) | +11.4 s | 5.2 / 5.3 tokens a second |
| 150-word story, before | 15.53 s | 5.33 s (4.4 s loading) | +10.2 s | 5.1 / 5.1 |
| 300-word explanation, before | 16.35 s | 5.29 s (4.3 s loading) | +11.1 s | 5.1 / 5.1 |
| Short question, after (`f7b4892`) | **3.08 s** | 0.46 s | **+2.6 s** | 5.2 / 5.3 |
| 150-word story, after | **2.72 s** | 0.63 s | **+2.1 s** | 5.0 / 5.2 |
| 300-word explanation, after | **2.52 s** | 0.67 s | **+1.9 s** | 4.9 / 5.0 |

**What the app's remaining 2 s is.** Not reading its instructions: Ollama's own count says the app's
prompt took 0.21 s to read on these calls (it still had most of it from the call before). It matches
the cost of a new connection to `localhost`: the app's request for a streamed answer was left before
its last bytes were read, so its connection was closed and the next answer opened a new one, through
the same IPv6 attempt. That is fixed after this phase (on the branch `audit/remaining-items`: local
servers are addressed as `127.0.0.1`, and a streamed answer is read to its end so its connection is
kept). Measured there the same way, the app's share is +0.54 s for the short question, +0.75 s for the
story and +0.56 s for the explanation. That is about as long as the model takes to write its first few
words (it writes about five tokens a second), which is what the app waits for before it shows any text,
so that leaked prompt text can be held back; it was not timed separately.

**The reloads.** Before the fix the call straight to Ollama spent 4.1 to 4.6 s loading the model each
time, although the model was loaded. Ollama's log said why: "reloading model, runner options changed".
The "Fast" profile sent `num_batch` 256 with every chat answer; nothing else sent it, and it is an
option Ollama loads the model with. So the model was loaded again whenever a chat answer followed
another kind of call, and again after it: the content-rule check, the search plan, the result judge,
the web answer, or here the direct call. The speed profiles now send no load-time option. The same
cause inflated the "before" times of the length requests, which alternated with direct calls.

**Where the time goes now** (the length requests, through the app, last run): the first word after a
median of 6.9 s (16.2 s before), and the rest is the model writing at about 5 tokens a second: a
500-word story takes about two and a half minutes, as it does straight from Ollama. Of the first-word
time, the app's own work (planning, building the prompt, the content rule's first look) is under 0.1 s;
about 2 s is the new connection each answer opened (see above), and the rest is the model reading the
prompt (about 200 to 260 tokens here) and starting. These are
model-bound; nothing in the app can make this model write faster on this processor.

**What the corrective phase added.** Web questions now cost one model call to plan the search (about
17 to 21 s here) and, when some results are doubtful, one to judge them (about 9 to 30 s), before the
answer is written. That is a trade of time for relevance, chosen and measured, and it can be switched
off with the setting `plan_web_search`. The live Omaha question took 41 s with planning against the
owner's 32.3 s before, without the judge; see `docs/WEB_RESEARCH_QUALITY_REPORT.md` for the round
with it.

The owner's own timings of 2026-11-23, for comparison: the astronaut story took 117.8 s and was
incomplete; it now takes about 160 s and is finished (580 words). The cerebral palsy explanation took
71.4 s for a short answer; it now takes 64 s for 215 words.
