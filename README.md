# Paperless Classifier

A TypeSafe-powered classification companion for Paperless-ngx.

Turn document OCR into useful metadata: choose a document type, apply existing
tags, and route ambiguous results to a review queue. The goal is the convenience
of Paperless-GPT with a focused, measurable classification workflow.

**Status: project outline and implementation plan. No application is implemented
or deployed yet.**

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

The first implementation milestone is a read-only CLI that classifies a selected
document and saves a proposal. Review UI and write-back follow that foundation.

This is an independent project, not an official Paperless-ngx or TypeSafe product.
