# LogStack - Log Ingestor → Grafana Loki

A production-ready FastAPI-based log ingestion service that standardizes log formats, masks sensitive data, and provides resilient buffering via Write-Ahead Logs before forwarding to Grafana Loki.

## 🎯 Overview

LogStack implements a centralized log ingestion service with:

- **Schema enforcement**: Strict validation of log format and fields
- **Sensitive data masking**: Global baseline + per-token overrides  
- **Resilient buffering**: Per-token WAL queues with quotas
- **Async forwarding**: Round-robin delivery to Loki with retry logic
- **Observability**: Comprehensive Prometheus metrics and health checks

## 🏗️ Architecture

Based on **ADR-001**: Single FastAPI service with event-driven pipeline:

```txt
Client Services → FastAPI Ingestor → [Auth|Mask|Validate|WAL] → 202 Response
                                                  ↓
                                            Async Forwarder → Grafana Loki
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- FastAPI installed in your virtual environment
- Git
- Optional: Grafana Loki instance for log forwarding

### Installation

```bash
# Clone and navigate
git clone <repo-url>
cd logstack

# Create virtual environment
python -m venv .venv

# Activate virtual environment
source .venv/bin/activate #(Linux, macOS)
.\venv\Scripts\activate.bat #(Windows CMD)
.\venv\Scripts\Activate.ps1 #(Windows Powershell)

# Install dependencies
python -m pip install -r requirements.txt

# Run the service (development)
fastapi run src/logstack/main.py --reload

# Or run with uvicorn
python -m uvicorn src.logstack.main:app --reload --host 0.0.0.0 --port 8000
```

### Basic Usage

```bash
# Ingest logs (use one of the configured API keys from config.yaml)
curl -X POST http://localhost:8000/v1/logs:ingest \
  -H "Authorization: Bearer logstack_1a2b3c4d5e6f7890abcdef12" \
  -H "Content-Type: application/json" \
  -d '{
    "entries": [{
      "timestamp": "2025-09-24T12:00:00.000Z",
      "level": "ERROR", 
      "message": "Payment failed",
      "service": "payments-api",
      "env": "prod",
      "metadata": {"order_id": "O-123", "amount": 12000}
    }]
  }'

# Check health status
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz

# View Prometheus metrics
curl http://localhost:8000/metrics

# Admin operations (use admin token)
curl -X POST http://localhost:8000/v1/admin/flush \
  -H "Authorization: Bearer logstack_admin123456789abcdef0123"
```

## 📋 API Endpoints

| Endpoint | Method | Description | Auth Required |
|----------|---------|-------------|---------------|
| `/v1/logs:ingest` | POST | Main log ingestion endpoint | Bearer token |
| `/healthz` | GET | Liveness probe (always 200 when alive) | None |
| `/readyz` | GET | Readiness probe (checks Loki, disk, WAL, forwarder) | None |
| `/metrics` | GET | Prometheus metrics exposition | None |
| `/v1/admin/flush` | POST | Force WAL segment flush to Loki | Admin token |
| `/v1/admin/status` | GET | Admin status information | Admin token |
| `/` | GET | Service information and version | None |

## 🔧 Configuration

Configuration is managed via `config.yaml` file with environment variable overrides:

### Default Configuration File (`config.yaml`)

```yaml
# Server settings
server:
  host: "0.0.0.0"
  port: 8000
  debug: false
  log_level: "INFO"

# Security and authentication
security:
  rate_limit_rps: 1
  rate_limit_burst: 5
  admin_token: "logstack_admin123456789abcdef0123"
  api_keys:
    logstack_1a2b3c4d5e6f7890abcdef12:
      name: "payments-api"
      active: true
    logstack_9f8e7d6c5b4a3210fedcba98:
      name: "user-service"
      active: true

# Data masking rules
masking:
  baseline_keys: ["password", "token", "authorization", "api_key", "secret", "card_number", "email"]
  partial_rules:
    authorization:
      keep_prefix: 5
    email:
      mask_email: true

# WAL configuration
wal:
  wal_root_path: "./wal"
  segment_max_bytes: 134217728  # 128MB
  token_wal_quota_bytes: 2147483648  # 2GB per token

# Loki forwarding
loki:
  base_url: "http://localhost:3100"
  timeout_seconds: 30
  max_retries: 3
```

### Environment Variable Overrides

```bash
# Server
LOGSTACK_HOST=0.0.0.0
LOGSTACK_PORT=8000
LOGSTACK_DEBUG=false
LOGSTACK_LOG_LEVEL=INFO

# Security  
LOGSTACK_SECURITY_RATE_LIMIT_RPS=2000
LOGSTACK_SECURITY_RATE_LIMIT_BURST=10000
LOGSTACK_SECURITY_ADMIN_TOKEN=your-admin-token

# API Keys - Method 1: JSON string (all keys at once)
LOGSTACK_SECURITY_API_KEYS='{"logstack_123":{"name":"service1","active":true}}'

