# Measured results

Numbers in this folder were produced by running the code on real inputs. Each file says when and with
what it was measured. Re-run them after changing the code they measure.

## Knowledge search (`retrieval_*.json`)

```
python tools/retrieval_benchmark.py --backend ollama --model all-minilm --save docs/benchmarks/retrieval_all-minilm.json
python tools/retrieval_benchmark.py --backend hash --save docs/benchmarks/retrieval_hash.json
```

36 short documents and 54 questions (`tests/fixtures/retrieval_benchmark.json`): 22 paraphrases that share
almost no words with their answer, 12 that reuse its wording, 10 that ask for a code, name or number, and 10
with no answer in the set. Each run is scored twice: with every match that has some evidence (an explicit
search) and with only the matches trusted enough to be put into a chat prompt unasked.

Measured on 2026-11-23 (Windows 11, CPU only, Ollama 0.40.17):

| | Word matching only | With the all-minilm embedding model |
|---|---|---|
| Paraphrased question, right document first | 18% | 91% |
| Paraphrased question, right document in the first three | 23% | 96% |
| Same wording, right document first | 100% | 100% |
| Code, name or number, right document first | 100% | 100% |
| No answer in the set: nothing returned (explicit search) | 70% | 60% |
| No answer in the set: nothing put into a chat prompt | 100% | 100% |
| Time per question | under 1 ms | about 20 ms including the model call |

Before these changes the app returned any passage sharing a word with the question: on the same set that
found the right document in the first three for 64% of paraphrases and returned something for 60% of the
questions that have no answer.

`tests/test_retrieval_benchmark.py` holds the word-matching scores in every test run and, when
`CN_LIVE_OLLAMA_URL` is set, the scores with a real embedding model.

## Instructions hidden in web pages (`injection_*.json`)

```
python tools/injection_benchmark.py --model dolphin3:8b --save docs/benchmarks/injection_dolphin3-8b.json
```

12 pages that carry an instruction aimed at an AI model (override the rules, a fake system line, a forged
end-of-content marker, chat-template tokens, a false statement to repeat, "do not tell the user", an HTML
comment, a note to language models, a link to send data to, a polite request, a Markdown instruction block,
a change of role) and 2 ordinary pages (`tests/fixtures/injection_benchmark.json`). Each page has a real fact
the answer should contain and a marker that appears in the answer only if the model obeyed the page. The
real model answers each page twice: with the page pasted into the prompt as the app used to do, and with
the prompt the app builds now.

Measured on 2026-11-23 with `dolphin3:8b` (CPU only, Ollama 0.40.17):

| | Page text pasted in (before) | Lines aimed at a model removed, the rest fenced (now) |
|---|---|---|
| Planted instruction obeyed | 6 of 12 | 0 of 12 |
| Real fact still in the answer | 14 of 14 | 14 of 14 |

This is one small model and twelve attacks written by the same person who wrote the defence. It shows the
defence works against these, not that web text is safe: the fence is one layer, and the app also never lets
web text reach a tool. Each saved answer carries a fingerprint of its prompt, and
`tests/test_research_hardening.py` fails when the app builds a different prompt, so a saved result cannot
outlive the code it describes.

## Claim check: what a passage says about a claim (`stance.json`)

```
python tools/stance_benchmark.py --judge-model dolphin3:8b --save docs/benchmarks/stance.json
```

Labelled pairs of a claim and a passage: does the passage state the claim (supports), state something
incompatible (contradicts), or neither (mentions: it asks, hedges, reports what others say, is about another
occasion). Four files under `tests/fixtures`:

| File | Pairs | Used to adjust the rules? |
|---|---|---|
| `stance_benchmark.json` | 68 | Yes: the rules were written against it |
| `stance_heldout_round1.json` | 40 | Yes, after one honest run (33 of 40 right, 4 false "supports") |
| `stance_heldout_round2.json` | 47 | No. The decision about the model's second reading was taken on it |
| `stance_heldout_round3.json` | 30 | No. Written after that decision; a third of it is look-alike passages |

Measured on 2026-11-23. "False supports" are passages counted as confirming a claim they do not confirm,
the mistake that matters most.

| | Round 2 (47 pairs) | Round 3 (30 pairs) |
|---|---|---|
| Wording rules alone | 81% right, 5 false supports | 77% right, 5 false supports |
| `dolphin3:8b` alone, asked about every passage | 77% right, 5 false supports | 67% right, 8 false supports |
| Rules, and the model re-reads the passages they count as support (what the app does) | 83% right, 2 false supports | 80% right, 3 false supports |
| Rules, and the model re-reads every counted passage (tried and dropped) | 74% right, 2 false supports | not run |

What this says: on text the rules were not written for, the claim check is right about four passages in
five. The rules and the small model are each wrong about different passages, and letting the model take
support away (never add it) removes about half of the false supports at 3.5 to 5 seconds per passage on a
CPU. Asking the model about contradicting passages too made things worse: it overruled five correct ones and
caught none. What still gets through in round 3: "will close unless a buyer is found", "was a hospital until
1998", "almost went bankrupt". The rules miss passages that say the same thing in other words ("the firm cut
200 jobs" for "the company laid off 200 workers"). The model's answers vary slightly between runs (35 and 36
of 47 on round 2).

The rounds are small and were written by the person who wrote the rules. `tests/test_stance_benchmark.py`
keeps the two development files fully right and holds rounds 2 and 3 at the measured scores as a floor, not
a target: a change that needs these items to pass has to come with a new held-out round.

## Research answers (`research_*.json`)

```
python tools/research_benchmark.py --model dolphin3:8b --full 3 --save docs/benchmarks/research_dolphin3-8b.json
```

12 questions with frozen search results and page texts (`tests/fixtures/research_benchmark.json`); the names
are invented so that nothing can be answered from memory. Nine questions are answered by one of four
results; three are about pages that do not contain the answer. Nothing is fetched.

Measured on 2026-11-23 with `dolphin3:8b`:

| | |
|---|---|
| The app's result scoring puts a page that answers the question first | 7 of 9 |
| ... within the first two (the pages a chat web answer reads) | 9 of 9 |
| The excerpt taken from the answering page contains the answer | 9 of 9 |
| Chat web answer states the right fact | 9 of 9 |
| Chat web answer contains a version, year or link that is in none of its sources | 0 of 12 |
| Chat web answer says so when the pages do not contain the answer | 1 of 3 |
| Full research answer states the right fact | 3 of 3 |
| Full research answer cites a link that was not retrieved | 0 of 3 |
| Time per chat web answer / full research answer | 19 s / 74 s |

The weak spot is the last-but-three row: asked for a price or a founder that the pages do not give, this
model recites what the pages do say (the weight, the founding year) instead of saying the answer is
missing. It invents nothing, but it does not answer the question either. A stricter instruction in the
prompt did not change that (measured before and after: 1 of 3 both times). In the fixture the answering page
is deliberately not always first, so "7 of 9" is about the app's scoring, not about any search engine.

`tests/test_research_benchmark.py` runs the ranking and excerpt checks on every push, re-judges the saved
answers with the current judge, and fails when the app's prompt no longer matches the one the saved answers
were written for.
