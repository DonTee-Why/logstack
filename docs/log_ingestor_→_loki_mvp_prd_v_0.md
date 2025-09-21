# Product Requirements Document (PRD) — MVP

**Project:** Internal Log Ingestor → Grafana Loki  
**Mode:** Service/API (FastAPI recommended)  
**Version:** v1.0 (MVP, rewritten)

---

## 1. Objective

Develop a central service that standardizes log ingestion across the organization. The service will enforce schema consistency, mask sensitive data, buffer logs reliably using per-service disk queues (WAL), and forward them to **Grafana Loki**. The goal is to ensure consistency, resilience, and observability from day one.

---

## 2. Scope

### In-Scope (MVP)

- **Schema enforcement**: Strict validation of log format and fields.
- **Normalization & serialization**: Standardized Loki label mapping and compact JSON log lines.
- **Sensitive data masking**: Global baseline masking with per-token overrides.
- **Ingestion resilience**: Per-token WAL queues, quotas, and retry/backoff mechanisms.
- **Security**: TLS, bearer token authentication at the application level, per-token rate limits.
- **Observability**: Prometheus metrics, health/readiness probes, and starter Grafana dashboards.

### Out-of-Scope (MVP)

- Multi-replica deployments.
- Central database (no DB used).
- Dead-letter queues and replay tools.
- Regex-based masking (MVP supports key-only masking).
- Tracing and advanced transformations.

---

## 3. API Endpoints

### `POST /v1/logs:ingest`

**Headers**:

- `Authorization: Bearer <token>` — validated directly by the application.
- Optional: `X-Idempotency-Key` — best-effort deduplication within a 15-minute window.

**Request Body Example**:

```json
{
  "entries": [
    {
      "timestamp": "2025-09-21T20:12:34.567Z",
      "level": "ERROR",
      "message": "Payment failed",
      "service": "payments-api",
      "env": "prod",
      "labels": {"region": "eu-west-1"},
      "trace_id": "abc123",
      "span_id": "def456",
      "metadata": {"order_id": "O-123", "amount": 12000, "currency": "NGN"}
    }
  ]
}
```

**Validation Rules**:

- Required: `timestamp` (RFC3339), `level` ∈ `[DEBUG, INFO, WARN, ERROR, FATAL]`, `message`, `service`, `env`.
- Labels: allowlisted `{service, env, level, schema_version, region, tenant}`, ≤6 keys, value length ≤64 chars.
- Entry size ≤ 32KB; batch size ≤ 500 entries or 1MB.

**Responses**:

- `202 Accepted` — logs enqueued successfully.
- `400 Bad Request` — invalid schema.
- `401 Unauthorized` — invalid or missing token.
- `429 Too Many Requests` — quota or rate limit exceeded.
- `500 Internal Server Error` — unexpected failure.

### `GET /metrics`

Prometheus metrics (ingestion rates, WAL usage, retries, masking counts).

### `GET /healthz`

Liveness probe (always 200 if service alive).

### `GET /readyz`

Readiness probe: 200 only if Loki reachable in last 60s, disk free >20%, WAL integrity OK.

---

## 4. Processing Pipeline

1. **Authentication & Rate Limiting** — validate token and enforce per-token rate caps inside the app.
2. **Masking Engine** — apply global baseline + per-token key masks before persistence.
3. **Schema Validator** — enforce required fields, enums, and caps.
4. **Normalizer** — extract allowed labels, serialize remaining data as compact JSON line with `ingest_time`.
5. **WAL Append** — enqueue normalized entries into per-token WAL segments.
6. **Acknowledgement** — return `202` after WAL write.
7. **Forwarder (async)** — round-robin per token, build Loki push payloads, send, retry with backoff, delete segments on success.

---

## 5. WAL (Write-Ahead Log)

- **Per-token directories**: `wal/<token>/...`.
- **Segments**: 128MB max or 1h age, then rotated.
- **Quotas**: 2GB or 24h per token, whichever first.
- **Backpressure**: If ≥80% of quota → 429 to that token only; if disk free <20% → 429 to all tokens.
- **Integrity**: Each segment checksum verified; corrupt segments skipped and counted.
- **Retention**: Old segments purged once quota exceeded.

---

## 6. Security

- TLS termination at proxy or app server.
- Bearer tokens validated at the application level.
- Per-token rate limiting (in-app token bucket).
- Masking before WAL write.
- No persistence of raw tokens or secrets.

---

## 7. Sensitive Data Masking

- **Global baseline keys** (always masked): `password, token, authorization, api_key, secret, card_number`.
- **Per-token overrides**: additional keys and partial masking rules.
- **Execution**: Applied before WAL persistence.
- **Metrics**: `masked_fields_total{token,key}`, `masking_errors_total`.
- **Fallback**: If per-token config fails, baseline-only masking is enforced.

---

## 8. Observability

- Prometheus metrics (ingest totals, rejects, latencies, WAL depth, retries, 429s, masking counts).
- `/healthz` and `/readyz` endpoints.
- Starter Grafana dashboard: ingest rate, WAL utilization, backpressure events, Loki push latency.

---

## 9. Non-Functional Requirements

- **Throughput**: ≥1,000 entries/s on one small node.
- **Latency**: p95 ingest latency <200ms (steady state, no WAL pressure).
- **Durability**: 0% loss within quota during ≤10 min Loki outage.
- **Security**: All endpoints over TLS; masking applied before persistence.
- **Operability**: Config hot-reload; graceful shutdown drains queues.

---

## 10. Acceptance Criteria

- Invalid requests rejected with 400; valid requests acked with 202.
- Token validation and rate limits enforced in-app.
- Masking confirmed in WAL samples; no secrets appear.
- Per-token WAL isolation proven: one token at quota → only that token throttled.
- Loki outage (≤10 min) → 0% loss while within quota.
- `/readyz` reflects Loki reachability and disk headroom.

---

## 11. Config Defaults

```yaml
limits:
  entry_bytes_max: 32768
  batch_entries_max: 500
  batch_bytes_max: 1048576
  token_wal_quota_bytes: 2147483648   # 2GB
  token_wal_quota_age_hours: 24
  wal_segment_bytes: 134217728        # 128MB
  disk_free_min_ratio: 0.20
  backoff_seconds: [5, 10, 20]
  backoff_park_seconds: 60
security:
  rate_limit_rps: 2000
  rate_limit_burst: 10000
masking:
  baseline_keys: ["password","token","authorization","api_key","secret","card_number"]
  partial:
    authorization: { keep_prefix: 5 }
  tenants: {}   # additive keys per token as needed
```

---

**End of PRD v1.0**
