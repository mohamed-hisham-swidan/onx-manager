## Summary

<!-- Briefly describe what this pull request changes and why. Link any related issue (e.g., Closes #123). -->

## Changes

- 

## Verification & Quality Gates

- [ ] `python3 scripts/check-version-propagation` passes
- [ ] `python3 scripts/check-db-revision` passes
- [ ] `python3 scripts/check-ruff-baseline` passes (no new Ruff violations)
- [ ] `python3 scripts/check-route-contract` passes (if routes or permissions changed)
- [ ] `python3 scripts/check-ps1-bom` passes (if `.ps1` scripts changed)
- [ ] `python3 scripts/check-stray-db` passes
- [ ] Backend tests pass (`cd backend && pytest -q`)
- [ ] Frontend checks pass (`cd frontend && npm run typecheck && npm run lint && npm test && npm run build`)
