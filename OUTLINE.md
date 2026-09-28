# Product outline

Paperless Classifier turns consumed documents into reviewable filing suggestions. The first release combines Jev's typed classification with generative title, vocabulary, and vision capabilities.

| Capability | Implemented behavior |
| --- | --- |
| Document type | One existing type, or unknown; changing the type requires approval. |
| Existing tags | Independent Jev scores for every eligible tag; additions only. |
| Subjects and new tags | Up to six subjects discovered without an existing vocabulary, supporting quotes, suggested equivalent tags, independent Jev relevance scores, and explicit review to reuse, rename, or create up to three new tags. |
| Titles | Editable factual title suggestions. |
| Images and scans | Paperless OCR first; a separate vision model reads all pages when needed. |
| Review | Current metadata, source excerpt, predictions, original document link, and explicit approval. |
| History | Proposals, approvals, before/after metadata, failures, and write journal. |
| Intake | Manual selections or an optional dedicated queue tag. |

Existing tags are preserved, including inbox/workflow markers. The model cannot choose operational tags, endpoints, tools, or write policy. New tags are normalized and matched against the live taxonomy before creation.

Subject discovery runs whenever enrichment is enabled, including documents that already match broad tags. Jev suggests synonymous existing tags after discovery; broader or narrower meanings should remain distinct. Reviewers see every discovered subject and can override the suggested match. A useful rare subject does not need multiple documents before it can become a tag. Created tags join the vocabulary used on future documents. Existing curated definitions are preserved when tags are reused.

The first release requires review for every write. The 50% tag-score preselection is a UI convenience, not a calibrated accuracy or automatic-application threshold. New tags are never preselected.

Approvals are bound to the displayed proposal revision and store the selected names and IDs. Regenerating a job invalidates older open review forms. All active jobs remain accessible; only terminal history entries are limited to the latest 200.

## Boundaries

Paperless owns originals, OCR, search, and consumption. Jev processes text only. The generative model handles title suggestions, missing vocabulary, and reading images. Vision-derived text is used for classification without replacing Paperless OCR or original files.

The app can take over title/tag/type enrichment for documents the user selects. Keep Paperless-GPT available for other functions and avoid having both applications update the same documents simultaneously. The classifier does not change the existing `needs-tags` workflow or remove its queue markers.

Not implemented: automatic approval, correspondent creation/selection, OCR write-back, searchable-PDF replacement, arbitrary field extraction, chat, retraining, or automatic undo.

## Success and evaluation

The first release is successful when a document can be classified, inspected, and applied with fewer manual steps, while preserving unrelated metadata and recording recoverable outcomes.

Model accuracy on the real archive remains unmeasured. The initial investigation covered synthetic documents. A future private calibration and held-out evaluation should measure tag precision/recall, type accuracy, review rate, latency, and provider usage, with counts and uncertainty. Sparse categories remain review-only. A target such as 98% precision is an evaluation target, not a current claim.
