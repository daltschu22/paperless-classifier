# Paperless Classifier

A TypeSafe-powered classification companion for Paperless-ngx.

Turn document OCR into useful metadata: choose a document type, apply existing
tags, and route ambiguous results to a review queue. The goal is the convenience
of Paperless-GPT with a focused, measurable classification workflow.

**Status: outline, implementation plan, and a working synthetic Jev investigation
harness. The Paperless application and integration are not implemented or deployed.**

## Planned experience

1. Connect Paperless-ngx and TypeSafe.
2. Select a small collection or queue tag to classify.
3. Review proposed document types and tags beside the original metadata.
4. Accept, edit, or reject suggestions.
5. Enable automatic application for categories that perform well on your documents.

Paperless supplies OCR and remains the source of truth. Jev evaluates the text
against the taxonomy already in Paperless. Local policy decides which changes
are eligible to apply and which need review. Selected OCR text is sent to the
hosted TypeSafe API; the application itself runs locally.

## Start here

- [Product outline](OUTLINE.md): scope, user experience, and success criteria.
- [Implementation plan](PLAN.md): ordered milestones and acceptance checks.
- [Architecture](docs/architecture.md): data flow, decisions, and update behavior.
- [Synthetic example](examples/classification.json): an illustrative proposal.
- [Source notes](docs/sources.md): upstream references and verification work.
- [Initial Jev investigation](docs/investigation-2026-09-17.md): measured results,
  limitations, and reproduction commands.

The next implementation milestone is a read-only Paperless CLI that classifies
a selected real document and saves a proposal. Review UI and write-back follow
that foundation. The research harness already tests synthetic classification
through the official SDK. Run `./check` for offline checks; live experiment
instructions are in the investigation report.

This is an independent project, not an official Paperless-ngx or TypeSafe product.
