# Re-evaluate translations with a fresh Opus 4.7 judge run

**Status: v2 split layout.** Re-scoring is no longer a per-submission
operation. Under rubric v2 there is a single canonical judge
(`claude-opus-4-7-rubric-v2-poe`) and a single judgments file. To force a
fresh judgment pass, you have two options.

---

## Option A — Re-judge ONLY the entries currently missing scores

If `benchmark/data/judgments/claude-opus-4-7-rubric-v2-poe.json` already
exists but is incomplete (e.g. after adding new translations), run:

```bash
python scripts/rejudge_all_via_poe.py
```

The script defaults to `--resume`: it loads existing scores and only judges
unscored `(model_id, text_id, target_lang)` triples. Idempotent.

---

## Option B — Re-judge EVERYTHING from scratch

If you've updated the rubric, the prompt, or want a fresh pass:

```bash
python scripts/rejudge_all_via_poe.py --no-resume
```

This discards the existing judgments file and re-judges all 1000+ entries
(~$8 at current Poe Opus 4.7 rates). Confirm with the user via
`AskUserQuestion` first — this is irreversible without restoring from git.

After completion, the script prints per-model `old → new` overall deltas to
verify the calibration shift.

---

## Workflow after re-judge

1. Inspect the printed delta table for sanity.
2. `git diff benchmark/data/judgments/` to review score changes.
3. Ask via `AskUserQuestion`: "Commit and push the refreshed judgments?"
   - "Yes — commit + push" (Recommended)
   - "No — stop here"
4. If "Yes":

   ```bash
   git add benchmark/data/judgments/claude-opus-4-7-rubric-v2-poe.json
   git commit -m "rejudge(benchmark): refresh scores under rubric v2"
   git push origin main
   ```
5. Ask: "Republish the wiki?" → invoke `/benchmark-publish-wiki` if "Yes".

---

## Why this replaces the old per-submission rescore

In v1, each submission file contained both translations AND scores together.
Re-scoring meant editing each submission individually (and the file's
`judge_id`). In v2, translations and judgments are split:

- `benchmark/data/translations/<slug>.json` — outputs (immutable)
- `benchmark/data/judgments/<judge-id>.json` — all scores from one judge

So re-scoring is now a single operation against a single file. There's no
need for per-submission rescore commands.

---

## Important guardrails

- **Do NOT touch the translations files.** They are immutable artifacts;
  the rejudge script never writes to them. If you need to add new
  translations, use `python -m benchmark.cli add-translations`.
- **The judgments file IS the v2 source of truth for scores.** Manual edits
  there are allowed but discouraged — prefer regenerating via the script
  for auditability.
- **Always confirm via `AskUserQuestion`** before `--no-resume` (destroys
  prior judgments), commit + push, and wiki publish. Stop at any "No".
- **Hash mismatches reported by the rejudge script are fatal.** They mean
  the judgments file refers to outputs that no longer exist in the
  translations files (e.g. someone replaced a translation but didn't
  rejudge). Investigate before pushing.
