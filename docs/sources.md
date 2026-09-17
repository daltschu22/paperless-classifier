# Source notes

Reviewed 2026-09-17. These sources support the design; they do not establish
compatibility with a deployed Paperless version or prove classification quality.

- [TypeSafe System One](https://docs.typesafe.ai/concepts/system-one): text input,
  constrained decisions, and the limits of calibration.
- [TypeSafe primitives](https://docs.typesafe.ai/primitives): Choice, Noul, and
  independent questions sharing one state.
- [TypeSafe confidence](https://docs.typesafe.ai/confidence): interpretation of
  probabilities and the separate confidence statistic.
- [TypeSafe Python SDK](https://github.com/typesafe-ai/typesafe-sdk-python):
  official client; validate and pin a version during implementation.
- [Paperless-ngx REST API source](https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/api.md):
  authentication, pagination, metadata operations, and API version negotiation.
- [Paperless matching](https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/advanced_usage.md#matching):
  existing rules and learned matching to use as a baseline.
- [Paperless-GPT](https://github.com/icereed/paperless-gpt): inspiration for the
  companion application workflow, with broader OCR and generation scope.

The Paperless API documentation website returned HTTP 403 during research; its
upstream repository documentation was used instead. Upstream `main` can describe
features newer than the installed release. Verify the deployed API schema and
server version before integration, particularly asynchronous task behavior and
any conditional-update support.

Homelab context came from `home-ansible`'s Paperless and tag-expansion documentation.
This task did not inspect live Paperless documents, run a model evaluation, change
existing services, or establish performance/cost claims.
