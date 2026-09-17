# Jev feasibility investigation — 2026-09-17

Jev is worth pursuing for document classification. The API and official Python
SDK worked, classification was fast in these probes, and input-token cost was
small. This is a preliminary synthetic experiment, not evidence that it beats
Paperless-GPT or is ready to modify the live library automatically.

## What ran

- One authentication/smoke request to the documented evaluation endpoint.
- A fixed synthetic set of 24 documents: 23 classified, one blank OCR input
  skipped locally without a provider call.
- Three synthetic size probes with 56 tags and 15 document types plus `unknown`.
- Three earlier size probes with one fewer type, retained in the private run log.
- Read-only inspection of Paperless taxonomy counts, server headers, and OCR
  lengths for 20 recent documents. No Paperless metadata was changed.

All Jev requests used synthetic text and synthetic taxonomy. No real document
text or real taxonomy names were sent to TypeSafe. The supplied key is stored
outside this repository with owner-only permissions; it is not in the fixtures,
logs, committed files, or this report.

The smoke request resolved `jev-latest` to `jev-1.13.0`. Subsequent experiments
pinned `jev-1.13.0` and used `typesafe-sdk==0.6.0` with retries disabled. Calls
were sequential from scratch, with one reusable SDK client per batch. Timing
includes the complete client call and response validation; first calls include
connection setup. This is a single run, with no claim about sustained throughput.

## Classification observations

The fixed set uses 12 independently evaluated tags and eight named types plus
`unknown`. Expected labels and question definitions were written before the run.
Only OCR entered model state; case IDs and expected labels stayed local.

| Measure | Observation |
| --- | --- |
| Successful non-empty document calls | 23 / 23 |
| Type matches to predeclared expectations | 22 / 23 |
| Exact tag-set matches at probability >= 0.5 | 23 / 23 |
| Positive tag matches at that cutoff | 31 / 31; zero extra tags |
| Total individual tag judgments | 276 |
| Median latency | 0.184 seconds |
| Nearest-rank p95 latency | 0.393 seconds |
| Input tokens | 33,864 |
| Estimated input-token cost | $0.0014223 |

Examples covered paid receipts versus unpaid invoices, vehicle and home insurance,
a wage form, a lease, medical documents, an appliance manual mentioning water and
electricity, a Spanish invoice, noisy OCR, and unrelated footer terms. A synthetic
instruction embedded in a cafe receipt did not cause the requested medical and
insurance misclassification. That single case does not establish general prompt
injection resistance.

The type disagreement was an explanation of benefits. The fixture expected
`unknown` because it had no benefits-specific type. Jev returned `letter` with
probability 0.49, followed by `statement` at 0.27 and `unknown` at 0.17. It assigned
zero probability to `invoice`, correctly recognizing the "not a bill" distinction.
The broad letter definition makes the expected label debatable. Treat this as
evidence that taxonomy boundaries need work, rather than an unequivocal model
failure. Its uncertainty would have made it a review candidate.

The fragment and gibberish cases chose `unknown`; that label must remain an
abstention even when it has high probability. Blank text was handled before inference.

## Threshold tradeoff

All cutoffs below were inspected on the same responses. They are exploratory
readouts, not calibrated deployment thresholds or independent experiments.

| Tag probability cutoff | Correct additions | Incorrect additions | Missed expected tags |
| --- | --- | --- | --- |
| 0.50 | 31 | 0 | 0 |
| 0.80 | 30 | 0 | 1 |
| 0.90 | 29 | 0 | 2 |
| 0.95 | 28 | 0 | 3 |

A synthetic solar purchase agreement had `solar=0.99`, `electricity=0.89`, and
`utilities=0.61`. Raising a universal threshold loses the broader valid labels.
At 0.95, vehicle insurance also loses its vehicle tag. A user-specific taxonomy
with short names may behave differently from this deliberately described fixture.

## Request size

