# Project reports

| File | What it is |
| --- | --- |
| `Project_Progress_Report.pdf` | **Main report.** Progress of every phase and a technical comparison of the warehouse after each phase (Baseline → Layer 3 → Layer 4 → …) |
| `phases.yaml` | Phase register the report is built from: status, what was added, how it was measured, result, KPI experiment |
| `archive/Project_Progress_Report_phaseN.pdf` | Frozen copy of the report at the end of phase N |

## Report contents

1. Project progress: phase table and the warehouse KPIs after each completed phase
2. Executive summary (Layers 4 and 5 headline results)
3. Layers compared, glossary of technical terms
4. Simulation setup and unit conversion (ticks → seconds, metres, orders per robot)
5. Layer 3: Classical ML test metrics
6. Layer 4: all optimisation experiments (mean ± std)
7. Paired comparison with the baseline
8. Head-to-head: Baseline vs Layer 3 vs Layer 4
9. Results per simulated day
10. Charts
11. Layer 5: deep learning (faults, demand) and the object detector, with the Vision page
12. Layer 6: operator commands (rules, TF-IDF, DistilBERT) and the Copilot
13. Layer 7: the knowledge assistant (RAG) and the Knowledge page
14. Interpretation
15. Validity and limitations
16. Professional-readiness backlog: every gap to professional warehouse software, with the phase that closes it (`professional_backlog.yaml`)

## Updating at the end of a phase

1. Edit `phases.yaml`: set the phase `status: done` and fill in `added`, `measured`, `result`, `docs`.
   If the phase changes decisions, set `experiment` to the experiment ID that represents the warehouse after it
   (and `kpi_effect: decisions`); if it only predicts or explains, keep the previous experiment (`kpi_effect: advisory`).
2. If the phase produced new results (models, experiments), add its section to `scripts/build_project_report.py`.
3. Rebuild and archive:

```bash
python scripts/build_project_report.py --snapshot
```

The report reads only generated results (`models/*_report.json`, `evaluation/reports/phase4/`, `configs/experiments/`),
so it can be rebuilt at any time and always matches the code.