# API Keys - Method 2: Individual environment variables (recommended)
LOGSTACK_API_KEY_PAYMENTS_TOKEN=logstack_payments_123456789
LOGSTACK_API_KEY_PAYMENTS_NAME=payments-api
LOGSTACK_API_KEY_PAYMENTS_ACTIVE=true
LOGSTACK_API_KEY_PAYMENTS_DESCRIPTION="Payments service API key"

LOGSTACK_API_KEY_USER_TOKEN=logstack_user_987654321
LOGSTACK_API_KEY_USER_NAME=user-service
LOGSTACK_API_KEY_USER_ACTIVE=true

# WAL
LOGSTACK_WAL_ROOT_PATH=./wal
LOGSTACK_WAL_SEGMENT_MAX_BYTES=134217728

# Loki
LOGSTACK_LOKI_BASE_URL=http://localhost:3100
LOGSTACK_LOKI_TIMEOUT_SECONDS=30
```

### 🔑 API Key Management

LogStack supports multiple ways to configure API keys:

#### **Method 1: Individual Environment Variables (Recommended)**

```bash
# Define each API key separately
export LOGSTACK_API_KEY_PAYMENTS_TOKEN="logstack_payments_123456789"
export LOGSTACK_API_KEY_PAYMENTS_NAME="payments-api"
export LOGSTACK_API_KEY_PAYMENTS_ACTIVE="true"
export LOGSTACK_API_KEY_PAYMENTS_DESCRIPTION="Payments service API key"

export LOGSTACK_API_KEY_USER_TOKEN="logstack_user_987654321"
export LOGSTACK_API_KEY_USER_NAME="user-service"
export LOGSTACK_API_KEY_USER_ACTIVE="true"
```

**Pattern**: `LOGSTACK_API_KEY_{NAME}_{FIELD}`

- `{NAME}`: Uppercase identifier for your service (e.g., PAYMENTS, USER, ANALYTICS)
- `{FIELD}`: TOKEN (required), NAME, ACTIVE, DESCRIPTION

#### **Method 2: JSON Environment Variable**

```bash
export LOGSTACK_SECURITY_API_KEYS='{
  "logstack_payments_123": {
    "name": "payments-api",
    "active": true,
    "description": "Payments service API key"
  },
  "logstack_user_456": {
    "name": "user-service", 
    "active": true,
    "description": "User service API key"
  }
}'
```

#### **Method 3: Configuration File**

Define in `config.yaml` (as shown in the configuration section above).

**Priority Order**: Individual env vars > JSON env var > config file

## 🔒 Security Features

- **Bearer token authentication** with configurable API keys
- **Per-token rate limiting** using token-bucket algorithm
- **Comprehensive data masking** applied before WAL persistence:
  - **Global baseline**: `password`, `token`, `authorization`, `api_key`, `secret`, `card_number`, `email`
  - **Partial masking**: Email format (`e*****e@domain.com`), authorization prefix preservation
  - **Per-token overrides** for custom masking rules
- **Admin endpoints** protected with separate admin tokens
- **Structured security logging** for rate limiting and authentication events

## 📊 Monitoring & Observability

### Health Checks

- **`/healthz`**: Liveness probe (always 200 when service is alive)
- **`/readyz`**: Readiness probe checks:
  - Loki connectivity (can reach `/ready` endpoint)
  - Disk space (>20% free space available)
  - WAL integrity (directory writable, segments accessible)
  - Forwarder service (background async forwarder running)

### Prometheus Metrics

Available at `/metrics` endpoint:

```promql
# Throughput metrics
rate(logs_ingested_total[5m])
rate(http_requests_total[5m])

# Error rates
rate(logs_rejected_total[5m]) / rate(logs_ingested_total[5m]) * 100
rate(http_requests_total{status=~"4.."}[5m])

# Latency percentiles
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))

# WAL and system health
wal_segments_active{token="..."}
wal_disk_usage_bytes
rate_limit_exceeded_total{token="..."}
```

### Structured Logging

All components use structured logging with `structlog`:

- Authentication and authorization events
- Rate limiting decisions with detailed context
- WAL operations and segment rotations
- Forwarder status and retry attempts
- Health check results and failures

## 🗂️ Project Structure

```txt
src/logstack/
├── main.py              # FastAPI app entry point
├── config.py            # Configuration management (YAML + env vars)
├── api/                 # API endpoints
│   ├── logs.py          # Log ingestion endpoint
│   ├── admin.py         # Admin operations (flush, status)
│   ├── healthz.py       # Health checks (liveness, readiness)
│   └── metrics.py       # Prometheus metrics exposition
├── core/                # Business logic
│   ├── auth.py          # Authentication & rate limiting
│   ├── masking.py       # Data masking engine
│   ├── pipeline.py      # Processing pipeline orchestration
│   ├── wal.py           # Write-Ahead Log implementation
│   ├── forwarder.py     # Async Loki forwarder
│   ├── forwarder_service.py  # Background forwarder service
│   ├── health.py        # Comprehensive health checker
│   ├── metrics.py       # Metrics collection
│   └── exceptions.py    # Custom exceptions
└── models/              # Data models
    └── log_entry.py     # Pydantic schemas

