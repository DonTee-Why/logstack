"""
LogStack - Internal Log Ingestor → Grafana Loki 

A FastAPI-based log ingestion service that standardizes log formats,
masks sensitive data, and provides resilient buffering via Write-Ahead Logs.
"""

__version__ = "0.1.0"
__author__ = "Timilehin Olusegun"
__email__ = "timiddon97@gmail.com"

from .main import app

__all__ = ["app"]
