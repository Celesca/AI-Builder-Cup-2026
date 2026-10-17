# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: a plant manager or lean (Kaizen) engineer who opens the dashboard after a shift, at a desk, to review what the cameras saw, tune the safety rules, and decide which Gemba Kaizen actions to approve. The job is making decisions about waste and safety from footage they did not watch, not babysitting a live feed.
Secondary (named in the architecture, not yet designed for): the line operator, who is asked clarifying questions by a Thai voice agent; the manager reads reports in Japanese or English.

## Product Purpose

Factories already have CCTV but no insight from it. VALZ turns workstation video into approved Gemba Kaizen actions: a Safety Agent checks safety rules and labels what the worker is doing in every sampled frame; a Gemba Kaizen Agent turns the measured waste and incidents into Gemba Kaizen cards with an ROI estimate. Success is a manager who trusts the numbers enough to act on them, and an operator who is asked instead of second-guessed when the system is unsure.

## Positioning

"The system says what it doesn't know, then asks the person who does." Time and counts are measured by plain computer vision and arithmetic, never by the language model; the vision model only judges what is visible; the LLM explains and cites a lean knowledge base (every suggestion names its source card and the video moment). A generic CCTV analytics dashboard cannot truthfully say that every number is traceable to a timestamp.

## Operating Context

- Input is a short workstation clip (upload) or, later, a live stream; the pipeline samples about 1 frame per second.
- Backend is `ai_backend` (FastAPI, in this repo): `/analysis/analyze/upload` runs the Safety Agent then the Gemba Kaizen Agent; the frontend reaches it through its own `/api/*` proxy.
- Safety rules are free-text prompts with a severity (for example "a person who is not wearing a safety helmet"); the manager edits them and re-runs.
- Activities map to Muda categories: VA (value-adding), NNVA (necessary inspection), NVA_MOTION, NVA_TRANSPORT, NVA_WAITING, NVA_SEARCH, plus NO_PERSON and UNCERTAIN.
- Reports are written in Thai, Japanese, or English (backend `language`); the interface itself is English.
- A mock mode must work with no API key: bundled demo clips with cached analysis results.

## Capabilities and Constraints

- Stack is fixed: SvelteKit 3 (runes), adapter-node, plain CSS, no heavy new dependencies. Imports use `#lib/...` with file extensions.
- The vision model reports confidence as an integer 0-100, so confidences are coarse; low-confidence moments are marked unclear and become questions for the operator.
- A live stream is not implemented in the backend: a live-video surface is a placeholder, not a working feature.
- Estimated savings come from the backend's Gemba Kaizen Engine (hours per shift, throughput), not from the LLM; rule-based cards appear when no LLM key is set and must be labelled as such.
- Undecided: real factory footage, authentication and roles, persistence of past runs across sessions, the voice agent integration.

## Brand Commitments

The product name is VALZ. The glossary of the domain is Japanese lean vocabulary (Gemba, Kaizen, Muda, takt, Yamazumi) and it should be used correctly, not decoratively.

## Evidence on Hand

- No real factory footage exists in the repo. The only local clips are an unrelated street test clip and lectures; demo content must be the user's own clips dropped into `frontend/static/demo/`, or clearly labelled synthetic material.
- Real backend responses exist only when a run has been made with an OpenRouter key; the shape is defined by `ai_backend/openapi.json`.
- Do not fabricate customers, benchmarks, or measured savings; demonstration data is acceptable only when labelled as sample/synthetic.

## Product Principles

1. Every number points back to a moment in the video; nothing is stated that the manager cannot jump to and check.
2. Be honest about confidence: unclear is a first-class state, and a rule-based or sample result never poses as an LLM or live one.
3. The manager's levers (rules, thresholds, language) sit next to the evidence they change.
4. Measured facts and model judgement are visibly different kinds of information.
5. Works end to end offline in mock mode, so a demo never depends on a key or a network.
