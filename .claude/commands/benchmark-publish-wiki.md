# Republish the v2 wiki from translations + judgments (split layout)

Aggregate the v2 split layout (`benchmark/data/translations/` joined with
`benchmark/data/judgments/<active-judge>.json`), regenerate the wiki locally,
and push it to the wiki repo. Use this after a re-judge run or after adding
new translations on `main`.

**No args.**

The skill is **idempotent**: re-running with no new data just confirms
"no changes" and exits cleanly.

---

## Step 1 — Sanity check the working tree

Run via Bash from the repo root:

```
git branch --show-current && git status -s | head -20
```

If on a feature branch, ask the user whether to switch to `main` first
(`AskUserQuestion`). The wiki should reflect what's on `main`.

If there are uncommitted files in `benchmark/data/translations/` or
`benchmark/data/judgments/`, list them and ask the user whether to commit them
now or proceed with what's on remote.

---

## Step 2 — Identify the active judge

```
ls benchmark/data/judgments/
```

If exactly one judgment file → that's the active judge.
If more than one, ask the user via `AskUserQuestion` which one to publish
(typically `claude-opus-4-7-rubric-v2-poe.json`). Pass the chosen
`<judge-id>` (filename without `.json`) to the next steps.

If zero, **stop**: nothing to publish. Tell the user to run
`scripts/rejudge_all_via_poe.py` first.

---

## Step 3 — Aggregate (join translations + judgments)

```
python -m benchmark.cli aggregate \
    --judge-id <judge-id> \
    --run-id aggregated \
    --output benchmark_results/aggregated.json
```

Capture the printed stats from the aggregator:
- `translation files: T`
- `translations:      N`
- `judgment files:    J`
- `scores:            S`
- `matched:           M`
- `unjudged:          U`
- (any `HASH MISMATCHES` or `orphan scores`)

If `HASH MISMATCHES > 0`, **stop**. There's an integrity error between
translations and judgments — surface the issue and don't publish.

If `unjudged > 0`, warn the user: some translations have no score under the
active judge. Offer to run the re-judge to fill the gap before continuing.

---

## Step 4 — Generate the wiki locally (clean dir)

```
rm -rf wiki/ && python -m benchmark.cli wiki aggregated
```

The fresh `rm -rf` is important — leftover files from earlier runs (e.g.
languages tested but no longer in translations) would otherwise survive and
publish stale pages.

Confirm the output:

```
ls wiki/
```

Expected: `Home.md`, `All-Languages.md`, `All-Models.md`, plus one
`Language-<name>.md` per target language and one `Model-<id-slug>.md` per
benchmarked model.

---

## Step 5 — Clone wiki + sync content

Derive the wiki URL from the current repo's `origin`:

```
WIKI_URL=$(git remote get-url origin | sed 's/\.git$//').wiki.git
rm -rf .wiki_repo_archive && git clone "$WIKI_URL" .wiki_repo_archive
```

(On Windows / PowerShell, run the two commands manually.)

If the clone fails ("repository not found"), inform the user that the wiki
needs at least one page created via the GitHub UI before automated tools can
clone it.

Once cloned, sync v2 content while preserving archive pages:

```
cd .wiki_repo_archive && \
  find . -maxdepth 1 -name 'Language-*.md' ! -name 'Archive-*' -delete && \
  find . -maxdepth 1 -name 'Model-*.md'    ! -name 'Archive-*' -delete && \
  rm -f Home.md All-Languages.md All-Models.md && \
  cp ../wiki/*.md .
```

The `! -name 'Archive-*'` exclusion preserves the v1 archive at
`Archive-Home.md`, `Archive-Language-*.md`, etc.

---

## Step 6 — Commit and push

```
cd .wiki_repo_archive && git add -A && git status --porcelain
```

If empty → wiki is already up to date. Tell the user "no changes" and skip.

Otherwise:

```
git commit -m "Publish v2 benchmark wiki: <N> models, <Q> languages (judge: <judge-id>)" && git push
```

Replace `<N>`, `<Q>` from Step 3's stats and `<judge-id>` with the active
judge.

If push fails: 403 → auth issue (configure credential helper); non-fast-forward
→ someone else pushed, redo from Step 5.

---

## Step 7 — Cleanup

```
rm -rf wiki/ benchmark_results/aggregated.json
```

Don't `rm -rf .wiki_repo_archive` — Windows often refuses while the shell
still references it. Leave it; it's gitignored.

---

## Step 8 — Report

Tell the user:

- The number of models and languages now live on the wiki.
- The active `judge-id` used.
- Whether `unjudged > 0` (some translations not in the judgment file).
- The wiki URL (derive from origin: `<origin-url-without-.git>/wiki`).

---

## Important guardrails

- **Never delete `Archive-*` files.** The v1 archive is kept indefinitely.
- **Never push without `git status --porcelain`** confirming changes.
- **Never run from a feature branch** unless explicitly authorized.
- **Hash mismatches are fatal.** If the aggregator reports any, stop and ask.
