# Submission checklist (Samsung PRISM GenAI Hackathon, Theme 1) - Team Code Alchemist

| Item | Status | Where |
|---|---|---|
| **Source code** | Ready | `src/litmus`, `scripts/`, `tests/` (16 tests pass) |
| **README** (reproducible setup) | Ready | `README.md` |
| **Presentation** (official template) | Ready | `presentation/Litmus_PRISM_Submission.pptx` + `.pdf` (team details from `presentation/team.json`) |
| **Demo video** (max 5 min) | Ready (48 s) | `demo/Video Project.mp4` |
| **AI disclosure** | Ready | `AI_DISCLOSURE.md` |
| **APK / SDK** | **N/A** | Python package + local web app; no mobile or SDK component |
| **Official MTEB result JSON** (screening) | Ready | `results/appsretrieval_results.json` (Litmus, NDCG@10 0.9669) and `results/appsretrieval_results_dense.json` (dense baseline, 0.9032) |
| **Tag / Release** | Create on GitHub | Release `v1.0.0` with the files listed below |
| Other: measured results | Ready | `results/` (subset, evolution, versioning, feasibility, MTEB smoke test) |

Repository: https://github.com/kanika190905/litmus

## GitHub release (Releases → Draft a new release)

* Tag: `v1.0.0` (choose "create new tag on publish"). Title: `Litmus v1.0.0 - Team Code Alchemist`
* Attach:
  1. `results/appsretrieval_results.json` (the official screening file)
  2. `results/appsretrieval_results_dense.json`
  3. `presentation/Litmus_PRISM_Submission.pdf`
  4. `litmus_demo_cache.zip` (prebuilt demo index: unzip in the repo root, then `run_demo.bat` or `litmus serve`)

## Still to confirm

* **Theme ID** on slide 1 is blank. If you have one, put it in `presentation/team.json` (`theme_id`), then run
  `python presentation/build_deck.py --out presentation/Litmus_PRISM_Submission.pptx`.
