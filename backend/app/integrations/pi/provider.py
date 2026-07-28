"""Abstract data provider for the PI Web API.

The provider hides the concrete transport (HTTP, mock, etc.) and exposes a
small, stable surface to the services layer. The current implementation
(``PiWebApiDataProvider``) talks to a real PI Web API via HTTPX; tests use
a mock or stub that satisfies the same contract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class PiPoint:
    """Metadata for a PI point resolved by the data provider."""

    web_id: str
    name: str
    description: Optional[str] = None
    engineering_unit: Optional[str] = None
    point_type: Optional[str] = None
    data_type: Optional[str] = None
    raw: Optional[dict] = None


@dataclass(frozen=True)
class PiValue:
    """A single value point from the PI Web API."""

    timestamp: datetime
    value: object
    good: bool = True
    questionable: bool = False
    substituted: bool = False
    units: Optional[str] = None


@dataclass(frozen=True)
class PiRecordedValues:
    """A set of recorded values for a PI point."""

    web_id: str
    values: List[PiValue]


@dataclass(frozen=True)
class PiInterpolatedValues:
    """A set of interpolated values for a PI point."""

    web_id: str
    values: List[PiValue]


class PiDataProvider(ABC):
    """Abstract PI data provider.

    Implementations are responsible for:
    * authenticating with the PI Web API;
    * applying timeouts and retry policy on idempotent GETs;
    * normalizing errors so the service layer can present a stable contract
      to the HTTP layer.
    """

    @abstractmethod
    async def ping(self) -> None:
        """Verify connectivity to the PI Web API."""

    @abstractmethod
    async def resolve_point(self, path: str) -> Optional[PiPoint]:
        """Resolve a PI point by its path.

        Returns ``None`` if the point does not exist.
        """

    @abstractmethod
    async def get_recorded_values(
        self,
        web_id: str,
        start_time: datetime,
        end_time: datetime,
        max_count: Optional[int] = None,
    ) -> PiRecordedValues:
        """Fetch recorded values for a point between two timestamps."""

    @abstractmethod
    async def get_interpolated_values(
        self,
        web_id: str,
        start_time: datetime,
        end_time: datetime,
        interval: str,
        max_count: Optional[int] = None,
    ) -> PiInterpolatedValues:
        """Fetch interpolated values for a point between two timestamps."""

    async def get_recorded_values_batch(
        self,
        web_ids: Sequence[str],
        start_time: datetime,
        end_time: datetime,
        max_count: Optional[int] = None,
    ) -> List[PiRecordedValues]:
        """Fetch recorded values for many points.

        Default implementation issues sequential calls. Concrete providers may
        override it to take advantage of batch endpoints when available.
        """
        results: List[PiRecordedValues] = []
        for web_id in web_ids:
            results.append(
                await self.get_recorded_values(web_id, start_time, end_time, max_count)
            )
        return results

    async def get_interpolated_values_batch(
        self,
        web_ids: Sequence[str],
        start_time: datetime,
        end_time: datetime,
        interval: str,
        max_count: Optional[int] = None,
    ) -> List[PiInterpolatedValues]:
        """Fetch interpolated values for many points."""
        results: List[PiInterpolatedValues] = []
        for web_id in web_ids:
            results.append(
                await self.get_interpolated_values(
                    web_id, start_time, end_time, interval, max_count
                )
            )
        return results
