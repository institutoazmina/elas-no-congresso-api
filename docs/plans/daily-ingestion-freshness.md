# Plan: daily freshness, selective AI, and database-only newsletters

Status: accepted; implementation follows ADR-002. This document records the design;
see [operation instructions](../newsletters.md#operação-da-ingestão-eficiente) for
implemented limits, bootstrap, freshness gates, and recovery. The initial full
baseline and validation against the real sources remain operational rollout checks.

## Outcome

Daily ingestion owns freshness of every tracked proposition, including older,
unapproved, unassessed, inactive, and newly closed propositions. Newsletter
generation reads dated activity already stored in PostgreSQL, categorizes it
with deterministic rules, and creates an unpublished draft. It does not start
ingestion, download documents, run OCR, or run AI.

AI runs when a proposition is newly discovered or its substantive text changes.
A status, committee, rapporteur, deadline, author metadata, or approval change
does not by itself trigger classification. Retries of an already requested
analysis are allowed; model upgrades and historical backfills are explicit
maintenance operations.

Daily freshness means coverage of changes exposed by the official sources,
verified through completed collection windows and outstanding failures. An API
outage or an unpublished source correction cannot be converted into a successful
freshness marker. Start with a daily coverage target of 08:00 America/Sao_Paulo,
measuring source completion independently from document extraction and AI.

## Findings from the existing implementation

- Câmara already queries `/proposicoes` with `dataInicio` and `dataFim`. These
  select a tramitação window containing presented **and changed** propositions,
  not just newly presented proposals. Its `/tramitacoes` endpoint also supports
  date filters. See the [official Câmara specification](https://dadosabertos.camara.leg.br/api/v2/api-docs).
- Senado currently uses deprecated `/materia/tramitando`. The replacement
  `/processo?numdias=N` lists recently updated processes, with a maximum of 30
  days. Without an active-only filter it can include closed processes. An
  October 6 read-only probe with `numdias=2&v=1` returned 136 processes, including
  64 closed and 72 active. Preserve legacy `codigoMateria` identities while
  recording the process ID. See the [official Senado specification](https://legis.senado.leg.br/dadosabertos/v3/api-docs).
- Both ingestion tasks enqueue `classify_proposition` after every upsert.
- Classification stores `input_hash` but does not use it to skip duplicate
  inference. It downloads a PDF only if `full_text` is absent, so a changed URL
  can leave old stored text in use.
- The separate 06:30 status refresh only follows human-assessed propositions.
  The newsletter full refresh repeats much of daily ingestion's HTTP and DB work.
- Event persistence repeatedly queries and upserts every historical event;
  authors are deleted and rebuilt on every normal ingestion.
- Current `IngestionRun` records discovery counts, but not complete refresh
  coverage, per-item pending work, or document/AI freshness separately.

## Required behavior

| Detected change | Database work | Document work | AI |
| --- | --- | --- | --- |
| New relevant proposition | Store identity, metadata and dated history | Extract available principal text | Once for its content version |
| Status, commission, rapporteur, vote or enactment | Store actual changes and new/corrected events | None unless there is independent document-change evidence | None |
| New or revised principal text | Store document identity and version | Download/extract changed content | Once if normalized text differs |
| New URL or changed PDF bytes with identical extracted content | Update provenance/validators | Verify content as needed | None |
| Duplicate daily result or overlapping collection window | Advance checked coverage; avoid unchanged writes | Reuse known content | None |
| Pending/failed document or AI request | Retry only that pending version | Retry extraction if necessary | Retry original request, not a new status-triggered request |

When full text is unavailable, a new proposition may initially be analyzed from
its ementa. If inteiro teor arrives later, that is a new content version. A
changed ementa is content change only when it is the content currently used for
analysis. Author/party metadata changes do not independently trigger AI, even
though those fields form part of the existing model input.

Document policy confirmed by the user: include identifiable substantive
replacement texts such as substitutivos and amended main texts as new analysis
versions, while excluding reports, procedural documents, and attachments without
substantive replacement text. Keep the original text and the candidate
replacement distinguishable; do not silently overwrite the original, treat a
submitted amendment as an adopted text, or concatenate every attachment into
model input. Select by official document identity/type and its relationship to
the principal proposal. A report referencing an independently identified
replacement text does not make the whole report eligible for AI. Ambiguous
documents remain visible for review without automatically replacing model input.

## Implementation sequence

### 1. Establish coverage and persist collection progress

Extend run auditing with a run kind, processed/skipped/failed counts and per-item
failures. Add durable checkpoints for each house and collection stream, with the
last fully covered window, execution start/end and reconciliation coverage.
Track when each proposition's source status and principal document were checked;
do not use generic `updated_at` as source freshness or legislative activity.

Resume from the last successful checkpoint with an initial 48-hour overlap.
Persist batch progress and failed IDs so a restart retries remaining work instead
of repeating all HTTP requests. Do not advance complete coverage while relevant
items or pages remain unprocessed. Discovery failures and item failures must both
be visible. Separate metadata coverage from PDF/OCR and AI completion.

### 2. Make daily ingestion incremental and comprehensive

Keep Câmara's changed-proposition window, fix misleading descriptions, and
intersect returned IDs with the tracked inventory before applying theme filters.
Always update an already tracked proposition even if its latest ementa no longer
matches discovery keywords. Apply relevance filtering to new discoveries only.

Replace Senado's active-only legacy listing with the process change feed and
process/document endpoints. Explicitly verify closed-process coverage in tests.
Resolve and preserve existing legacy IDs; repair missing process mappings without
creating duplicate propositions or clearing previously known mappings.

For tracked changed IDs, fetch status/history and document metadata as needed.
Remove the daily restriction to human-assessed propositions. Fold the separate
enactment refresh into this same collection so daily jobs do not fetch the same
proposition twice. Preserve human annotations, approval, and existing alert rules.

Fetch Câmara histories with an overlapping date window after an initial full
baseline. Load existing event keys once per batch, insert new events and update
only corrected records. Use bounded full-history reconciliation for older source
corrections; retain existing event identity and legacy deduplication semantics.
Diff authors instead of deleting and recreating unchanged authors. Fetch/cache
author profiles only when needed; keep profile enrichment as its own scheduled job.
Invalidate public caches once after meaningful committed changes, not for every
checked but unchanged row.

Use a bounded reconciliation pass across all tracked IDs as a safety net for
source omissions, reactivation, and old corrections, distributed across daily
batches with a maximum proposed coverage age of seven days. This is separate
from daily changed-record coverage and does not enqueue AI for unchanged text.
If Senado's checkpoint gap exceeds its 30-day change-feed horizon, run an explicit
catch-up reconciliation and keep coverage incomplete until it finishes.

Start with small batches and at most two concurrent HTTP requests, bounded by a
per-source shared rate limiter, while keeping DB transactions short. Respect
Retry-After and retry transient transport/429/5xx failures with jitter. Do not
retry permanent 4xx responses blindly. The Senado specification warns that more
than ten requests per second can be limited; the initial rate should remain well
below that. Keep large PDFs and models out of the 512 MB ingestion worker.

### 3. Version documents and extract only changed content

Record source document ID/type, URL, source revision/date where available,
HTTP ETag/Last-Modified when supported, downloaded-byte hash, normalized-text hash,
extraction version/status and check/extraction timestamps. Separate immutable
document versions from the selected analysis text.

Use document metadata to identify new candidate versions, conditional HTTP reads
when validators are trustworthy, and a bytes hash before rerunning extraction/OCR.
Compare normalized extracted content before requesting AI. A URL is a locator,
not a content fingerprint: test replacement at the same URL and identical text at
a different URL. Preserve the last successful text on download/OCR failure; mark
the new version pending/failed instead of classifying old text as if it were new.

Silent changes at an unchanged URL with no updated source metadata or validators
cannot be detected without fetching bytes. Document this limit, use reconciliation
to check these cases, and measure the download cost before selecting a tighter
verification cadence. Do not claim every silent source mutation is detected daily.

Extraction/OCR runs asynchronously on a worker with enough memory, separately
from status collection. A document request must identify its version so a delayed
old request cannot overwrite newer text.

### 4. Gate and deduplicate classification

Persist classification requests with proposition, content version/hash, actual
model-input hash, model ID/revision, preprocessing version and relevant inference
configuration. Enforce a unique request key in PostgreSQL and enqueue after commit.
Periodically recover persisted requests that were not successfully published to
Celery; relying only on an in-memory signal or broker delivery is insufficient.

Only discovery or substantive content change creates a request. Before inference,
recheck whether that version already succeeded and whether a newer version has
superseded it. Recheck before saving so an older worker cannot overwrite a newer
analysis. Return immediately for an already successful request without loading
models. Keep the last successful prediction visible with explicit version/staleness
metadata while its replacement is pending. Preserve human-curated assessments.

Model changes and historical missing analyses have separate explicit maintenance
commands. A status update must not silently start a bulk historical AI backfill.
Seed hashes from existing stored content without network calls or inference;
legacy analyses whose provenance cannot be validated remain explicitly marked
rather than pretending they were analyzed against a verified new version.

### 5. Generate newsletters from the database

Make database-only preparation the default in both scheduled and manual flows.
Remove the weekly full-refresh preparation tasks and default the workflow refresh
option to false. Keep full refresh as a separately named recovery operation.
Wait/check against successful daily coverage for the requested period, not merely
the scheduled time or the existence of an IngestionRun row.

By default, preserve a prepared local preview but block Substack delivery if
source coverage is stale or incomplete. Provide an explicit manual override that
shows incomplete coverage in the draft. Drafting does not silently start collection
or AI. Metadata freshness need not wait for AI, because the Radar uses official
ementa and deterministic stage classification; pending substantive-text verification
remains visible separately.

For an end date of today, state the completed collection cutoff in the report:
morning ingestion cannot guarantee movements published later that same day.
For a historical report, track collection coverage separately from the dates of
the legislative events. Keep draft reservation, uncertain-delivery reconciliation,
and protection of human edits unchanged.

### 6. Roll out and measure

Deploy additive migrations and seed stored hashes/checkpoints first. Perform a
single explicit baseline reconciliation to fill current coverage gaps. Enable
selective AI before switching to comprehensive changed-record ingestion, so the
first daily catch-up cannot create an accidental mass reclassification.

Observe daily runs with counts for candidates, known/new records, HTTP requests,
actual DB writes, new/corrected events, content checks, downloads/OCR, skipped AI,
queued/completed AI, failed IDs and oldest outstanding work. Show progress and
last success in the admin/CLI and stream pipeline logs without Kamal buffering.
Retire overlapping refresh schedules only after the new daily path covers them.
Switch newsletters to the coverage gate after baseline and daily checks succeed.

Do not cancel or regenerate an existing frozen newsletter as part of this change.
The currently running manual full refresh is a separate execution and is not
modified by this plan. Preserve current human edits and alert deduplication.

## Acceptance checks

- An older, unapproved/unassessed tracked proposition changing status is updated
  by the next completed daily run; AI invocation count is zero.
- A Senate proposition closed yesterday still appears in changed-process coverage.
- An unchanged daily rerun does not download/OCR known documents, rewrite authors
  or events, or rerun AI. Coverage timestamps may advance.
- A new relevant proposition creates one classification request; overlapping
  discovery and duplicate Celery deliveries do not produce repeated inference.
- A changed principal document at the same URL is detected when the source
  revision/validator/content check exposes it and creates one new analysis.
- New URL or changed PDF packaging with identical normalized text produces no AI.
- Failed extraction does not discard the old text or publish a false success;
  recovery completes the pending version exactly once.
- A slow classifier for an older version cannot replace a newer result.
- Partial pagination, source outage, failed items, and a >30-day Senate gap prevent
  a complete coverage marker until recovery succeeds.
- Newsletter generation with fresh coverage makes zero official-source HTTP,
  PDF/OCR, or classifier calls, and only the existing draft-only Substack requests.
- Stale coverage blocks normal delivery; a deliberate override is labeled.
- API request counts scale with changed records plus bounded reconciliation,
  rather than a complete inventory refresh for every newsletter.

## Confirmed scope

Substantive replacement texts/substitutivos and amended main texts count as new
AI content versions. Reports and procedural documents do not. Status-only
changes never trigger AI.
