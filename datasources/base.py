"""
Flight Monitor - Data Source Base Interface
"""
from abc import ABC, abstractmethod
from typing import List
from core.models import FlightPrice, SearchQuery


class BaseDataSource(ABC):
    """Abstract base class for all flight data sources."""

    name: str = "base"

    @abstractmethod
    def search_flights(self, query: SearchQuery) -> List[FlightPrice]:
        """Search for flights matching the query.

        Args:
            query: Search query with departure, destination, date, etc.

        Returns:
            List of FlightPrice objects.
        """
        pass

    def is_available(self) -> bool:
        """Check if this data source is currently available."""
        return True
