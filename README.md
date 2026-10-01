# HubSpot Master Service

> **Production service to extract, normalize, and store HubSpot CRM data securely, reliably, and resiliently.**

---

## 📌 Project Overview

**HubSpot Master Service** is an enterprise-grade extraction pipeline for HubSpot CRM. Its sole responsibility is to pull data from HubSpot on demand, flatten and normalize nested JSON records into tabular relational structures, export them as Parquet files, and publish them to S3-compatible object storage (MinIO).

It operates under a **Coordinator pattern**, executing background scan jobs with checkpointing, cooperative pause/resume capabilities, sliding-window rate limit throttling, and dual-key HMAC security.

---

## 🚀 Key Features

- **HubSpot OAuth & Private App Authentication**: Automatic access token refresh and token caching.
- **Cursor-Based Pagination**: Seamlessly fetches large datasets (`contacts`, `companies`, `deals`, `tickets`, `owners`).
- **Proactive Rate Limiting & 429 Handling**: Burst limit throttling (~100 req / 10s) and automatic `Retry-After` HTTP header honor.
- **Resilient Retry & Dead-Letter Queue (DLQ)**: Exponential backoff retries for transient errors; logs exhausted failures to the `failed_external_calls` database table with sensitive key redaction (`[REDACTED]`).
- **Granular Checkpointing**: Progress per object type is saved in PostgreSQL (`job_checkpoints`) to prevent data loss.
- **Cooperative Pause & Resume**: Jobs can be paused or resumed between pagination boundaries.
- **Data Normalization & Parquet Export**: Converts raw JSON arrays into tabular DataFrames and compressed Parquet files.
- **MinIO Storage Partitioning**: Uploads normalized tables using the key scheme:  
  `hubspot/{table_name}/glynac_organization_id={org_id}/processing_date={date}/{table}.parquet`
- **HMAC Security**: Request signature validation (`X-HS-Signature`, `X-HS-Timestamp`, `X-HS-Client-ID`, `X-HS-Nonce`) with dual keys (`COORDINATOR` full access vs. `ENGINEER` read-only GET operations).

---

## 🛠 Tech Stack

- **Language / Framework:** Python 3.10+, FastAPI, Uvicorn
- **Database:** PostgreSQL (SQLAlchemy ORM) / SQLite fallback
- **Storage:** MinIO (S3-compatible Object Storage), PyArrow / Pandas
- **Testing:** Pytest, HTTPX

---

## 📋 API Endpoints

### Scan Router (`/api/scan`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/scan/start` | Start a new scan job |
| `GET` | `/api/scan/{scan_id}/status` | Get job status, record counts & checkpoints |
| `POST` | `/api/scan/{scan_id}/pause` | Cooperatively pause a running job |
| `POST` | `/api/scan/{scan_id}/resume` | Resume a paused job from checkpoint |
| `POST` | `/api/scan/{scan_id}/cancel` | Cancel an active job |
| `GET` | `/api/scan/list` | List jobs with optional filtering |
| `GET` | `/api/scan/statistics` | Aggregate global scan metrics |
| `DELETE` | `/api/scan/{scan_id}/remove` | Remove job record and checkpoints |

### Normalization Router (`/api/normalization`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/normalization/{scan_id}/normalize` | Explicitly trigger normalization for scan data |
| `GET` | `/api/normalization/{scan_id}/tables` | List normalized Parquet files & storage keys |
| `GET` | `/api/normalization/supported-objects` | Supported object types list |

### Maintenance Router (`/api/maintenance`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/maintenance/cleanup` | Cleanup local temporary scan files |
| `POST` | `/api/maintenance/detect-crashed` | Transition stale running jobs to `CRASHED` |

### Public & Health (`/api`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Service health probe (DB & MinIO check) |
| `GET` | `/api/stats` | Public aggregate metrics |
| `POST` | `/api/validate-credentials` | Test HubSpot credentials validity |

---

## ⚡ Quickstart

### 1. Clone & Setup Environment
```bash
git clone https://github.com/kumkumgayki22/hubspot-master-service.git
cd hubspot-master-service
cp .env.example .env
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Application
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Interactive API Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 4. Run Test Suite
```bash
pytest -v
```

---

## 📄 License
MIT License
