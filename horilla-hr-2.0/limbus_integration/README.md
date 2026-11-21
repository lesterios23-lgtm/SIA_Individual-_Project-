# Limbus Integration — HR (Energy Cycle Human Capital)

This app implements **only the Human Resources system's responsibilities** from
`INTEGRATION-HANDOFF.md`. HR is the authority for employee identity and active
status. It publishes that lifecycle to Production through the Integration
Gateway and records Production events that need an accountable operator.

## Boundary

| HR does | HR does not |
| --- | --- |
| Queue and send employee lifecycle events | Write to PostgreSQL, InvenTree, or another system's database |
| Own the employee external ID (`Employee.badge_id`) | Own the gateway's `integration_event` / `integration_mapping` tables |
| Record gateway responses and attempts | Create InvenTree users, parts, stock, builds, or orders |
| Flag missing/unknown/inactive operators | Invent an employee ID, operator ID, endpoint, or credential |

The local tables in `limbus_integration` are HR's **sender-side outbox and
audit trail**. They are not the gateway's central tables.

## Contract mapping

The OpenAPI document is the API contract. It defines:

* `POST /events` with the `EventEnvelope` body
* `GET /events/{event_id}` for status
* headers `Authorization`, `Content-Type`, `Idempotency-Key`,
  `X-Limbus-System`
* `additionalProperties: false` on the envelope

The handoff lists per-system endpoints such as
`POST /api/v1/integration/events/employee-upsert`. Those paths are not present
in `integration-openapi.yaml`. HR therefore submits the documented envelope to
the documented `/events` endpoint and sets `event_type`:

| Handoff endpoint | `event_type` sent |
| --- | --- |
| `/events/employee-upsert` | `employee.upsert` |
| `/events/employee-deactivate` | `employee.deactivate` |

This follows the handoff's own naming pattern (`purchase-received` endpoint ↔
`purchase.received` event type). If the gateway later exposes typed paths, only
`GatewayClient.post_event` changes; the envelope, idempotency and outbox do not.

## Outbound flow

1. An `Employee` or `EmployeeWorkInformation` save enqueues a row in
   `OutboundEvent` (or a management command does it in bulk).
2. The row is written **before** any network call. A gateway outage therefore
   cannot fail the HR save.
3. `limbus_process_outbox` claims due rows, sends `POST /events`, and records
   an `OutboundEventAttempt` audit row.
4. `event_id` is the `Idempotency-Key` and is reused on every retry.
5. A 2xx `received` response marks the event `delivered`; the gateway owns the
   rest of processing. `succeeded`/`duplicate` marks it `succeeded`.
6. A 4xx (400/401/403/409) marks it `failed` and is **not retried unchanged**.
   An operator fixes the cause and uses `limbus_requeue_event`.
7. A 5xx, timeout, 408/425/429 is retried after 1, 5, 15, 60 seconds. After
   five attempts the event becomes `failed` and is logged at ERROR level.
8. `GET /events/{event_id}` is available through `limbus_event_status --poll`.
   Polling is advisory and never rewrites a successful delivery as a failure.

### Employee payload

Every value is a string or null; dates are ISO-8601. No units are inferred.

```json
{
  "employee_id": "EMP-001",
  "status": "active",
  "first_name": "Jane",
  "last_name": "Doe",
  "full_name": "Jane Doe",
  "email": "jane.doe@example.com",
  "department_id": "3",
  "department": "Manufacturing",
  "job_position_id": "7",
  "job_title": "Machine Operator",
  "job_role_id": "2",
  "job_role": "Shift A",
  "manager_employee_id": "EMP-000",
  "manager_name": "Mona Manager",
  "start_date": "2025-01-06",
  "end_date": "2026-01-05",
  "company_id": "1",
  "company": "Energy Cycle"
}
```

`Employee.badge_id` is the external employee ID. It is normalized by trimming
and collapsing internal whitespace; case is preserved. If it is missing, HR
does **not** invent an ID: the event is stored as `blocked` with
`error_code=missing_identity` so HR can fix the record and re-sync. A manager
without a badge ID is published as `manager_employee_id: null` with the
manager's name, rather than a guessed ID.

The default correlation ID is `hr-employee-<external_id>` (or
`hr-employee-pk-<pk>` for a blocked record without an external ID).

## Inbound flow

HR receives Production events that require an accountable operator: build, QC
and approval actions, plus rejected-time and missing-identity events.

The OpenAPI document does not yet define how the gateway delivers events to
HR. To avoid inventing an endpoint or a credential, the domain handler is
`limbus_integration.inbound.ingest_inbound_event`, and the current adapter is:

```text
python manage.py limbus_ingest_inbound --file events.json
python manage.py limbus_ingest_inbound --file -   # stdin
```

