# Benchmark a model end-to-end: {{arg1}} / {{arg2}} [{{arg3}}]

Run the full TBL benchmark v2 on a single model: produce translations, add
them to the split-layout `translations/`, then re-judge with Opus 4.7 via Poe.

**Args:**
- `{{arg1}}` = provider (`ollama`, `poe`, `openrouter`, or `openai`)
- `{{arg2}}` = model id (e.g. `gemma3:27b`, `claude-haiku-4.5`)
- `{{arg3}}` = (optional) pair set: `quick` (8 pairs, default), `standard`
  (16 pairs), or `full` (28 pairs). See `benchmark/canonical_pairs.py`.

If `{{arg1}}` or `{{arg2}}` is missing/invalid, ask the user via
`AskUserQuestion` before running. If `{{arg3}}` is missing, default to
`quick`. If `{{arg3}}` is provided but isn't one of `quick|standard|full`,
ask the user to pick.

Volume / time:
- `quick`    → ~45 translations, judge call cost ~$0.35
- `standard` → ~125 translations, ~$0.95
- `full`     → ~245 translations, ~$1.75

---

## Step 1 — Pre-flight: validate the model id

```bash
python -m benchmark.cli models -p {{arg1}} --check {{arg2}}
```

Three outcomes:

1. **Exit 0** → proceed to Step 2.
2. **Exit 1 "NOT FOUND"** → close matches printed. Use `AskUserQuestion` to
   let the user pick from the top 3 (mark the first as Recommended). Treat
   the picked id as the new `{{arg2}}`.
3. **Exit 1 "could not fetch model list"** → missing API key or network.
   Report exact reason and stop.

---

## Step 2 — Produce translations only

```bash
python -m benchmark.cli run -p {{arg1}} -m {{arg2}} --no-evaluate --pair-set <quick|standard|full>
```

Wait for completion. Extract `<RUN_ID>` from the `Results saved to:` line.

Sanity-check success rate via the run summary. **If < 90% success**, read a
sample error from `benchmark_results/<RUN_ID>.json` before continuing.
Common causes: HTTP 401/402 (API key), HTTP 404 (bad model id — re-run
Step 1 with the exact id from the error). If the run fails to start, report
and stop.

---

## Step 3 — Add translations to the split layout

Ask via `AskUserQuestion` for the GitHub user if not already known
(header "GitHub user", required).

Then:

```bash
python -m benchmark.cli add-translations benchmark_results/<RUN_ID>.json \
    --by github:<user> \
    --provider {{arg1}}
```

This writes/merges into `benchmark/data/translations/<model-slug>.json`. The
output lists how many entries were added and the total count after merge.

If the command fails (no usable results, schema invalid), report exact error
and **stop**.

---

## Step 4 — Re-judge the affected model

The judgments file at `benchmark/data/judgments/claude-opus-4-7-rubric-v2-poe.json`
now lacks scores for the new translations. The re-judge script is idempotent
and only touches unscored entries.

Ask via `AskUserQuestion`: "Re-judge new translations with Opus 4.7 via Poe?"
- "Yes — run rejudge now" (Recommended)
- "No — skip (wiki will mark them unjudged)"

If "Yes":

```bash
python scripts/rejudge_all_via_poe.py --yes
```

The script:
- Loads existing scores from the judgment file (`--resume` default)
- Calls Poe Opus 4.7 only on the new entries
- Writes updated judgments to the same file
- Prints per-model `old → new` overall delta

If the script reports failures, list them to the user and ask whether to
re-run (the script is idempotent and will retry only the failures).

---

## Step 5 — Commit and push

Ask via `AskUserQuestion`: "Commit and push the new translations + judgments?"
- "Yes — commit + push" (Recommended)
- "No — stop here"

If "Yes":

```bash
git add benchmark/data/translations/<slug>.json benchmark/data/judgments/claude-opus-4-7-rubric-v2-poe.json
git commit -m "benchmark: add {{arg2}} via {{arg1}}, judged by Opus 4.7 rubric v2"
git push origin main
```

Stage **only** the two files — never `git add -A`. If `git status` shows
unrelated changes, warn the user and ask whether to include them.

---

## Step 6 — Publish the wiki

Ask via `AskUserQuestion`: "Republish the wiki now?"
- "Yes — run /benchmark-publish-wiki" (Recommended)
- "No — skip"

If "Yes", invoke `/benchmark-publish-wiki`. It joins translations + judgments
and pushes the wiki.

---

## Important guardrails

- **Canonical pair sets are fixed.** Don't substitute. Tier comparability
  depends on the set (`quick`/`standard`/`full`) staying intact.
- **Active judge is Opus 4.7 via Poe.** Don't introduce other judges — v2 is
  single-judge.
- **Always confirm via `AskUserQuestion`** before each user-visible action:
  rejudge, commit + push, wiki publish. Stop at any "No" answer.
- **Hash mismatches between translations and judgments are fatal.** The
  rejudge script validates hashes; if it warns about mismatches, stop and
  surface to the user.
- **The submit→rerank dance is gone.** Rubric v2 has no §5 dispersion rule;
  scores are absolute. The old `scripts/dump_for_rerank.py` and
  `apply_rerank.py` are obsolete in v2.