tests/                   # Test suite
├── unit/               # Unit tests
│   ├── auth/           # Authentication tests
│   ├── masking/        # Data masking tests
│   └── wal/            # WAL system tests
└── integration/        # Integration tests
    └── auth/           # End-to-end auth tests

config.yaml             # Main configuration file
requirements.txt        # Python dependencies
```

## 📚 Documentation

- [**PRD**](docs/log_ingestor_→_loki_mvp_prd_v_0.md) - Product requirements
- [**ADR-001**](docs/adr/ADR-001-log-ingestor-system-architecture.md) - System architecture  
- [**ADR-002**](docs/adr/ADR-002-wal-segment-rotation-strategy.md) - WAL rotation strategy
- [**Metrics Guide**](docs/prometheus-metrics-guide.md) - Prometheus metrics reference

## 🚧 Development Status

**Current Phase**: MVP Complete! 🎉

### ✅ Completed Features

- [x] **FastAPI Application**: Production-ready FastAPI setup with lifespan management
- [x] **Configuration Management**: YAML config file with environment variable overrides
- [x] **Authentication & Security**: Bearer token auth with per-token rate limiting
- [x] **Data Masking Engine**: Global baseline + per-token overrides + partial masking
- [x] **Write-Ahead Log (WAL)**: Per-token directories, binary format, adaptive rotation
- [x] **Async Forwarder**: Background service with retry logic and Loki integration
- [x] **Health Checks**: Comprehensive `/healthz` and `/readyz` endpoints
- [x] **Admin Endpoints**: Manual flush and status operations
- [x] **Metrics**: Prometheus metrics exposition
- [x] **Structured Logging**: Complete observability with `structlog`
- [x] **API Endpoints**: Full log ingestion pipeline
- [x] **Error Handling**: Comprehensive exception handling and HTTP status codes

### 🔄 In Progress

- [x] **Unit Testing**: Auth components (TokenBucket, RateLimiter) ✅
- [ ] **Integration Testing**: End-to-end workflow tests
- [ ] **Performance Testing**: Load testing and benchmarking

### 📊 MVP Compliance

✅ **100% PRD Requirements Met**:
- Schema enforcement and validation
- Sensitive data masking (baseline + overrides)
- Per-token WAL buffering with quotas
- Async forwarding to Loki with retry logic
- Bearer token authentication
- Rate limiting (token-bucket algorithm)
- Health checks and observability
- Admin operations

## 🚀 Getting Started - Quick Demo

1. **Clone and setup**:

   ```bash
   git clone <repo-url> && cd logstack
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Start the service**:

   ```bash
   fastapi run --reload
   ```

3. **Send test logs**:

   ```bash
   curl -X POST http://localhost:8000/v1/logs:ingest \
     -H "Authorization: Bearer logstack_1a2b3c4d5e6f7890abcdef12" \
     -H "Content-Type: application/json" \
     -d '{"entries": [{"timestamp": "2025-09-24T12:00:00Z", "level": "INFO", "message": "Hello LogStack!", "service": "demo", "env": "dev"}]}'
   ```

4. **Check health and WAL**:

   ```bash
   curl http://localhost:8000/readyz | jq .
   ls -la wal/  # See WAL segments created
   ```

## 🛣️ Roadmap

- **✅ Phase 1 (MVP)**: Complete! Single service with WAL buffering, masking, auth, health checks
- **🔄 Phase 2**: Complete test coverage and performance benchmarking
- **📋 Phase 3**: Multi-replica deployment with shared storage  
- **📋 Phase 4**: Advanced masking (regex-based, field-level)
- **📋 Phase 5**: Dead-letter queues and replay mechanisms
- **📋 Phase 6**: Horizontal scaling with consistent hashing

## 🧪 Testing

Run the test suite:

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest

# Run specific test categories
pytest tests/unit/           # Unit tests only
pytest tests/integration/    # Integration tests only
pytest tests/unit/auth/      # Auth-specific tests
pytest -v                    # Verbose output
```

## 🤝 Contributing

1. Follow established patterns from ADR-001 and ADR-002
2. Add comprehensive tests for new features
3. Update metrics and monitoring for new components
4. Document configuration options in `config.yaml`
5. Ensure all health checks pass before submitting PRs

## 📄 License

MIT License - see LICENSE file for details.

## 🏆 Acknowledgments

Built following production-grade practices:

- **Architecture**: Event-driven pipeline with WAL buffering
- **Security**: Defense in depth with authentication, rate limiting, and data masking
- **Observability**: Comprehensive health checks, metrics, and structured logging
- **Reliability**: Async processing, retry logic, and graceful error handling

---

Built with ❤️ by Timi
