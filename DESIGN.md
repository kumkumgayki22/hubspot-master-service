# HubSpot Master Service — Specification & Design

## 0. Getting Started — Account, Repo & Submission

### Set up your own repository
- Repository name: `hubspot-master-service`
- Includes `README.md`, Python `.gitignore`, and `DESIGN.md`.

## 1. What This Service Is, In Plain Terms

This service's only job is to **pull data out of HubSpot on demand and hand it off in a clean, organized form.**

Think of it as a pipeline with one job: given a HubSpot account, go get its data, clean it up, and put it somewhere it can be picked up and used. Nothing about scheduling ("when to run"), and nothing about what happens to the data afterward — this service only handles the extraction and cleanup step.

Another system (a "Coordinator") will be the one calling this service to say "start pulling data for this account", "how's it going", "pause/cancel it", etc. This service just needs to respond correctly to those requests and do the work reliably — including respecting HubSpot's rate limits so it never gets the account blocked or throttled unexpectedly.

## 2. What Exactly You Need To Build

1. **HubSpot Authentication**: Access tokens, refreshed automatically or Private App Tokens.
2. **Cursor-based Pagination**: Fetching data one page at a time (`contacts`, `companies`, `deals`, `tickets`, `owners`).
3. **Rate Limit Handling**: Handling HTTP 429 and `Retry-After` headers; honoring short burst (~100 req/10s) and daily limits.
4. **Checkpointing**: Saving page state per record type during extraction to avoid losing progress.
5. **Data Normalization**: Reorganizing HubSpot JSON objects into clean, flat relational tables.
6. **Storage Upload**: Saving normalized tables as Parquet or JSON files and uploading them to MinIO (S3-compatible storage).
7. **Job Tracking & Lifecycle**: Managing job status in PostgreSQL (`PENDING`, `RUNNING`, `PAUSED`, `RESUMING`, `NORMALIZING`, `UPLOADING_TO_MINIO`, `COMPLETED`, `FAILED`, `CANCELLED`, `CRASHED`).
8. **Pause & Resume**: Cooperative pausing between pagination boundaries; resuming from last checkpoint cursor.
9. **REST API**: Full suite of FastAPI endpoints for job control, normalization, maintenance, credentials validation, audit logs, and health probes.
10. **Security**: HMAC request signing with dual keys (`Coordinator` and `Engineer`), timestamp freshness validation, and replay protection.
11. **Resilience & Dead-Letter Queue**: Bounded retries with exponential backoff for transient failures; persisting failed calls to Dead-Letter Queue (`failed_external_calls` table) with redacted sensitive fields.

## 3. Tech Stack

- **Language/Framework:** Python 3.10+, FastAPI
- **Database:** PostgreSQL (SQLAlchemy ORM)
- **File storage:** MinIO (S3-compatible object storage)
- **Packaging:** Docker, Docker Compose

---

## 10. Technical Appendix

### 10.1 Architecture Overview

```
Coordinator (calls via signed HTTP)
        │
        ▼
HubSpot Master Service (FastAPI)
        │
        ├── Auth: HubSpot OAuth 2.0 (access token + refresh token, or private-app token)
        ├── Fetch: HubSpot CRM API v3 (cursor-based pagination via `after`/`paging.next.after`)
        ├── Rate limiting: burst limit (~100 req / 10s) + daily limit, honor `Retry-After` on 429
        ├── Checkpointing: persist last-seen cursor per object type, per run
        ├── Normalization: flatten HubSpot objects into relational tables
        └── Publish: upload normalized Parquet files to MinIO
```

### 10.2 Job Lifecycle / State Machine

```
PENDING
  → RUNNING
  → PAUSED (cooperative — checked between pages)
  → RESUMING
  → NORMALIZING
  → UPLOADING_TO_MINIO
  → COMPLETED
```

Side states: `FAILED`, `CANCELLED`, `CRASHED` (heartbeat timeout while `RUNNING`).

### 10.3 API Endpoints

- **`scan` router — `/api/scan`**:
  - `POST /scan/start`
  - `GET /scan/{scan_id}/status`
  - `POST /scan/{scan_id}/pause`
  - `POST /scan/{scan_id}/resume`
  - `POST /scan/{scan_id}/cancel`
  - `GET /scan/list`
  - `GET /scan/statistics`
  - `DELETE /scan/{scan_id}/remove`
- **`normalization` router — `/api/normalization`**:
  - `POST /normalization/{scan_id}/normalize`
  - `GET /normalization/{scan_id}/tables`
  - `GET /normalization/supported-objects`
- **`maintenance` router — `/api/maintenance`**:
  - `POST /maintenance/cleanup`
  - `POST /maintenance/detect-crashed`
- **`credentials` — `/api`**:
  - `POST /api/validate-credentials`
- **`audit` — `/api/audit`**:
  - `GET /audit/logs`
  - `GET /audit/stats`
- **Public — `/api`**:
  - `GET /api/health`
  - `GET /api/stats`

### 10.4 Storage Key Partitioning Scheme

`hubspot/{table_name}/glynac_organization_id={org_id}/processing_date={date}/{table}.parquet`
