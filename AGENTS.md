# Working in this repository

Paperless Classifier contains the hybrid review application and a synthetic API research harness. Read README.md,
OUTLINE.md, PLAN.md, and docs/architecture.md before implementation. Keep completed
features distinct from planned behavior, and update milestone status with evidence.

- Keep changes focused on the requested milestone.
- Preserve the boundary between classification proposals and Paperless writes.
- Use existing taxonomy IDs; tags are independent classifications, not one choice.
- Keep provider probability, provider confidence, and measured accuracy distinct.
- Store only synthetic fixtures in git. Never commit credentials, documents,
  OCR exports, local databases, or private evaluation results.
- Exercise external services through mocks in ordinary tests. Integration runs
  should identify their dataset and any permitted writes explicitly.
- Review tracked and untracked changes and check for secrets before committing.
- Run `./check` before committing; it also runs in CI without network access.
  Check local Markdown links when changing documentation. Extend the shared
  entrypoint with meaningful failure and recovery tests as application code lands.
- Live experiments require the harness's explicit `--execute` flag and a private
  output path. Preserve model, dataset, usage, and run provenance in reports.
- Keep deployment automation in home-ansible and follow its canonical checkout,
  Quadlet, documentation generation, and validation conventions there.

Implement only the work authorized in the current task. Product review controls
described in the plan are application behavior, not extra approval requirements
for ordinary repository work.
