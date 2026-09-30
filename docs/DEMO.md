# Demo walkthrough

The web demo runs locally on CPU. Setup takes about 15-20 minutes once (see README,
section 3). The prebuilt demo index `litmus_demo_cache.zip` from the release avoids the
initial indexing wait.

## Start

* **Windows:** double-click `run_demo.bat`. The browser opens `http://127.0.0.1:8000` after
  about 45 seconds, once the model has loaded.
* **Any OS:** `litmus serve`, then open `http://127.0.0.1:8000`.

The demo store `apps-demo` contains 1,000 real CoIR-apps snippets in three versions:

| version | change |
|---|---|
| v1 | original snippets |
| v2 | a regression commit: 10 solutions get a one-token bug, 40 are refactored, 5 deleted |
| v3 | a fix commit: 8 of the bugs are reverted |

## 1. Execution-verified retrieval (P0)

1. **Sample query → `q6018`**, **Version → v1**, click **Compare: dense-only vs verified**.
2. The query analysis panel shows the category (`task_with_examples`), the language and
   the 4 sample tests extracted from the statement.
3. The summary line reads *"Ground-truth solution d6018: dense-only rank 4 → Litmus rank 1"*.
   Dense retrieval ranks a different problem's solution first. Litmus executed the top
   candidates, and only d6018 reproduces all 4 expected outputs (**PASS 4/4**).
4. Expand any result to see its code and, per example, the actual vs. expected output.
   Look-alikes are marked **WRONG ANSWER** or **RUNTIME ERROR**.
5. The timing strip shows each stage. Dense search takes under a millisecond and verifying
   20 candidates takes ~20 ms. Embedding a new query takes ~1-3 s on a laptop CPU.

## 2. Retrieval across versions (P1)

1. **Sample query → `q5287 [evolves]`**. Switch **Version** between **v1**, **v2** and **v3**.
2. In **v2** this solution has a one-token regression (`n // 2` → `n // 3`), so it fails its
   sample tests. In **v3** it is reverted and passes again.
3. `litmus versions apps-demo` and `litmus diff apps-demo v1 v2` show the manifests.
   A new version embeds only the changed snippets.

## 3. Retrieval across all versions (Bonus)

1. Same query, **Version → ALL versions (evolutionary)**, click **Search**.
2. The correct content (identical in v1 and v3, one item) ranks **#1 with PASS 3/3**. The v2
   regression, textually almost identical, drops to #4 with **WRONG ANSWER**.
3. Click **history** on a result to see the snippet's lineage: v1 → v2 (changed) → v3
   (reverted to v1).

## 4. Your own query

Paste any programming task with sample Input/Output. Statements copied from the Codeforces
or AtCoder websites are recognised too. If none of the library's snippets reproduces the
examples, the demo says so instead of presenting the closest look-alike as a solution.
Plain questions without examples are ranked by semantic similarity.

## Command line

```bash
litmus search @demo/queries/q6018.txt --store apps-demo --version v1 -k 5 --code 8
litmus search @demo/queries/q5287.txt --store apps-demo --version all -k 5
litmus search @demo/queries/custom_digit_sum.txt --store apps-demo -k 3
```
