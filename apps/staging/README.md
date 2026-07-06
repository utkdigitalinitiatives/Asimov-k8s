# Solr staging — retired (July 6, 2026)

**This environment is intentionally empty.** It is kept as a placeholder so the
historical staging/production layout stays visible in the repo.

Solr is a **deploy-only** application on this cluster — like Redis and the
kube-prometheus-stack monitoring, it is *used*, not actively developed. A
separate staging environment added only overhead and caused a recurring
`install-solr-crds` Job conflict with production (both overlays built the same
immutable Job from `infrastructure/base` with different `environment` labels).

## What changed
- The `solr-staging` Azure Flux configuration was deleted on 2026-07-06.
- Solr now runs **production-only**: [`apps/production/solr-mainsite`](../production/solr-mainsite)
  and [`infrastructure/production`](../../infrastructure/production).
- Staging Solr pods had already been disabled on 2025-12-15.

See the repo root `CLAUDE.md` for the current architecture.
