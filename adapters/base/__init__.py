"""SourceAdapter Protocol и RSSAdapter base class — контракты для адаптеров."""

from adapters.base.rss_adapter import RSSAdapter
from adapters.base.source_adapter import SourceAdapter

__all__ = [
    "RSSAdapter",
    "SourceAdapter",
]
