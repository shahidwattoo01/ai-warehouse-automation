# Contributing

## Workflow

- `main` is protected. Work on short-lived branches: `feat/<area>-<topic>`, `fix/<area>-<topic>`, `docs/<topic>`.
- Pull requests are small, reviewed by one teammate, and must pass CI.
- Commit messages follow Conventional Commits: `feat(sim): add reservation table`.
- Rotate the driver on each task; everyone must be able to explain every part.

## Definition of done for a change

- [ ] Tests added or updated; `make test` passes
- [ ] `make lint` and `make typecheck` pass
- [ ] Contracts regenerated if a message changed (`make contracts`)
- [ ] Docs, model card or data card updated if behavior changed
- [ ] A decision record added in `docs/decisions` if the change is architectural

## Rules that protect the project

1. The simulator core stays free of AI code; AI plugs in through the policy interface.
2. Agents and the Copilot never write state directly; they use validated tools.
3. All randomness comes from the seeded streams in `common/seeds.py`.
4. Splits are made by seed and scenario, never by random row or frame.
5. Constants (thresholds, speeds, limits) live in `configs/`, never in code.
