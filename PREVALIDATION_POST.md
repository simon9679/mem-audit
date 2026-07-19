## Would an external consistency checker for Mem0 be useful to you?

I kept running into the ADD-only contradiction issue described in #4896 and
#4536 — my memory store ends up with pairs like "lives in Berlin" / "lives
in Madrid" both present, and nothing in Mem0 itself flags or resolves it.

I don't want to migrate to a different memory framework just for this — I'm
happy with Mem0 otherwise (cost, simplicity, backend flexibility).

So I built a small external tool that:
- reads your existing memories through the standard SDK (get_all/history) —
  doesn't touch your vector store directly, works with whatever backend
  you've got (Qdrant/pgvector/etc.)
- does a cheap embedding pass to find near-duplicate pairs, then an
  LLM-judge pass only on those candidates, to classify each as
  DUPLICATE / CONTRADICTION / UPDATE(stale) / UNRELATED
- prints a report — never modifies anything

Before I put more time into it: is this something you'd actually run, or
do you handle this a different way already (manual review, custom
scripts, or you've just moved to Zep/Letta for the built-in resolution)?

Genuinely looking for "this doesn't match how my store actually looks" /
"I already solved this with X" more than feature requests at this stage.

Happy to share the repo if there's interest.
