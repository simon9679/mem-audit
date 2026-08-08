# PREREG — H↔I reproducibility (registered before the numbers)

*Registered while run I is still in progress and H↔I has NOT been computed. Frozen;
never edited. The prediction and the reading of each outcome are fixed here so
neither can be adjusted post-hoc.*

## The pair

H and I: two runs of the same 33-session p8 dialogue, **identical config** —
Mem0 1.0.11, chroma local, HuggingFace all-MiniLM-L6-v2 embedder, litellm →
Cerebras gpt-oss-120b, temperature 0, **max_tokens 6000 both**, plain
json_object. Both complete all 33 sessions with **zero truncation and zero
swallowed update-429** (the resumable engine refuses to checkpoint a degraded
session, so completion means every session made both LLM calls). This is the
clean reproducibility pair the whole exercise was for.

## Registered prediction (before numbers)

- **Volume divergence |H| vs |I|: < 15 %.**
- **Symdiff at `exact`: 25–50 %.**
- i.e. expect **tight convergence in volume, notable divergence in composition.**

If wrong in either direction, it is recorded as wrong, unedited.

## How each outcome is read (fixed now, no post-hoc spin)

- **Large H↔I divergence** (volume and/or symdiff high): the headline result of
  the whole audit, **stronger than the truncation finding.** Two complete runs,
  identical config, temp 0, zero truncation, zero swallowed failures — yet
  different memory. Then the instability is **not reducible to any engineering
  defect we found; it is in the extraction itself.** This is exactly what the
  work set out to find and has not yet seen cleanly.
- **Tight H↔I convergence:** the equally strong opposite result. After truncation
  is removed, **Mem0 is reproducible**, and all previously observed instability is
  explained by the engineering defects (truncation, swallowed-429), not by the
  nature of LLM extraction. **Good news for Mem0, to be reported as such — no
  forcing a problem where the data shows none.**

Both outcomes are publishable; neither is the "hoped-for" one.

## Caveat carried forward (the F/H gap)

The F(16000, 134 facts)/H(6000, 189 facts) volume gap (~40 %, of which only ~20 %
is F's two tail extraction-429 sessions; ~80 % is spread across sessions both ran
cleanly) is **not** silent loss — F had zero swallowed update-429 (verified from
its call_log: every session 0–30 made both calls). Its cause **remains
unestablished.** `max_tokens` is the only *known* difference between F and H, but
**not a proven cause** — F and H also differ in launch time, provider-queue
state, and two tail sessions, and no 16000/16000 pair exists to isolate the cap.
A tight H↔I result would show 6000 runs are volume-stable; it would **not** prove
max_tokens caused the F/H gap. State it exactly that weakly.
