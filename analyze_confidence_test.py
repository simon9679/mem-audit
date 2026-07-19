"""
Compares confidence_report.json against the known ground truth from
confidence_test_seed.py and prints real precision/recall numbers.

Run: python analyze_confidence_test.py
"""
import json

with open("confidence_report.json", "r", encoding="utf-8") as f:
    findings = json.load(f)

print(f"\nTotal findings in report: {len(findings)}\n")
for f in findings:
    print(f"  [{f['severity']:>6}] {f['type']:>13} — {f['summary']}")

print("\n" + "=" * 70)
print("GROUND TRUTH CHECK — read the summaries above and answer honestly:")
print("=" * 70)
print("""
Expected to be caught (5 pairs total):
  [ ] dup1: "vegetarian for five years" <-> "haven't eaten meat... five years"
  [ ] dup2: "commute takes almost an hour" <-> "getting to office... close to an hour"
  [ ] dup3: "degree in mechanical engineering" (both)
  [ ] contra1: "allergic to peanuts" <-> "peanuts... favorite snacks"
  [ ] contra2: "don't have any pets" <-> "my dog needs to go to the vet"
  [ ] upd1: "currently single" <-> "girlfriend and I just moved in together"
  [ ] upd2: "barista at a local cafe" <-> "new job as a data analyst"

Expected to NOT appear anywhere in the report (false positive if they do):
  [ ] nearmiss: "hiking in the mountains" / "training for a half-marathon"
      (related topic, genuinely different facts — should NOT be flagged)
  [ ] any of the 8 "noise" facts (season, violin, book, postcards, bread,
      volunteering, Japanese, sci-fi movies)

Manually check each box against the findings printed above, then compute:
  precision = (true positives) / (true positives + false positives)
  recall    = (true positives) / (true positives + false negatives)

Paste the finding list back into the chat and the analysis will be done
against these ground-truth pairs directly — this printout is a checklist,
not an automated scorer, since it needs a human (or the assistant) to match
paraphrased summaries to the ground-truth pairs by meaning, not exact string.
""")
