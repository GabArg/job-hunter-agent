"""Public job discovery adapters and aggregation."""

from .aggregator import DiscoveryAggregator, DiscoveryResult, SourceStats
from .base import JobSource
from .models import RawJob

__all__ = ["DiscoveryAggregator", "DiscoveryResult", "JobSource", "RawJob", "SourceStats"]
