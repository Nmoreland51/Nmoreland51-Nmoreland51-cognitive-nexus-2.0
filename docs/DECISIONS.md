# Decisions

Only choices made in the Grok backup session of 2026-11-23. Older owner-control decisions stay in `docs/owner/P0_OWNER_CONTROL_DIRECTIVE.md`.

## D-XAI-1. xAI is optional and off by default

`xai` is not in `DEFAULT_CONFIG["provider_order"]`. A saved config that does not list it does not gain it. Setting `XAI_API_KEY` does not by itself send prompts to xAI.

If the owner adds `xai` behind another provider, it runs only when "Allow cloud fallback" is on. If the owner puts `xai` first, that is an explicit choice and the fallback switch is not required. This matches the rule already used for OpenAI and Anthropic.

## D-XAI-2. Prompts are not stored on xAI unless the owner opts in

xAI's Responses API stores responses for 30 days unless `store` is false. `xai_store_responses` defaults to false, and the adapter sends `store: false`. The prompt is still transmitted when the provider runs. The answer label includes that destination.

`previous_response_id` is sent only when storage is on. With storage off, multi-turn context is the messages the app already has, sent again in `input`.

## D-XAI-3. Reasoning effort low is a latency default, not a content filter

`xai_reasoning_effort` defaults to `low` so chat requests do not use xAI's high reasoning default. It does not add a refusal rule. Set `XAI_REASONING_EFFORT` empty to omit the field and take xAI's own default. The owner can set `low`, `medium`, `high`, or `xhigh`.

## D-XAI-4. No published price was copied

Token counts are recorded when xAI returns them. `estimated_cost_usd` is left unset, and the label says the price is not known. A guessed price would be presented as a fact.

## D-XAI-5. The seven failing tests were aligned with owner control, not reverted

`561101d` left tests expecting `direct_harmful_instruction`, canned redirects, and "Do not provide step-by-step" under the default reality check. The code already classifies topics as `not_classified` and labels fiction instead of withholding it. The tests were updated to that behavior. `reality_check=withhold` still produces the older step-by-step constraint when the owner selects it. No keyword filter was added.

## D-XAI-6. Base the review on the newest pushed branch

The draft pull request targets `fix/chat-speed-web-search-images`, not `main`. `main` is `dce9ee0` (2026-07-02). A pull request into `main` would mix this work with the 50 commits already on the active branch.

## Not decided here

- Which Android branches to merge.
- Whether live files should be encrypted (audit item 112).
- A replacement for the default OpenAI or Anthropic model ids.
- Enabling paid xAI fallback on the owner's machine. That stays off until Nate turns it on.
