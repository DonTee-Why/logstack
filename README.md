# LogStack - Log Ingestor → Grafana Loki

A FastAPI-based log ingestion service that standardizes log formats, masks sensitive data, and provides resilient buffering via Write-Ahead Logs before forwarding to Grafana Loki.

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

### Installation

```bash
# Clone and navigate
git clone <repo-url>
cd logstack

# Install dependencies (FastAPI already installed)
pip install -e .

# Run the service
python -m uvicorn src.logstack.main:app --reload --host 0.0.0.0 --port 8080
```

### Basic Usage

```bash
# Ingest logs
curl -X POST http://localhost:8080/v1/logs:ingest \
  -H "Authorization: Bearer your-token-here" \
  -H "Content-Type: application/json" \
  -d '{
    "entries": [{
      "timestamp": "2025-09-21T20:12:34.567Z",
      "level": "ERROR", 
      "message": "Payment failed",
      "service": "payments-api",
      "env": "prod",
      "metadata": {"order_id": "O-123", "amount": 12000}
    }]
  }'

# Check health
curl http://localhost:8080/healthz
curl http://localhost:8080/readyz

# View metrics
curl http://localhost:8080/metrics
```

## 📋 API Endpoints

- `POST /v1/logs:ingest` - Main log ingestion (requires Bearer token)
- `GET /metrics` - Prometheus metrics
- `GET /healthz` - Liveness probe (always 200)
- `GET /readyz` - Readiness probe (checks dependencies)
- `POST /v1/admin/flush` - Manual WAL flush (admin token)

## 🔧 Configuration

Configuration via environment variables:

```bash
# Server
LOGSTACK_HOST=0.0.0.0
LOGSTACK_PORT=8080
LOGSTACK_DEBUG=false

# Security  
LOGSTACK_SECURITY_RATE_LIMIT_RPS=2000
LOGSTACK_SECURITY_RATE_LIMIT_BURST=10000

# WAL
LOGSTACK_WAL_ROOT_PATH=./wal
LOGSTACK_WAL_SEGMENT_MAX_BYTES=134217728  # 128MB
LOGSTACK_WAL_TOKEN_WAL_QUOTA_BYTES=2147483648  # 2GB

# Loki
LOGSTACK_LOKI_BASE_URL=http://localhost:3100
LOGSTACK_LOKI_TIMEOUT_SECONDS=30
```

## 🔒 Security Features

- **Bearer token authentication** at application level
- **Per-token rate limiting** with token-bucket algorithm  
- **Sensitive data masking** before WAL persistence
- **Global baseline masking**: `password`, `token`, `authorization`, `api_key`, `secret`, `card_number`
- **Per-token overrides** for additional masking rules

## 📊 Monitoring

Key Prometheus metrics:

```promql
# Throughput
rate(logs_ingested_total[5m])

# Error rate  
rate(logs_rejected_total[5m]) / rate(logs_ingested_total[5m]) * 100

# Latency
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# WAL health
wal_segments_active
wal_disk_usage_bytes
```

## 🗂️ Project Structure

```txt
src/logstack/
├── main.py              # FastAPI app entry point
├── config.py            # Configuration management
├── api/                 # API endpoints
│   ├── logs.py          # Log ingestion endpoint
│   ├── healthz.py       # Health checks  
│   └── metrics.py       # Prometheus metrics
├── core/                # Business logic
│   ├── auth.py          # Authentication & rate limiting
│   ├── pipeline.py      # Processing pipeline
│   ├── forwarder.py     # Async Loki forwarder
│   ├── metrics.py       # Metrics collection
│   └── exceptions.py    # Custom exceptions
└── models/              # Data models
    └── log_entry.py     # Pydantic schemas
```

## 📚 Documentation

- [**PRD**](docs/log_ingestor_→_loki_mvp_prd_v_0.md) - Product requirements
- [**ADR-001**](docs/adr/ADR-001-log-ingestor-system-architecture.md) - System architecture  
- [**ADR-002**](docs/adr/ADR-002-wal-segment-rotation-strategy.md) - WAL rotation strategy
- [**Metrics Guide**](docs/prometheus-metrics-guide.md) - Prometheus metrics reference

## 🚧 Development Status

**Current Phase**: MVP Foundation ✅

- [x] FastAPI project structure
- [x] Configuration management  
- [x] API endpoints (placeholder)
- [x] Pydantic data models
- [x] Authentication framework
- [x] Metrics collection setup
- [ ] WAL system implementation
- [ ] Data masking engine
- [ ] Async forwarder
- [ ] Health checks
- [ ] Comprehensive testing

## 🛣️ Roadmap

1. **Phase 1 (MVP)**: Single service with WAL buffering
2. **Phase 2**: Multi-replica deployment with shared storage  
3. **Phase 3**: Advanced masking (regex-based, field-level)
4. **Phase 4**: Dead-letter queues and replay mechanisms
5. **Phase 5**: Horizontal scaling with consistent hashing

## 🤝 Contributing

1. Follow the established patterns from ADR-001
2. Add comprehensive tests for new features
3. Update metrics for observability
4. Document configuration options

## 📄 License

MIT License - see LICENSE file for details.

---

**Built with ❤️ by Timi**
