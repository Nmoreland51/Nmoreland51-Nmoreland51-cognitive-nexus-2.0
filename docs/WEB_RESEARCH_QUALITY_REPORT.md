# Web research quality (CN-QA-006)

The owner asked "Search the web for the best weed in Omaha" and got lawn-care results, generic
listings, a recommendation the shown sources did not support, and "the results do not say" without a
second search.

## Causes

Traced through `modules/nexus_core.py` (chat web answers) and `modules/web_research.py`:

| Stage | Before |
|---|---|
| Intent | none: the router's search query, or the message, was searched as typed |
| Query expansion and refinement | none: one search |
| Relevance | none: whatever came back went to the model, in the engine's order |
| Source selection | the first two pages were read, in search order, listing pages included |
| Legal and availability context | searched only if the question's own words happened to find it |
| Claims in the answer | version numbers, years and links were checked against the sources; names were not |
| Insufficient evidence | "The web results do not say ..." after one search, and nothing else |

## What changed, in three rounds

Each round was measured with the real model before the next was designed, and each was then
measured on questions written before it ran (below).

**Round one** (commits `543daf9`, `7a07f56`, `e5d289e`; `modules/research_plan.py`):

1. **What is meant.** Before searching, the local model reads the question once, held to a JSON
   Schema: what it is about with any ambiguous word spelled out ("weed" as cannabis), two or three
   queries, words that would only appear in pages about another meaning, and what kind of page would
   answer it.
2. **Relevance.** A result carrying other-meaning words and fewer words of the meant sense is dropped,
   with the reason kept. Listing pages are kept but read last.
3. **Refinement.** The queries are searched in turn until two relevant non-listing results are in
   hand, at most three searches.
4. **Names.** The answer prompt says what is meant and to name only businesses, products and places
   that are in the results; names in the answer that appear in no source and not in the question are
   listed under it ("Not found in the sources above: ...").

Measured: the model spelled the meaning out correctly for all seven questions, but **left the list of
other-meaning words empty every time** and put the question's own words first among its queries. So
nothing was dropped and the first search found what the question as typed finds: 3 of 5 results
about lawn care for the Omaha question, the same as before. Asking it first to name the other meanings
did not help ("none", even for "weed").

**Round two** (`2a06d88`):

5. **The model judges doubtful results.** A result that contains a word of the meant sense that the
   question does not ("cannabis") is kept. For each result that only shares the question's words, the
   model is asked, held to a schema, to say in a few words what the result is about and then whether
   that is what the person means; a "no" drops it, with the model's description as the reason. Writing
   the description first was more reliable than a bare yes or no in a probe on the development case.
6. **Queries that spell the meaning out are searched first.**
7. Words the model copied from the prompt's own example ("snake, reptile, venom") are not used.

