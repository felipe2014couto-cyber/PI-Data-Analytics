"""StreamSet batch client for PI Web API.

Sends multiple WebIds in a single request using ``/streamsets/{mode}``.
Supports safe fallback to individual endpoints when StreamSet is unsupported.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

from app.core.config import settings
from app.core.exceptions import QueryLimitExceeded
from app.integrations.pi.errors import (
    PiAuthError,
    PiIntegrationError,
    PiInvalidResponseError,
    PiRateLimitedError,
    PiTagNotFoundError,
    PiTimeoutError,
    PiUnavailableError,
)
from app.integrations.pi.provider import PiValue
from app.integrations.pi.webapi_provider import (
    _parse_value_entry,
    get_global_semaphore,
)

logger = logging.getLogger("pi_analytics_data.service.streamset")


class StreamSetCapability(Enum):
    UNKNOWN = auto()
    SUPPORTED = auto()
    UNSUPPORTED = auto()


@dataclass
class StreamSetState:
    recorded: StreamSetCapability = StreamSetCapability.UNKNOWN
    interpolated: StreamSetCapability = StreamSetCapability.UNKNOWN
    checked_at_recorded: float = 0.0
    checked_at_interpolated: float = 0.0

    RETRY_TTL: float = 600.0  # 10 minutes

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def is_supported(self, mode: str) -> bool:
        async with self._lock:
            cap = self.recorded if mode == "recorded" else self.interpolated
            if cap == StreamSetCapability.SUPPORTED:
                return True
            if cap == StreamSetCapability.UNKNOWN:
                return True
            checked = self.checked_at_recorded if mode == "recorded" else self.checked_at_interpolated
            return (time.monotonic() - checked) >= self.RETRY_TTL

    async def mark_unsupported(self, mode: str) -> None:
        async with self._lock:
            if mode == "recorded":
                self.recorded = StreamSetCapability.UNSUPPORTED
                self.checked_at_recorded = time.monotonic()
            else:
                self.interpolated = StreamSetCapability.UNSUPPORTED
                self.checked_at_interpolated = time.monotonic()

    async def mark_supported(self, mode: str) -> None:
        async with self._lock:
            if mode == "recorded":
                self.recorded = StreamSetCapability.SUPPORTED
                self.checked_at_recorded = time.monotonic()
            else:
                self.interpolated = StreamSetCapability.SUPPORTED
                self.checked_at_interpolated = time.monotonic()


_CAPABILITY = StreamSetState()

_UNSUPPORTED_CODES = {400, 404, 405, 501}

_STREAMSET_BATCH_SIZE = getattr(settings, "pi_query_streamset_batch_size", 10)


@dataclass
class StreamSetResult:
    web_id: str
    values: List[PiValue]


def _safe_mask_webid(web_id: Any) -> str:
    """Mask a WebId for diagnostic logging."""
    if not isinstance(web_id, str):
        return "<non-string>"
    if len(web_id) <= 6:
        return web_id[:2] + "***"
    return web_id[:3] + "***" + web_id[-2:]


def _dump_payload_structure(payload: Any, depth: int = 0, max_depth: int = 6) -> List[str]:
    """Return safe structural description lines of a PI payload (no values/WebIDs)."""
    lines: List[str] = []
    prefix = "  " * depth
    if isinstance(payload, list):
        lines.append(f"{prefix}list len={len(payload)}")
        if payload and depth < max_depth:
            _dump_node_structure(payload[0], depth, "list[0]", lines, max_depth)
    elif isinstance(payload, dict):
        lines.append(f"{prefix}dict keys={sorted(payload.keys())}")
        if depth < max_depth:
            for k in sorted(payload.keys()):
                _dump_node_structure(payload.get(k), depth, k, lines, max_depth)
    else:
        lines.append(f"{prefix}{type(payload).__name__}")
    return lines


def _dump_node_structure(
    node: Any, depth: int, label: str, lines: List[str], max_depth: int
) -> None:
    """Append a single structural line for *node*."""
    prefix = "  " * (depth + 1)
    if isinstance(node, dict):
        keys = sorted(node.keys())
        lines.append(f"{prefix}{label}: dict keys={keys}")
        if "WebId" in node:
            lines.append(f"{prefix}{label}.WebId: string masked={_safe_mask_webid(node['WebId'])}")
        has_ts = "Timestamp" in node or "timestamp" in node
        has_val = "Value" in node or "value" in node
        has_good = "Good" in node or "good" in node
        has_items = "Items" in node or "items" in node
        has_values_key = "Values" in node or "values" in node
        if has_items:
            inner = node.get("Items") or node.get("items")
            lines.append(f"{prefix}{label}.Items: {type(inner).__name__} len={len(inner) if isinstance(inner, (list, dict)) else '?'}")
        if has_values_key:
            lines.append(f"{prefix}{label}.Values: present")
        if has_ts:
            lines.append(f"{prefix}{label}.Timestamp: present")
        if has_val:
            val = node.get("Value") if "Value" in node else node.get("value")
            val_type = type(val).__name__
            if isinstance(val, dict):
                val_keys = sorted(val.keys())
                lines.append(f"{prefix}{label}.Value: dict keys={val_keys}")
                if "Items" in val or "items" in val:
                    inner = val.get("Items") or val.get("items")
                    lines.append(f"{prefix}{label}.Value.Items: {type(inner).__name__} len={len(inner) if isinstance(inner, (list, dict)) else '?'}")
                    if isinstance(inner, list) and inner and depth + 2 < max_depth:
                        first = inner[0]
                        if isinstance(first, dict):
                            lines.append(f"{prefix}{label}.Value.Items[0]: dict keys={sorted(first.keys())}")
            elif isinstance(val, list):
                lines.append(f"{prefix}{label}.Value: list len={len(val)}")
            else:
                lines.append(f"{prefix}{label}.Value: {val_type}")
        if has_good:
            lines.append(f"{prefix}{label}.Good: present")
        if "Errors" in node:
            lines.append(f"{prefix}{label}.Errors: {type(node['Errors']).__name__}")
    elif isinstance(node, list):
        lines.append(f"{prefix}{label}: list len={len(node)}")
        if node and depth + 1 < max_depth:
            _dump_node_structure(node[0], depth + 1, f"{label}[0]", lines, max_depth)
    elif node is None:
        lines.append(f"{prefix}{label}: None")
    else:
        lines.append(f"{prefix}{label}: {type(node).__name__}")


def _parse_streamset_response(
    payload: Any,
    error_collector: Optional[Dict[str, List[dict]]] = None,
) -> Dict[str, List[PiValue]]:
    """Parse StreamSet response keyed by WebId.

    PI Web API ``/streamsets/{mode}`` returns:
    ``{"Items": [{"WebId": "...", "Items": [value, ...]}, ...]}``

    Each series entry contains a flat list of value objects with at least a
    ``Timestamp`` key.  Entries containing a non-empty ``Errors`` list are
    PI error responses, not process points, and are excluded from the
    returned values.  When *error_collector* is provided, error entries
    are recorded keyed by WebId for recovery by the caller.
    """
    if not isinstance(payload, dict):
        raise PiInvalidResponseError(
            "Resposta do StreamSet nao e um objeto JSON."
        )

    items = payload.get("Items") if "Items" in payload else payload.get("items")
    if not isinstance(items, list):
        raise PiInvalidResponseError(
            "Resposta do StreamSet nao contem 'Items'."
        )

    results: Dict[str, List[PiValue]] = {}

    def parse_series_values(node: Any, web_id: str) -> List[PiValue]:
        """Walk containers inside one StreamSet series without crossing WebIds."""
        values: List[PiValue] = []

        def visit(current: Any) -> None:
            if isinstance(current, list):
                for child in current:
                    visit(child)
                return
            if not isinstance(current, dict):
                return

            for key in ("Items", "items", "Values", "values"):
                if key in current:
                    visit(current.get(key))
                    return

            for value_key in ("Value", "value"):
                nested_value = current.get(value_key)
                if isinstance(nested_value, dict) and any(
                    key in nested_value for key in ("Items", "items", "Values", "values")
                ):
                    visit(nested_value)
                    return

            if "Timestamp" in current or "timestamp" in current:
                errors = current.get("Errors") or current.get("errors")
                if errors and isinstance(errors, list) and len(errors) > 0:
                    if error_collector is not None:
                        error_collector.setdefault(web_id, []).append({
                            "timestamp": current.get("Timestamp"),
                            "errors": errors,
                        })
                    logger.debug(
                        "StreamSet error entry excluded for %s",
                        _safe_mask_webid(web_id),
                    )
                    return
                values.append(_parse_value_entry(current))

        visit(node)
        return values

    for entry in items:
        if not isinstance(entry, dict):
            continue
        web_id = entry.get("WebId") or entry.get("webId")
        if not web_id:
            continue
        if "Items" in entry:
            sub_items = entry.get("Items")
        elif "items" in entry:
            sub_items = entry.get("items")
        elif "Value" in entry:
            sub_items = entry.get("Value")
        else:
            sub_items = entry.get("value")
        str_wid = str(web_id)
        values = parse_series_values(sub_items, str_wid)
        results.setdefault(str_wid, []).extend(values)

    return results


_WINDOW_MAX_DAYS = 30


def _deduplicate_values(values: List[PiValue]) -> List[PiValue]:
    """Remove duplicate points by timestamp within a single series."""
    if len(values) <= 1:
        return values
    seen: set = set()
    result: List[PiValue] = []
    for v in sorted(values, key=lambda x: x.timestamp):
        if v.timestamp not in seen:
            seen.add(v.timestamp)
            result.append(v)
    return result


def _safe_window_str(start: datetime, end: datetime) -> str:
    """Safe time-window representation for logging."""
    return f"{start.strftime('%Y-%m-%d')}..{end.strftime('%Y-%m-%d')}"


async def _recover_failed_series(
    failed_web_ids: List[str],
    start_time: datetime,
    end_time: datetime,
    interval: str,
    max_count: Optional[int],
    provider,
    semaphore: asyncio.Semaphore,
) -> Tuple[Dict[str, List[PiValue]], Dict[str, List[str]]]:
    """Recover series that returned only PI error entries using 30-day windows.

    Each affected WebId is fetched individually via the interpolated endpoint
    with non-overlapping windows.  Partial results are kept when some windows
    succeed and others fail.  Returns ``(recovered_values, window_errors)``.
    """
    recovered: Dict[str, List[PiValue]] = {}
    window_errors: Dict[str, List[str]] = {}
    window = timedelta(days=_WINDOW_MAX_DAYS)

    for web_id in failed_web_ids:
        series_values: List[PiValue] = []
        current_start = start_time
        errors_for_web: List[str] = []

        while current_start < end_time:
            current_end = min(current_start + window, end_time)

            async with semaphore:
                try:
                    response = await provider.get_interpolated_values(
                        web_id,
                        current_start,
                        current_end,
                        interval=interval,
                        max_count=max_count,
                    )
                    series_values.extend(response.values)
                except PiIntegrationError as exc:
                    window_label = _safe_window_str(current_start, current_end)
                    errors_for_web.append(f"{window_label}: {exc.safe_message}")
                    logger.warning(
                        "Windowed recovery failed for %s window %s: %s",
                        _safe_mask_webid(web_id),
                        window_label,
                        exc.safe_message,
                    )

            current_start = current_end

        deduped = _deduplicate_values(series_values)

        if deduped:
            recovered[web_id] = deduped
            if errors_for_web:
                window_errors[web_id] = errors_for_web
                logger.info(
                    "Partial recovery for %s: %d points, %d failed windows",
                    _safe_mask_webid(web_id),
                    len(deduped),
                    len(errors_for_web),
                )
        else:
            window_errors[web_id] = errors_for_web or ["No data returned"]

    return recovered, window_errors


def _is_streamset_unsupported_error(exc: PiIntegrationError) -> bool:
    return hasattr(exc, "status_code") and exc.status_code in _UNSUPPORTED_CODES


def _should_not_fallback(exc: PiIntegrationError) -> bool:
    return isinstance(exc, (PiAuthError, PiRateLimitedError, PiTimeoutError, PiUnavailableError))


async def _individual_fetch(
    web_id: str,
    start_time: datetime,
    end_time: datetime,
    mode: str,
    interval: Optional[str],
    max_count: Optional[int],
    provider,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, List[PiValue], int]:
    """Fetch values for a single WebId via individual endpoint.

    Returns (web_id, values, retry_count).
    """
    retries = 0
    async with semaphore:
        try:
            if mode == "recorded":
                response = await provider.get_recorded_values(
                    web_id, start_time, end_time, max_count=max_count
                )
            else:
                response = await provider.get_interpolated_values(
                    web_id, start_time, end_time, interval=interval or "1m", max_count=max_count
                )
        except PiIntegrationError:
            raise
        return web_id, response.values, retries


async def fetch_streamset_batch(
    web_ids: List[str],
    start_time: datetime,
    end_time: datetime,
    mode: str,
    interval: Optional[str],
    max_count: Optional[int],
    provider,
) -> Tuple[Dict[str, List[PiValue]], int, bool]:
    """Fetch values for multiple WebIds in a single StreamSet call.

    Returns (results_by_web_id, request_count, used_streamset).
    """
    if not web_ids:
        return {}, 0, False

    if not await _CAPABILITY.is_supported(mode):
        return {}, 0, False

    semaphore = get_global_semaphore()
    batch_size = _STREAMSET_BATCH_SIZE
    all_results: Dict[str, List[PiValue]] = {}
    total_requests = 0
    used_streamset = False
    error_info: Dict[str, List[dict]] = {}

    for i in range(0, len(web_ids), batch_size):
        batch = web_ids[i : i + batch_size]
        params: List[Tuple[str, Any]] = [
            ("webId", wid) for wid in batch
        ]
        params.append(("startTime", start_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
        params.append(("endTime", end_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
        if interval and mode == "interpolated":
            params.append(("interval", interval))
        if max_count is not None:
            params.append(("maxCount", int(max_count)))

        streamset_path = f"/streamsets/{mode}"

        async with semaphore:
            total_requests += 1
            try:
                response = await provider._safe_request(
                    "GET", streamset_path, params=params
                )
                payload = response.json()
                if logger.isEnabledFor(logging.DEBUG):
                    try:
                        struct_lines = _dump_payload_structure(payload, max_depth=4)
                        logger.debug(
                            "StreamSet %s payload structure (%d lines):",
                            mode, len(struct_lines),
                        )
                        for line in struct_lines:
                            logger.debug("  SS_STRUCT %s", line)
                    except Exception as diag_exc:
                        logger.debug("STREAMSET_DIAG_FAILED: %s", diag_exc)
                batch_results = _parse_streamset_response(
                    payload, error_collector=error_info,
                )
                all_results.update(batch_results)
                await _CAPABILITY.mark_supported(mode)
                used_streamset = True
                logger.info(
                    "StreamSet %s batch of %d tags: %d results (points=%d)",
                    mode, len(batch), len(batch_results),
                    sum(len(v) for v in batch_results.values()),
                )
            except PiIntegrationError as exc:
                if _is_streamset_unsupported_error(exc):
                    logger.warning(
                        "StreamSet %s not supported (code=%s), falling back to individual",
                        mode, exc.code if hasattr(exc, "code") else "unknown"
                    )
                    await _CAPABILITY.mark_unsupported(mode)
                    return {}, total_requests, False
                if _should_not_fallback(exc):
                    raise
                logger.warning(
                    "StreamSet %s transient error (code=%s), falling back to individual",
                    mode, exc.code if hasattr(exc, "code") else "unknown"
                )
                return {}, total_requests, False

    if mode == "interpolated" and interval and error_info:
        failed_web_ids = [
            wid for wid in web_ids
            if wid in error_info and not all_results.get(wid)
        ]
        if failed_web_ids:
            logger.info(
                "Attempting windowed recovery for %d failed series (30d windows)",
                len(failed_web_ids),
            )
            recovered, recovery_errors = await _recover_failed_series(
                failed_web_ids,
                start_time,
                end_time,
                interval,
                max_count,
                provider,
                semaphore,
            )
            all_results.update(recovered)
            days_span = max(1, (end_time - start_time).days)
            windows_per_series = max(1, (days_span + _WINDOW_MAX_DAYS - 1) // _WINDOW_MAX_DAYS)
            total_requests += len(failed_web_ids) * windows_per_series
            for wid, errs in recovery_errors.items():
                if wid not in recovered:
                    logger.warning(
                        "Recovery fully failed for %s: %s",
                        _safe_mask_webid(wid),
                        "; ".join(errs),
                    )

    return all_results, total_requests, used_streamset


def build_web_ids_version(web_ids: Sequence[Optional[str]]) -> str:
    return "|".join(w or "" for w in web_ids)


def detect_missing_series(
    all_web_ids: Sequence[str],
    results: Dict[str, List[PiValue]],
) -> List[str]:
    return [wid for wid in all_web_ids if wid not in results]


# ---------------------------------------------------------------------------
# Fase 5.5: recorded exato, StreamSet ad hoc dentro de POST /batch
# ---------------------------------------------------------------------------


@dataclass
class RecordedBatchMetrics:
    strategy: str = "streamset-recorded-batch"
    streamset_used: bool = False
    batch_used: bool = False
    streamset_group_count: int = 0
    batch_count: int = 0
    batch_subrequest_count: int = 0
    individual_fallback_requests: int = 0
    initial_window_count: int = 1
    window_split_count: int = 0
    pi_http_requests: int = 0
    pi_points_received: int = 0
    retry_count: int = 0
    rate_limit_count: int = 0
    partial: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class _RecordedWork:
    key: str
    web_ids: Tuple[str, ...]
    start_time: datetime
    end_time: datetime
    depth: int = 0
    fallback: bool = False


@dataclass
class RecordedBatchResult:
    values: Dict[str, List[PiValue]]
    metrics: RecordedBatchMetrics
    errors: Dict[str, PiIntegrationError] = field(default_factory=dict)
    truncated_web_ids: set[str] = field(default_factory=set)


_BATCH_SEMAPHORE = asyncio.Semaphore(
    min(settings.pi_batch_max_concurrent, settings.pi_query_concurrency, 4)
)


def _iso_utc(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def build_recorded_resource(
    base_url: str,
    web_ids: Sequence[str],
    start_time: datetime,
    end_time: datetime,
    max_count: int,
    *,
    fallback: bool = False,
) -> str:
    """Build a Batch Resource without truncating or reordering WebIds."""
    if fallback:
        if len(web_ids) != 1:
            raise ValueError("Streams Recorded fallback requires exactly one WebId.")
        path = f"/streams/{web_ids[0]}/recorded"
        params = [
            ("startTime", _iso_utc(start_time)),
            ("endTime", _iso_utc(end_time)),
            ("boundaryType", "Inside"),
            ("maxCount", str(max_count)),
        ]
    else:
        path = "/streamsets/recorded"
        params = [("webId", wid) for wid in web_ids]
        params.extend([
            ("startTime", _iso_utc(start_time)),
            ("endTime", _iso_utc(end_time)),
            ("boundaryType", "Inside"),
            ("maxCount", str(max_count)),
        ])
    return base_url.rstrip("/") + path + "?" + urlencode(params)


def group_web_ids_for_recorded(
    base_url: str,
    web_ids: Sequence[str],
    start_time: datetime,
    end_time: datetime,
    max_count: int,
) -> List[Tuple[str, ...]]:
    """Respect both configured group size and Batch Resource URL size."""
    groups: List[Tuple[str, ...]] = []
    current: List[str] = []
    limit = settings.pi_streamset_recorded_max_webids
    max_chars = settings.pi_batch_resource_max_chars
    for web_id in web_ids:
        candidate = current + [web_id]
        resource = build_recorded_resource(
            base_url, candidate, start_time, end_time, max_count
        )
        if current and (len(candidate) > limit or len(resource) > max_chars):
            logger.info(
                "Recorded StreamSet group closed with %d WebIds (resource_chars=%d)",
                len(current),
                len(build_recorded_resource(base_url, current, start_time, end_time, max_count)),
            )
            groups.append(tuple(current))
            current = [web_id]
        else:
            current = candidate
        if len(build_recorded_resource(base_url, current, start_time, end_time, max_count)) > max_chars:
            raise PiInvalidResponseError(
                "Um WebId isolado excede o limite seguro da Resource do Batch."
            )
    if current:
        groups.append(tuple(current))
    return groups


def _content_json(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError as exc:
            raise PiInvalidResponseError("Content de subresposta Batch nao e JSON.") from exc
    return content


def _retry_after_seconds(headers: Any) -> Optional[float]:
    if not isinstance(headers, dict):
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(str(raw))
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


async def _cancel_aware_sleep(delay: float, cancel_check: Optional[Callable[[], Any]]) -> None:
    remaining = delay
    while remaining > 0:
        if cancel_check:
            await cancel_check()
        step = min(remaining, 0.25)
        await asyncio.sleep(step)
        remaining -= step


async def _post_batch(provider: Any, payload: Dict[str, dict], query_id: Optional[str]) -> Dict[str, Any]:
    async with _BATCH_SEMAPHORE:
        response = await provider._safe_request(
            "POST", "/batch", json=payload, query_id=query_id
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise PiInvalidResponseError("Resposta externa do Batch nao e JSON.") from exc
    if not isinstance(body, dict):
        raise PiInvalidResponseError("Resposta externa do Batch nao e um objeto.")
    return body


def _work_resource(provider: Any, work: _RecordedWork, max_count: int) -> str:
    return build_recorded_resource(
        provider.base_url,
        work.web_ids,
        work.start_time,
        work.end_time,
        max_count,
        fallback=work.fallback,
    )


async def fetch_recorded_streamsets_batch(
    web_ids: Sequence[str],
    start_time: datetime,
    end_time: datetime,
    provider: Any,
    *,
    query_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], Any]] = None,
) -> RecordedBatchResult:
    """Fetch all archived events through deterministic Batch waves.

    Saturated series alone move to child windows. Successful series are never
    repeated, and only proven boundary duplicates are removed by the caller.
    """
    metrics = RecordedBatchMetrics()
    values: Dict[str, List[PiValue]] = {wid: [] for wid in web_ids}
    errors: Dict[str, PiIntegrationError] = {}
    truncated_web_ids: set[str] = set()
    max_count = settings.pi_recorded_window_max_points
    groups = group_web_ids_for_recorded(
        provider.base_url, web_ids, start_time, end_time, max_count
    )
    metrics.streamset_group_count = len(groups)
    supported = await _CAPABILITY.is_supported("recorded")
    work: List[_RecordedWork] = []
    for group_index, group in enumerate(groups):
        if supported:
            work.append(_RecordedWork(f"group-{group_index:03d}-window-000", group, start_time, end_time))
        else:
            for series_index, wid in enumerate(group):
                work.append(_RecordedWork(f"group-{group_index:03d}-series-{series_index:03d}-window-000", (wid,), start_time, end_time, fallback=True))

    wave = 0
    while work:
        if cancel_check:
            await cancel_check()
        next_wave: List[_RecordedWork] = []
        async def send_batch(batch_items: List[_RecordedWork]) -> Tuple[List[_RecordedWork], Dict[str, Any]]:
            if cancel_check:
                await cancel_check()
            payload = {
                item.key: {"Method": "GET", "Resource": _work_resource(provider, item, max_count)}
                for item in batch_items
            }
            attempts = settings.pi_request_max_retries + 1
            for attempt in range(attempts):
                if cancel_check:
                    await cancel_check()
                if query_id:
                    from app.services.query_registry import get_query_registry
                    registry = get_query_registry()
                    await registry.check_cancelled(query_id)
                    current_requests = await registry.get_pi_request_count(query_id)
                    if current_requests >= settings.pi_visual_max_requests_per_query:
                        raise QueryLimitExceeded(
                            f"Limite de {settings.pi_visual_max_requests_per_query} requisicoes PI atingido."
                        )
                    await registry.increment_pi_requests(query_id)
                metrics.batch_count += 1
                metrics.pi_http_requests += 1
                metrics.batch_used = True
                metrics.batch_subrequest_count += len(payload)
                try:
                    return batch_items, await _post_batch(provider, payload, query_id)
                except PiRateLimitedError as exc:
                    metrics.rate_limit_count += 1
                    if attempt + 1 >= attempts:
                        raise
                    metrics.retry_count += 1
                    external_retry_after = _retry_after_seconds(
                        {"Retry-After": (exc.details or {}).get("retry_after")}
                        if isinstance(exc.details, dict) else None
                    )
                    await _cancel_aware_sleep(
                        external_retry_after if external_retry_after is not None
                        else min(2 ** attempt, 5) * random.uniform(0.5, 1.5),
                        cancel_check,
                    )
            raise PiUnavailableError("Batch nao retornou resposta.")

        batch_chunks = [
            work[offset : offset + settings.pi_batch_max_requests]
            for offset in range(0, len(work), settings.pi_batch_max_requests)
        ]
        sent_batches = await asyncio.gather(*(send_batch(items) for items in batch_chunks))
        for batch_items, response_body in sent_batches:
            for item in batch_items:
                sub = response_body.get(item.key)
                if not isinstance(sub, dict):
                    for wid in item.web_ids:
                        errors[wid] = PiInvalidResponseError("Subresposta Batch ausente.")
                    metrics.partial = True
                    continue
                status = int(sub.get("Status", sub.get("status", 0)) or 0)
                if status == 429:
                    metrics.rate_limit_count += 1
                    retry_count = item.depth
                    if retry_count < settings.pi_request_max_retries:
                        metrics.retry_count += 1
                        delay = _retry_after_seconds(sub.get("Headers") or sub.get("headers"))
                        await _cancel_aware_sleep(
                            delay if delay is not None else min(2 ** retry_count, 5) * random.uniform(0.5, 1.5),
                            cancel_check,
                        )
                        next_wave.append(_RecordedWork(item.key, item.web_ids, item.start_time, item.end_time, item.depth + 1, item.fallback))
                    else:
                        for wid in item.web_ids:
                            errors[wid] = PiRateLimitedError()
                        metrics.partial = True
                    continue
                if not item.fallback and status in _UNSUPPORTED_CODES:
                    await _CAPABILITY.mark_unsupported("recorded")
                    for series_index, wid in enumerate(item.web_ids):
                        metrics.individual_fallback_requests += 1
                        next_wave.append(_RecordedWork(f"{item.key}-fallback-{series_index:03d}", (wid,), item.start_time, item.end_time, fallback=True))
                    continue
                if status < 200 or status >= 300:
                    error = PiAuthError() if status in (401, 403) else PiInvalidResponseError(
                        f"Subresposta Batch retornou status {status}."
                    )
                    for wid in item.web_ids:
                        errors[wid] = error
                    metrics.partial = True
                    continue

                content = _content_json(sub.get("Content", sub.get("content")))
                if item.fallback:
                    raw_items = content.get("Items") if isinstance(content, dict) else None
                    parsed = {item.web_ids[0]: [_parse_value_entry(entry) for entry in (raw_items or []) if isinstance(entry, dict)]}
                else:
                    parsed = _parse_streamset_response(content)
                    metrics.streamset_used = True
                    await _CAPABILITY.mark_supported("recorded")

                missing = detect_missing_series(item.web_ids, parsed)
                for missing_index, wid in enumerate(missing):
                    metrics.individual_fallback_requests += 1
                    next_wave.append(_RecordedWork(f"{item.key}-missing-{missing_index:03d}", (wid,), item.start_time, item.end_time, fallback=True))

                for wid, series_values in parsed.items():
                    if wid not in item.web_ids:
                        continue
                    metrics.pi_points_received += len(series_values)
                    if len(series_values) >= max_count:
                        seconds = (item.end_time - item.start_time).total_seconds()
                        if seconds <= settings.pi_recorded_window_min_seconds:
                            values[wid].extend(series_values)
                            truncated_web_ids.add(wid)
                            metrics.partial = True
                            metrics.truncated = True
                            continue
                        midpoint = item.start_time + (item.end_time - item.start_time) / 2
                        metrics.window_split_count += 1
                        child_base = f"{item.key}-split-{wave:03d}-{list(item.web_ids).index(wid):03d}"
                        next_wave.extend([
                            _RecordedWork(child_base + "-left", (wid,), item.start_time, midpoint, fallback=item.fallback),
                            _RecordedWork(child_base + "-right", (wid,), midpoint, item.end_time, fallback=item.fallback),
                        ])
                    else:
                        values[wid].extend(series_values)
        work = next_wave
        wave += 1

    if not metrics.streamset_used:
        metrics.strategy = "batch-recorded-fallback"
    logger.info(
        "recorded_batch_completed strategy=%s tag_count=%d streamset_group_count=%d "
        "batch_count=%d batch_subrequest_count=%d window_split_count=%d "
        "pi_http_requests=%d points_received=%d retry_count=%d rate_limit_count=%d "
        "complete=%s partial=%s truncated=%s",
        metrics.strategy,
        len(web_ids),
        metrics.streamset_group_count,
        metrics.batch_count,
        metrics.batch_subrequest_count,
        metrics.window_split_count,
        metrics.pi_http_requests,
        metrics.pi_points_received,
        metrics.retry_count,
        metrics.rate_limit_count,
        not metrics.partial,
        metrics.partial,
        metrics.truncated,
    )
    return RecordedBatchResult(
        values=values,
        metrics=metrics,
        errors=errors,
        truncated_web_ids=truncated_web_ids,
    )
