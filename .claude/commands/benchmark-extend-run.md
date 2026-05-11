# Extend a model with more language pairs: {{arg1}} / {{arg2}}

Take an existing model and run it on more `(text, target_lang)` pairs.
Already-translated pairs are kept; only the new combinations are translated.
The judgments file is then refreshed by the canonical re-judge (Opus 4.7 via
Poe).

**Args:**
- `{{arg1}}` = model id to extend (must exist in
  `benchmark/data/translations/<slug>.json`)
- `{{arg2}}` = target tier: `standard` or `full`

If `{{arg1}}` is missing, list available models via
`ls benchmark/data/translations/` and ask the user to pick.

If `{{arg2}}` is missing, ask — usually `full` after `standard`.

---

## Step 1 — Inspect existing translations

```bash
python -c "import json,sys; sys.stdout.reconfigure(encoding='utf-8'); d=json.load(open('benchmark/data/translations/<slug>.json',encoding='utf-8')); print('Model:', d['model']['id']); print('Provider:', d['model']['provider']); print('N translations:', len(d['translations'])); pairs=sorted({(t['text_id'], t['target_lang']) for t in d['translations']}); print('Pairs:', len(pairs))"
```

Slug = `{{arg1}}` with `:` and `/` replaced by `-` (e.g. `gemma3:27b` →
`gemma3-27b`).

If the file doesn't exist, **stop**: the model has never been benchmarked.
Use `/benchmark-test-model` instead.

---

## Step 2 — Determine the provider

The translations file stores `model.provider`. Use that. If absent or
unclear, ask the user via `AskUserQuestion`.

---

## Step 3 — Translate only the delta

```bash
python -m benchmark.cli run -p <provider> -m {{arg1}} --no-evaluate --pair-set {{arg2}}
```

The runner produces a fresh `benchmark_results/<RUN_ID>.json` with ALL pairs
for the chosen tier. The next step's merge will dedup the ones we already
have.

Sanity-check success rate. **If < 90%**, read a sample error and stop.

---

## Step 4 — Merge into translations

Ask for GitHub user if not known.

```bash
python -m benchmark.cli add-translations benchmark_results/<RUN_ID>.json \
    --by github:<user> \
    --provider <provider>
```

The command merges new entries into `benchmark/data/translations/<slug>.json`.
Output reports how many entries were newly added vs. already present.

If `Added/merged: 0`, the run added nothing new (the tier was already
covered). Stop and tell the user.

---

## Step 5 — Re-judge the new entries

Ask via `AskUserQuestion`: "Re-judge new entries with Opus 4.7 via Poe?"
- "Yes — run rejudge now" (Recommended)
- "No — skip (wiki will mark them unjudged)"

If "Yes":

```bash
python scripts/rejudge_all_via_poe.py --yes
```

The script is idempotent — it loads existing scores and only judges the new
entries. Output prints `[X/Y]` progress and a final per-model `old → new`
table.

If the script reports any failures, list them and ask whether to re-run.

---

## Step 6 — Commit and push

Ask via `AskUserQuestion`: "Commit and push?"
- "Yes — commit + push" (Recommended)
- "No — stop here"

If "Yes":

```bash
git add benchmark/data/translations/<slug>.json benchmark/data/judgments/claude-opus-4-7-rubric-v2-poe.json
git commit -m "benchmark: extend {{arg1}} to {{arg2}} tier (judge: Opus 4.7 rubric v2)"
git push origin main
```

Stage **only** these two files. If unrelated changes exist in `git status`,
warn the user.

---

## Step 7 — Publish the wiki

Ask via `AskUserQuestion`: "Republish the wiki now?"
- "Yes — run /benchmark-publish-wiki" (Recommended)
- "No — skip"

If "Yes", invoke `/benchmark-publish-wiki`.

---

## Important guardrails

- **Don't shrink the tier.** Going `full → standard` is a no-op.
- **The judge is fixed at Opus 4.7 via Poe rubric v2.** Don't introduce
  other judges in v2.
- **Always confirm via `AskUserQuestion`** before rejudge, commit + push,
  wiki publish. Stop at any "No".
- **Hash mismatches between translations and judgments are fatal.** If the
  rejudge script warns about them, stop and surface to the user.
