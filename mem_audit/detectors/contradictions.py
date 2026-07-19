from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from mem_audit.connectors.mem0_connector import MemoryRecord
from mem_audit.detectors.base import Finding, FindingType, Severity
from mem_audit.detectors.duplicates import CandidatePair

# Classifier contract: given two memory texts, return one of these labels.
# This directly targets the failure mode documented in mem0ai/mem0#4896 and
# #4536 — near-duplicate ADD events that should have been UPDATE/DELETE but
# weren't, because Mem0's ADD-only extraction doesn't resolve them.
_LABELS = {"DUPLICATE", "CONTRADICTION", "UPDATE", "UNRELATED"}

_JUDGE_PROMPT = """You are auditing an AI agent's long-term memory store for consistency.
You will see two memory entries about the same user. Classify their relationship.

Memory A (older): "{text_a}"
Memory B (newer): "{text_b}"

Respond with strict JSON only, no other text:
{{
  "label": "DUPLICATE" | "CONTRADICTION" | "UPDATE" | "UNRELATED",
  "rationale": "<one short sentence>"
}}

Label meanings:
- DUPLICATE: both say the same thing, no new information in B.
- CONTRADICTION: A and B cannot both be true at the same time (e.g. two different
  cities as "current home"), and it's not a case of B simply superseding A over time.
- UPDATE: B is a natural evolution of A (e.g. changed job, moved city) — this is
  expected drift, not a bug, but worth surfacing so a human can confirm A should
  be retired.
- UNRELATED: the embedding similarity was a false positive; A and B are not
  actually about the same fact.
"""


@dataclass
class JudgeResult:
    label: str
    rationale: str


LLMCallFn = Callable[[str], str]  # prompt -> raw text completion


def default_llm_judge(client=None, model: str = "gpt-4o-mini") -> LLMCallFn:
    """OpenAI-compatible default judge. Swap with any callable(prompt) -> str."""
    if client is None:
        import openai

        client = openai.OpenAI()

    def call(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        return resp.choices[0].message.content or ""

    return call


def cerebras_llm_judge(model: str = "gpt-oss-120b", api_key: str | None = None) -> LLMCallFn:
    """
    Judge backed by Cerebras' free OpenAI-compatible endpoint (1M tokens/day
    free tier, no card). Good fit for this step specifically: judging is the
    call made once *per candidate pair*, so it's the volume driver in the
    pipeline — worth routing to the generous free tier rather than a
    rate-limited one.

    Cerebras' free-tier model catalog has changed more than once in 2026
    (reports as recent as May 2026 show it narrowed to just two models at
    one point) — don't trust this default blindly. Check your account's
    available models (client.models.list() or the Cerebras dashboard)
    before relying on `model` staying valid.

    api_key defaults to the CEREBRAS_API_KEY env var if not passed explicitly.
    """
    import os

    import openai

    resolved_key = api_key or os.environ.get("CEREBRAS_API_KEY")
    if not resolved_key:
        raise ValueError(
            "cerebras_llm_judge requires an API key — pass api_key= "
            "explicitly or set the CEREBRAS_API_KEY env var."
        )

    client = openai.OpenAI(base_url="https://api.cerebras.ai/v1", api_key=resolved_key)

    def call(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        return resp.choices[0].message.content or ""

    return call


def judge_pair(record_a: MemoryRecord, record_b: MemoryRecord, llm_call: LLMCallFn) -> JudgeResult:
    # Order by created_at when available so "older"/"newer" in the prompt is
    # meaningful; contradiction vs. update hinges on temporal order.
    a, b = record_a, record_b
    if a.created_at and b.created_at and a.created_at > b.created_at:
        a, b = b, a

    prompt = _JUDGE_PROMPT.format(text_a=a.text, text_b=b.text)
    raw = llm_call(prompt)
    parsed = _safe_parse(raw)
    return JudgeResult(label=parsed.get("label", "UNRELATED"), rationale=parsed.get("rationale", ""))


def find_contradictions(
    candidate_pairs: list["CandidatePair"],
    llm_call: LLMCallFn,
) -> list[Finding]:
    """
    Takes candidate pairs from duplicates.find_duplicate_candidates and
    classifies each with an LLM judge.

    Only DUPLICATE, CONTRADICTION and UPDATE labels produce Findings.
    UNRELATED means the cheap embedding pass produced a false positive —
    no Finding, full stop. (Earlier versions of this pipeline kept the
    embedding-pass Finding around regardless of what the judge said, which
    meant a pair the judge explicitly called UNRELATED could still show up
    in the report as a duplicate. Fixed by making the judge the only
    source of Findings for candidate pairs.)
    """
    findings: list[Finding] = []
    for pair in candidate_pairs:
        a, b = pair.record_a, pair.record_b
        result = judge_pair(a, b, llm_call)

        if result.label == "DUPLICATE":
            findings.append(
                Finding(
                    type=FindingType.DUPLICATE,
                    severity=Severity.LOW,
                    memory_ids=[a.id, b.id],
                    summary=f'Duplicate: "{a.text[:60]}" ~ "{b.text[:60]}"',
                    detail=result.rationale,
                    suggested_action="Same fact stored twice — safe to merge.",
                )
            )
        elif result.label == "CONTRADICTION":
            findings.append(
                Finding(
                    type=FindingType.CONTRADICTION,
                    severity=Severity.HIGH,
                    memory_ids=[a.id, b.id],
                    summary=f'Contradiction: "{a.text[:60]}" vs "{b.text[:60]}"',
                    detail=result.rationale,
                    suggested_action=(
                        "These cannot both be true. Confirm which is current and "
                        "delete/update the other — Mem0's ADD-only mode will not "
                        "do this for you (see mem0ai/mem0#4896, #4536)."
                    ),
                )
            )
        elif result.label == "UPDATE":
            findings.append(
                Finding(
                    type=FindingType.STALE,
                    severity=Severity.MEDIUM,
                    memory_ids=[a.id, b.id],
                    summary=f'Likely superseded: "{a.text[:60]}" -> "{b.text[:60]}"',
                    detail=result.rationale,
                    suggested_action="Consider retiring the older memory to avoid stale retrieval.",
                )
            )
    return findings


def _safe_parse(raw: str) -> dict:
    """LLM output is untrusted formatting-wise (not security-wise) — be defensive."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"label": "UNRELATED", "rationale": f"unparseable judge output: {raw[:100]}"}
    if data.get("label") not in _LABELS:
        data["label"] = "UNRELATED"
    return data