Measured on six new questions: off-topic results halved (12 to 6), nothing relevant dropped. Five of
the six that remained came from two questions where the plan added no word of its own ("a good gaming
mouse", "a glass pitcher"), which round two did not judge.

**Round three** (`2a06d88`):

8. **Every result is judged when the plan adds no words of its own.** The model saw nothing ambiguous
   in "gaming mouse"; a keyword search still finds pest control.
9. **Legal and availability context.** The plan names one more search, for what the law allows or what
   is available where the question is about, when the answer depends on it ("Nebraska cannabis law").
   It is made whatever the other searches found, and up to two results carrying at least half of its
   words are added after the others. The real model left it empty every time (see Results), so with
   this model it does not run.
10. **When the results do not answer, say so, then say what they do say.** The answer prompt used to
    end there ("do not offer other facts in its place"), which turned the live Omaha answer into one
    sentence. It now says what is missing, then adds in one or two sentences what the results do say
    that bears on the question, naming the result each point comes from.

The plan, every search (with what it returned, kept, dropped and why, and whether it was the context
search), are recorded with the answer and shown in Diagnostics. Without a model, or with the setting
`plan_web_search` off, the question is searched as typed, as before.

Also from the other agent's branch (`ee13bd0`): page extraction takes one lock, because two parallel
extractions abort Python 3.13 on Linux.

## Results

### Fixed pools of results, real model (`tools/research_relevance_benchmark.py`)

Ambiguous local questions, each with a fixed pool of made-up results, some about what was asked and some
about another meaning of a word in it. The search is simulated (results ranked by how many of the query's
words they contain), so every version sees the same engine. Counted: results about another meaning that
reach the model, and relevant results thrown out. Each held-out set was written before the round it
measures ran on any held-out question (`tests/fixtures/research_relevance_benchmark.json`).

| Set | Questions | Written | Searched as typed (old) | Round one | Round two | Round three |
|---|---|---|---|---|---|---|
| dev (the Omaha question) | 1 | with the planner | 3 of 5 off-topic | 3 | 1 | 1 |
| dev, the other meaning ("weeds in my lawn") | 1 | in round two | 2 of 5 | | 0 | 0 |
| heldout | 6 | before round one | 11 off-topic | 11, 0 dropped wrongly | 0, 2 dropped wrongly | 0, 2 dropped wrongly |
| heldout2 | 6 | before round two | 12 | | 6, 0 dropped wrongly | 1, 4 dropped wrongly |
| heldout3 | 5 | before round three | 10 | | | **0, 1 dropped wrongly** |

The fairest single figure is the last set, which round three never saw: **off-topic results reaching the
model fell from 10 to 0, and one relevant result of 15 was thrown out** (a Reddit thread asking where to
buy Medjool dates). The cost shows on heldout2: judging every result when the plan adds no words of its
own removed most of what got through in round two (6 to 1) but also threw out four good results (a
pitcher comparison, a thrift shop, a guide to choosing a canoe, a page on repairing a cracked bat).
Questions left with no relevant result: none in any set.

The model wrote no other-meaning words in any round (see round one), and **left the search for legal and
availability context empty for all 19 questions**. That part of round three is in place and tested, but
with this model it never runs.

Time on this machine, round three (the test suite was running alongside, so slower than alone): planning
a median of 26 to 27 s, searching and judging 24 to 29 s. In round two, alone: 17 to 21 s and 9 to 30 s.

### The owner's question, live (`Search the web for the best weed in Omaha.`, through the chat path)

Free search sources only (the search-page library, then Wikipedia); results differ from run to run.

| | Results the model read | Lawn care among them | Answer | Time |
|---|---|---|---|---|
| Before: searched as typed | two Yelp lists, Where's Weed, a Yellow Pages weed-control page, an online shop | 1 | (the owner's run: lawn-care sources, an unsupported shop name) | 32.3 s (the owner's run) |
| Round one, without the judge | three unrelated Wikipedia articles (the search source had fallen back) | 0 | "The web results do not say which cannabis dispensary is the best in Omaha." | 87 s |
| Round two | a Reddit thread on Omaha dispensaries, a dispensary's page, a news report on the Omaha Tribe legalising medical cannabis, a Yelp list | 0 | "The web results do not say which specific cannabis product is the best in Omaha." | 41 s |
| Round three | four pages on medical-marijuana cards in Omaha, a Yelp list | 0 | "The web results do not say which weed in Omaha is the best." | 48 s |

What this shows: the search now finds what is meant and no longer feeds the model lawn care. The answer
is still poor. A question about "the best" has no answer in these sources, and the model says so in one
sentence instead of saying what the results do offer. The new wording asks it to go on to what the
results say; it did so in one of the fixed research questions and not here.

### Answers from fixed sources, and hidden instructions (run again because the answer prompt changed)

- `tools/research_benchmark.py`: right 9 of 9, nothing from outside the sources in 12 of 12, "the sources
  do not say" in 1 of 3 (unchanged), full research answers 3 of 3.
- `tools/injection_benchmark.py`: planted instructions obeyed 0 of 12, the real fact kept in 14 of 14
  (unchanged).

## Limits

- The model decides what is meant. On a question where it guesses wrong, the plan searches for the
  wrong thing; the plan is shown so that can be seen.
- Relevance is judged from a result's title, snippet and address, not the whole page, by an 8B model
  that is sometimes wrong: in round three it threw out 7 of the 51 relevant results it saw across the
  held-out sets, and let 1 of the 33 off-topic ones through.
- The free search sources here return what they return. Neither SearXNG nor a Brave key is set up, so
  the app uses the free search-page library, which is often rate-limited, and then Wikipedia. In one
  live run a second query came back with three unrelated Wikipedia articles; the judge now drops such
  results, but it cannot find better ones.
- No current menus or prices came back for the Omaha question, and the app does not invent them.
- Each planned web question costs one model call to plan it (about 17 to 21 s here) and one to judge
  doubtful results (about 9 to 30 s), on this machine's processor.
