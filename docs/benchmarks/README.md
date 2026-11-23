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
