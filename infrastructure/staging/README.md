# Solr staging infrastructure — retired (July 6, 2026)

**This environment is intentionally empty.** It is kept as a placeholder so the
historical staging/production layout stays visible in the repo.

The staging infrastructure overlay (Solr/ZooKeeper operators, cert-manager,
Traefik) duplicated production and was the source of a recurring
`install-solr-crds` Job conflict. Solr is now **production-only**; the shared
infrastructure is managed solely by
[`infrastructure/production`](../production).

The `solr-staging` Azure Flux configuration was deleted on 2026-07-06. See the
repo root `CLAUDE.md` for the current architecture.
