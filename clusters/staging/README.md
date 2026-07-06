# Staging cluster config — retired (July 6, 2026)

**This directory is intentionally empty**, kept as a placeholder so the
historical staging/production layout stays visible in the repo.

These files described a self-managed Flux layout that was not the active
mechanism — cluster reconciliation is driven by `az k8s-configuration flux`
(microsoft.flux) configurations, not by manifests under `clusters/`. The
`solr-staging` Azure Flux configuration was deleted on 2026-07-06 when Solr
moved to a production-only, deploy-only model.

See the repo root `CLAUDE.md` for the current architecture.
