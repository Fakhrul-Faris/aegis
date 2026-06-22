# Research

Offline analysis that is NOT part of the running bot: pairs screening runs,
backtest reports, Monte Carlo calibration, scanner-log studies.

## Layout

```
research/
├── crypto/     M4 soak, Strategy A/B backtest verdicts
├── forex/      FX1–FX8 hypothesis sweeps, H11b/c, SCM pivots
├── goals/      research goal registry
├── runs/       run manifests
└── skills/     agent skill notes
```

## Conventions

- Anything in `scratch/` is gitignored — promote results deliberately.
- Every study that informs a config value gets a dated markdown note so
  future-you knows where the number came from.
- Verdict files (`*-verdict.md`) are the gate inputs referenced from
  [`docs/Aegis Tasks & Milestones.md`](../docs/Aegis%20Tasks%20%26%20Milestones.md)
  and the forex/intraday milestone docs.
