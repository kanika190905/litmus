# Demo video: recording script (target 4:00-4:45, limit 5:00)

## Before recording (5 min)

1. Plug the laptop in, close heavy apps, and turn off notifications (Focus assist).
2. Open a terminal (PowerShell) and run exactly:
   ```powershell
   cd "C:\Users\abhin\OneDrive\Desktop\samsung prism\litmus"
   C:\Users\abhin\.venvs\prism\Scripts\activate
   litmus serve
   ```
3. **Wait ~45 s** (it loads the model and warms the sandbox and the version views).
4. Open `http://127.0.0.1:8000` in a browser at 100% zoom, full-screen (F11).
5. Run one throw-away search first, so the query shows real steady-state timings on camera.
6. Keep a second terminal ready for the CLI part.

## Script

| Time | Show | Say (suggested narration) |
|---|---|---|
| 0:00-0:25 | Title slide of the PPT | "This is Litmus, our submission for Theme 1, Agentic Code Intelligence. Given a library of code and a natural-language query, it ranks snippets by relevance. It runs on a laptop CPU and supports retrieval across code versions." |
| 0:25-0:55 | Architecture slide | "Embeddings alone rank code by *similarity*, and a snippet with a one-character bug looks identical to the correct one. Litmus searches, then *verifies*: a CPU embedding model finds candidates, and when the query contains sample tests, which 98% of the benchmark queries do, we execute the candidates on those tests in a sandbox and use the outcome as evidence in the ranking." |
| 0:55-1:50 | Web UI: choose sample **q6018**, click **Compare: dense-only vs verified** | "This is a real query from the CoIR-apps test split. Query analysis detects a Codeforces-style task and extracts its sample tests. *(point at the examples)* Dense retrieval alone puts the ground-truth solution at rank 4. Litmus executed the top candidates: this one reproduces every expected output, *(open the result, show got vs expected)* so it moves to rank 1. Look-alikes that print the wrong answer or crash drop down. Timings: embedding the query is the main cost; dense search takes milliseconds; verifying 20 candidates takes about 20 milliseconds." |
| 1:50-2:25 | Expand a WRONG ANSWER / RUNTIME ERROR hit, then edit one word of the query and press **Search** | "Every result carries its evidence: expected versus actual output. That makes the ranking explainable. *(edit a word, search)* This is now a query the system has never seen: embedding it on this laptop CPU takes under a second for a short statement (2-3 s for a long one), and verification takes milliseconds." |
| 2:25-3:10 | Version selector: **v1 → v2 → v3 → ALL versions** with sample **q5287** (marked [evolves]) | "P1: this corpus has three versions. v2 is a regression commit: this solution got a one-token bug. Searching v2 shows the buggy version failing its tests. *(switch to v3)* v3 fixes it. *(switch to ALL)* The Bonus: search across all versions. The correct and buggy versions are near-identical in text, but only the correct ones pass, so they rank first. *(click 'history')* This is the full lineage of the snippet across versions." |
| 3:10-3:50 | Terminal: `litmus versions apps-demo` and `litmus diff apps-demo v1 v2` (below) | "Versions are git-tree-like manifests, and vectors are cached by content hash. Adding a version only embeds what changed: here only 50 of 995 snippets were re-embedded for v2, and the v3 revert re-embedded zero and re-indexed in 0.05 seconds. Any directory or git ref can be indexed the same way." |
| 3:50-4:30 | Results slide | "On a representative subset of 200 real test queries, verification raises MRR@10 from 0.962 to 0.987 and the ground truth moved up in 9 queries and down in none. On the evolution benchmark, a buggy version outranks the correct one 30% of the time with embeddings alone, and 10% with Litmus. The official full-corpus MTEB run uses the same code through MTEB's own evaluator." |
| 4:30-4:45 | Close | "Litmus: search, then verify. Thank you." |

## Commands shown in the terminal part

```bash
litmus versions apps-demo
litmus diff apps-demo v1 v2
litmus search @demo/queries/q5287.txt --store apps-demo --version all -k 5
```

## Checklist while recording

- [ ] Query analysis panel visible (kind, language, examples)
- [ ] "Compare" line shows dense rank → Litmus rank of the ground truth
- [ ] Timings strip visible (embed, dense, verify, total)
- [ ] At least one PASS and one WRONG ANSWER / ERROR result expanded
- [ ] Version switch v1 / v2 / v3 / ALL, plus the history popup
- [ ] CLI `versions` / `diff` output
- [ ] Results slide
