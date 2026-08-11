# PREREGISTRATION - J4/K4 on mem0ai 2.0.17, GPT-OSS low reasoning

Frozen: 2026-08-09, before any J4/K4 provider request.

## Calibration basis

C1 was a separately preregistered single-session configuration test. It used the
same SDK, dataset, model, token ceiling, and rate limit settings as this pair, with
`reasoning_effort="low"`; it made one call, returned `stop`, and completed session 0.
J2/J3 used default medium reasoning and are preserved failed calibrations (`length`).

## Question

For the same 33-session ES-MemEval `p8` dialogue, do two fresh Mem0 2.0.17 stores
produce divergent fact dumps and frozen zero-LLM retrieval results when extraction
uses Cerebras GPT-OSS 120B at temperature 0 and low reasoning effort?

## Fixed environment

- Dataset SHA-256: `f30698e87fddaeff51270a666c654da604f487a3456ec60d2b6ae08a6fecd420`.
- Subject: `p8`, exactly 33 sessions in source order.
- Configuration: `config_j4k4.json`; fresh local Chroma stores J4 and K4; MiniLM L6 v2;
  LiteLLM/Cerebras `gpt-oss-120b`, temperature 0, max tokens 4000, reasoning low.
- Questions SHA-256: `4daba3365a270926e3ee13a2084b78755c54081af89c6de9988bff197986067d` (`audit/retrieval_questions.json`).

## Predictions

- Both clean runs complete 33/33 sessions, exactly one call per session, all `stop`.
- Fact-volume divergence is below 15 percent.
- Exact dump symdiff is 75--100 percent; cosine-0.72 symdiff is 60--90 percent.
- J4 compared with itself is zero at every comparison threshold.
- At most 2/20 frozen retrieval questions have identical top-5 results.

## Execution and failure rules

- Four complete sessions per window; calls are at least 60 seconds apart.
- Persist state after every complete session. Provider error rolls back the current
  window and emits an immutable alert with rate-limit headers.
- Any `length`, non-`stop`, call-count anomaly, or dump ceiling stops the run. It is
  retained but excluded from clean-pair comparison.
- No raw dialogue or credential is stored. Retained code and outputs receive SHA-256.

## Scope

This measures one provider/model configuration, including its low reasoning setting.
It is not a measurement of GPT-OSS medium reasoning or a general Mem0 property.
