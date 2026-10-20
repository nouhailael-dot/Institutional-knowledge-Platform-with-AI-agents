# Pre-flight checklist

- [ ] Fresh full Supabase backup taken today, downloaded, SHA-256 recorded, and
      restored into a scratch database with matching row counts.
- [ ] `python -m scripts.architecture_v2_release plan` passes (all 43 checksums).
- [ ] Checkout is clean; `git ls-files --eol '*.sql'` shows `w/lf` for every release file.
- [ ] Owner approval file names this host and `sha256(release_manifest.json)`.
- [ ] Owner credentials are the dedicated schema-owner role, not an application role.
- [ ] Both application releases are built and ready to deploy (step 8).
- [ ] A change window is agreed with GHUS; writers (discovery, enrichment, map
      exports) are paused during each `apply`.
- [ ] Local rehearsal re-run on the latest commit is green
      (`python -m scripts.phase12_cutover_rehearsal`).
- [ ] Production row counts are compared with the 28 Sep dump; any new actors
      without a mappable legacy category are expected to appear as extra
      `category_doubt` reviews (484 targets only the 214 known ones).
- [ ] pgvector is present on the target (it is on Supabase; `search_doc` rebuild needs it).
