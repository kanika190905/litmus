# Submission checklist (Samsung PRISM GenAI Hackathon, Theme 1)

| Item | Status | Where / what remains |
|---|---|---|
| **Source code** | Ready | `src/litmus`, `scripts/`, `tests/`; `pytest -q` passes (14 tests) |
| **README** (reproducible setup) | Ready | `README.md` |
| **Presentation** (official template) | Ready, team fields to fill | `presentation/Litmus_PRISM_Submission.pptx` (+ PDF). Fill `[TO FILL]` on slide 1 (Theme ID, team, college, members, GitHub link) and the video link on slide 11 |
| **Demo video** (max 5 min) | **Team to record** | Follow `docs/DEMO_SCRIPT.md`; upload to YouTube/Drive; put the link in README + slide 11 |
| **AI disclosure** | Ready | `AI_DISCLOSURE.md` |
| **APK / SDK** | **N/A** | Python package + local web app; there is no mobile or SDK component |
| **Tag / Release** | Prepared locally | git tag `v1.0.0`. After pushing: create a GitHub Release from the tag and attach the files below |
| **MTEB result JSON** (screening) | **Pending** | Run `python scripts/run_mteb_eval.py` (~6-7 h on a laptop CPU, resumable). Attach `results/appsretrieval_results.json` to the release. Do **not** submit subset numbers as the official score |
| Other: measured results | Ready | `results/subset_eval.json`, `results/subset_rankings.csv`, `results/evolution_eval.json`, `results/versioning.json` |

## Release assets to attach (GitHub → Releases → Draft new release → tag `v1.0.0`)

1. `results/appsretrieval_results.json` (official MTEB output, once the run completes)
2. `results/appsretrieval_responses.csv` (per-query top-10, produced by the same run)
3. `presentation/Litmus_PRISM_Submission.pdf`
4. `results/subset_eval.json`, `results/evolution_eval.json`, `results/versioning.json`, `results/exec_feasibility.json`, `results/mteb_smoke_subset.json`
5. `dist/litmus_demo_cache.zip` (7.4 MB prebuilt demo index: unzip in the repo root and run `litmus serve` without waiting for embeddings)

## Push commands (after creating an empty public repo on GitHub)

```bash
git remote add origin https://github.com/<your-account>/<repo>.git
git push -u origin main
git push origin v1.0.0
```