The file may contain one JSON object, a JSON array, or newline-delimited JSON.
The payload is the documented `EventEnvelope`. When the gateway publishes its
delivery contract, replace only this adapter.

Handling rules:

* Replay of the same `event_id` returns the stored result and creates no row.
* Only `source_system: production` is processed; anything else is `ignored`.
* The operator is resolved from `payload.operator_external_id` or
  `payload.employee_id` against `Employee.badge_id`.
* Missing, unknown or inactive operators become `exception` rows with
  `resolution` `missing_identity`, `unknown_operator`, or `inactive_operator`.
* `build.*`, `qc.*`, `approval.*` events resolve to `processed`.
* Unknown event types are stored and `ignored`; the gateway's allowlist is
  authoritative, so HR does not guess at new types.

## Configuration

All values are environment variables; the token has no default and is never
committed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LIMBUS_GATEWAY_URL` | `http://localhost:8088/api/v1/integration` | Documented local/private development server |
| `LIMBUS_HR_TOKEN` | empty | HR's least-privilege bearer token; required to send |
| `LIMBUS_HTTP_TIMEOUT` | `15` | Per-request timeout in seconds |
| `LIMBUS_OUTBOX_MAX_ATTEMPTS` | `5` | Attempt cap before `failed` |
| `LIMBUS_OUTBOX_BATCH_SIZE` | `50` | Rows claimed per worker run |
| `LIMBUS_AUTO_PUBLISH` | `True` | Enqueue on model saves; set `False` for bulk imports |

## Commands

| Command | Purpose |
| --- | --- |
| `limbus_sync_employees` | Queue `employee.upsert` for existing employees; `--dry-run` previews |
| `limbus_deactivate_employee` | Queue `employee.deactivate`; refuses an active employee without `--force` |
| `limbus_process_outbox` | Send due events; `--reclaim-stale` recovers crashed workers |
| `limbus_event_status` | Show status; `--poll` calls `GET /events/{event_id}` |
| `limbus_requeue_event` | Requeue a failed/delivered event after an operator fix |
| `limbus_ingest_inbound` | Ingest Production event envelopes |

Every result is a JSON object containing **both** `event_id` and
`correlation_id`. Command-level failures also include a run correlation ID and
`event_id: null` when no event was created. Dry runs and lookups that did not
create an event return `event_id: null` deliberately rather than fabricating
an ID.

Examples:

```bash
python manage.py limbus_sync_employees --dry-run --limit 10
python manage.py limbus_process_outbox --limit 100
python manage.py limbus_event_status --event-id <uuid> --poll
python manage.py limbus_requeue_event --event-id <uuid> --reset-attempts
python manage.py limbus_deactivate_employee --employee EMP-001
```

## Tests

The suite covers:

* envelope fields, string IDs, ISO dates and payload hash stability
* external-ID normalization and blocked missing identities
* active→inactive and inactive→active lifecycle transitions
* documented URL/headers/body, including `Idempotency-Key == event_id`
* duplicate, 400, 401, 403, 409, 429, 5xx and timeout classification
* retry scheduling, same key across retries, attempt cap
* poll, requeue and result shape (`event_id` + `correlation_id`)
* inbound replay, operator resolution and exception reasons
* command output shape and missing-token refusal

Run with the project's normal test runner:

```bash
python manage.py test limbus_integration
```

## Acceptance-test coverage (HR side)

| Handoff test | HR implementation |
| --- | --- |
| 1. Duplicate replay | `event_id`/`Idempotency-Key` reuse; `OutboundEvent` dedupe by payload hash; inbound `event_id` uniqueness |
| 2. Missing fields | Envelope validation returns field-level errors for inbound; blocked outbox rows expose missing `badge_id` |
| 3. Invalid token | 401 is classified as non-retryable `failed`; missing token refuses to send |
| 4. Unauthorized event type | Only `employee.upsert` / `employee.deactivate` can be enqueued; gateway 403 is non-retryable |
| 5. Gateway outage | Events persist in the outbox and retry with backoff |
| 7. Employee deactivation | `employee.deactivate` is published on the active→inactive transition; payload status is `inactive` |
| 10. Mapping | Every sent event carries `external_id`; missing identity is blocked, never guessed |

Tests 6, 8 and 9 belong to Supply Chain, Sales and Production and are not
implemented here.

## Security notes

* The token is read from `LIMBUS_HR_TOKEN`; it is not stored in the database,
  logged, or returned in results.
* The gateway URL must be an absolute `http(s)` URL. Production should use
  HTTPS and a private network allowlist.
* The admin exposes the outbox and inbound audit rows as read-only.
* A 4xx is never retried unchanged. A 429 honours `Retry-After`; a 5xx or
  transport failure uses exponential-style backoff from the handoff.
