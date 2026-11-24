# Factual reliability (CN-QA-005)

"What is 7 times 6?" came back 84 once in three through the chat on 2026-11-23. The model was
sampling at the chat's usual temperature (0.35 to 0.7) and nothing in the app could work the answer
out exactly.

## What changed

Commits `7a07f56` (calculator, temperature) and `e5d289e` (word problems):

- **Plain arithmetic is calculated, not sampled.** `modules/calculator.py` answers a question that is
  nothing but arithmetic ("what is 17 times 23", "15% of 80", "-15 plus 8", "3.5 x 2.4", "(4 + 6) / 4",
  "the square root of 81"). It walks the expression's syntax tree; nothing is evaluated as code. The
  answer shows the calculation and is labelled "Calculated exactly by the app; no model used".
  Division by zero is said plainly. Anything else ("what is the x in algebra", "what is 2026", "what is
  a times table") goes to the model.
- **Word problems: the model sets up, the app calculates.** For a short question with at least two
  numbers that asks for a quantity, the model is asked only for the expression, held to a JSON Schema.
  The app refuses an expression that uses a number the question does not give (units such as 60 or 100
  aside), works the rest out exactly, and shows the expression, labelled "set up by the model, worked
  out by the app". When that fails, the model answers as before.
- **Short factual answers at temperature 0.1.** Questions the planner classes as simple facts no longer
  sample at up to 0.55. Writing and conversation keep their temperatures.

Limits: a wrong expression that uses only the question's numbers, or a unit number such as 7 or 60,
gets through; it is visible in the answer. The calculator does not read units ("3 hours in minutes")
or dates; those go to the model or to the word-problem path.

## Results

Through the app's whole chat path, with its default settings, each question three times, with which
part produced the answer recorded (`tools/quality_check.py`; `docs/benchmarks/quality_before.json`,
`quality_after.json`).

**The owner's set** (written from the finding before any fix: multiplication, division, negatives,
decimals, a percentage, two word problems, and "7 times 6" after being told it is 48):

| | Before (`44c49e7`) | After |
|---|---|---|
| Right | 24 of 27 | **27 of 27** |
| Wrong | 3.5 × 2.4 as 8.8 once; "50 dollars, spent 18, earned 25" as 17 twice | none |
| Answered by | the model, 27 | the app's calculator 21; set up by the model and worked out by the app 6 |
| Median time | 4.0 s | under 0.1 s (calculator); 6 to 12 s for a word problem |

**Six word problems written after the word-problem path was built**, run on both versions with
nothing adjusted to them:

| Problem | Before | After | How the after answers came about |
|---|---|---|---|
| 4 tickets at $45 and a $6 fee | 1 of 3 (186, 180, 51) | **3 of 3** | (45 × 4) + 6 |
| A bus: 38 seats taken, 17 get off, 9 get on | 0 of 3 (28, 18, 29) | 0 of 3 | the model wrote (52 − 17 + 9) − 38 = 6 each time; the sum is shown, so the mistake can be seen |
| 250 g of flour for 4 people, for 10 | 0 of 3 (10 each time) | **3 of 3** | (250 × 10) ÷ 4 |
| 18 km in 45 minutes, km per hour | 3 of 3 | **3 of 3** | 18 ÷ (45 ÷ 60) |
| $120 coat at 25% off | 3 of 3 | **3 of 3** | the model's own answer: the word-problem path gave none (no usable expression), so the model answered as before (30 to 41 s); why was not traced |
| $84 shared by three, $3 tip each | 0 of 3 (30, 27, 30) | **3 of 3** | (84 + 3 × 3) ÷ 3 |
| **Total** | **7 of 18** | **15 of 18** | |

What this shows: the arithmetic itself is no longer a matter of chance. A word problem is still only as
good as the model's reading of it: the bus problem was set up wrongly every time, and an app that
cannot read the question better than the model cannot catch that; it can only show the sum it used.