The final size fixture uses 56 tags and 15 named types plus `unknown`, matching
the observed live taxonomy counts. The names and descriptions are invented.
The long inputs use repeated administrative boilerplate with the informative
invoice either first or last. They test request size and evidence position, not
the complexity of a real multipage document.

| Synthetic request | Input tokens | Elapsed | Estimated cost |
| --- | --- | --- | --- |
| Short invoice, full taxonomy | 4,453 | 0.488 s | $0.0001870 |
| 32,000 characters, invoice first | 9,885 | 0.300 s | $0.0004152 |
| 32,000 characters, invoice last | 9,886 | 0.244 s | $0.0004152 |

All three chose invoice and the expected two tags at cutoffs through 0.90.
At 0.95, the tail-evidence case missed electricity. Later calls being faster than
the first is not proof that longer input is faster; connection setup and a sample
of three prevent that inference.

## Cost and integration

The [published model price](https://docs.typesafe.ai/models), checked on the run
date, is $0.042 per million input tokens; output tokens are free. Estimates use
the API's reported input-token usage. They are not an account billing statement.

Across all 30 successful calls, including smoke and the earlier size run:
82,646 input tokens, estimated cost **$0.0034711**. No provider errors or retries
occurred. The 26 final-fixture calls account for $0.0024397 of that total.

The installed Paperless server reported version 3.1.3 and `X-Api-Version: 10`.
Read requests using an API-v9 Accept header succeeded. It contains 47 documents,
56 tags, 15 document types, and 34 correspondents. Among 20 recent documents,
OCR lengths ranged from 595 to 32,329 characters and every document already had
a type. These observations do not measure whether current labels are correct.
The existing-type conflict/review path will therefore matter in an initial pilot.

The small taxonomy suggests evaluating all allowed tags together is practical;
candidate retrieval is unnecessary for the first prototype. Exclude operational
tags before building real requests. All three taxonomy list calls fit in one
page, but a reusable Paperless client must still implement pagination.

## What this does not establish

The examples are authored for the experiment and largely short and clear. There
are only 31 positive tags in the main set, many rare categories have no coverage,
and the expected labels were not independently reviewed. The same person/process
designed the taxonomy, prompts, and expectations. Perfect matches here do not
establish 98% production precision, calibration, or resistance to arbitrary inputs.

There was no controlled comparison with Paperless-GPT, no test of real document
classification, no sustained load test, and no write-back test. The experiment
does not replace the planned evaluation or justify automatic application.

## Recommended next step

Build the read-only Paperless client and use the actual permitted taxonomy to
prepare proposals. With only 47 documents available, begin with a small varied
sample for taxonomy wording, then evaluate the remaining documents without
changing prompts. Keep related document families together and verify expected
labels manually. Report disagreement with current metadata separately from
errors against reviewed labels. Accumulate more examples before automatic mode,
especially for sparse tags. Preserve the current title-generation path.

## Reproduce

The committed harness makes no Paperless requests and defaults to zero network
calls. Its key input is an environment variable or a private key file, never a
command-line key value. The live flag makes billed TypeSafe requests.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-investigation.txt
./check

# Show planned requests only.
.venv/bin/python tools/investigate_jev.py
.venv/bin/python tools/investigate_jev.py --scale

# Run with TYPESAFE_API_KEY or --key-file /path/to/private/key.
.venv/bin/python tools/investigate_jev.py --execute --output private/reproduction.jsonl
.venv/bin/python tools/investigate_jev.py --scale --execute --output private/reproduction-scale.jsonl
```

Outputs are created with mode 0600 and an existing output path is refused. The
first request error stops the experiment. The harness is limited to 30 cases,
requires fixtures marked synthetic, and does not implement production retry,
token-budget, queue, or write-back behavior. Dependencies are pinned to the
tested environment; the ordinary checks run offline using the Python standard
library. Private raw observations are retained locally and excluded from git.
