# Working in this repository

Paperless Classifier is currently a planning repository. Read README.md,
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
- Run checks appropriate to changed behavior. During this documentation-only
  phase, check Markdown links, example JSON, and `git diff --check`.
- When application code is added, provide one local check entrypoint and CI
  that runs the same checks; include meaningful failure and recovery tests.
- Keep deployment automation in home-ansible and follow its canonical checkout,
  Quadlet, documentation generation, and validation conventions there.

Implement only the work authorized in the current task. Product review controls
described in the plan are application behavior, not extra approval requirements
for ordinary repository work.
