from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import pandas as pd

from .fetch import FetchResult

_MEMBER_RE = re.compile(r"^(?P<variable>.+)_member(?P<member>\d+)$")


def _payload_objects(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def section_to_frame(payload: dict[str, Any], section: str, source: str, model: str | None = None) -> pd.DataFrame:
    block = payload.get(section)
    if not isinstance(block, dict) or "time" not in block:
        return pd.DataFrame()

    times = block.get("time", [])
    data: dict[str, Any] = {"time": times}
    n = len(times)
    for key, values in block.items():
        if key == "time" or not isinstance(values, list):
            continue
        if len(values) == n:
            data[key] = values

    frame = pd.DataFrame(data)
    frame.insert(1, "source", source)
    frame.insert(2, "model", model or _model_name(payload))
    frame["timezone"] = payload.get("timezone")
    frame["latitude_grid"] = payload.get("latitude")
    frame["longitude_grid"] = payload.get("longitude")
    frame["elevation_m"] = payload.get("elevation")
    frame["generationtime_ms"] = payload.get("generationtime_ms")
    return frame


def _model_name(payload: dict[str, Any]) -> str | None:
    # Raw JSON often has no human-readable model key when one model is explicitly requested.
    # The caller-provided source name is therefore the source of truth.
    model = payload.get("model")
    return str(model) if model is not None else None


def normalize_deterministic(results: Iterable[FetchResult]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hourly_frames: list[pd.DataFrame] = []
    daily_frames: list[pd.DataFrame] = []
    current_frames: list[pd.DataFrame] = []

    for result in results:
        if not result.name.startswith("deterministic__") or result.payload is None:
            continue
        model = result.name.split("__", 1)[1]
        for payload in _payload_objects(result.payload):
            hourly = section_to_frame(payload, "hourly", "deterministic", model)
            daily = section_to_frame(payload, "daily", "deterministic", model)
            if not hourly.empty:
                hourly_frames.append(hourly)
            if not daily.empty:
                daily_frames.append(daily)
            current = payload.get("current")
            if isinstance(current, dict) and "time" in current:
                row = dict(current)
                row.update(
                    {
                        "source": "current",
                        "model": model,
                        "timezone": payload.get("timezone"),
                        "latitude_grid": payload.get("latitude"),
                        "longitude_grid": payload.get("longitude"),
                        "elevation_m": payload.get("elevation"),
                    }
                )
                current_frames.append(pd.DataFrame([row]))

    return (
        pd.concat(hourly_frames, ignore_index=True, sort=False) if hourly_frames else pd.DataFrame(),
        pd.concat(daily_frames, ignore_index=True, sort=False) if daily_frames else pd.DataFrame(),
        pd.concat(current_frames, ignore_index=True, sort=False) if current_frames else pd.DataFrame(),
    )


def normalize_hrrr_15min(results: Iterable[FetchResult]) -> pd.DataFrame:
    for result in results:
        if result.name != "hrrr_15min" or result.payload is None:
            continue
        frames = []
        for payload in _payload_objects(result.payload):
            frame = section_to_frame(payload, "minutely_15", "hrrr_15min", "ncep_hrrr_conus")
            if not frame.empty:
                frames.append(frame)
        if frames:
            return pd.concat(frames, ignore_index=True, sort=False)
    return pd.DataFrame()


def normalize_ensemble_members(results: Iterable[FetchResult]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for result in results:
        if not result.name.startswith("ensemble_members__") or result.payload is None:
            continue
        model = result.name.split("__", 1)[1]
        for payload in _payload_objects(result.payload):
            hourly = payload.get("hourly")
            if not isinstance(hourly, dict) or "time" not in hourly:
                continue
            times = hourly["time"]
            n = len(times)
            records: dict[tuple[str, int], dict[str, Any]] = {}
            for key, values in hourly.items():
                if key == "time" or not isinstance(values, list) or len(values) != n:
                    continue
                match = _MEMBER_RE.match(key)
                if match:
                    variable = match.group("variable")
                    member = int(match.group("member"))
                else:
                    # Open-Meteo's unsuffixed ensemble field is the control member.
                    variable = key
                    member = 0
                records.setdefault((variable, member), {})["values"] = values

            members = sorted({member for _, member in records})
            variables = sorted({variable for variable, _ in records})
            for member in members:
                data: dict[str, Any] = {"time": times}
                for variable in variables:
                    entry = records.get((variable, member))
                    if entry:
                        data[variable] = entry["values"]
                frame = pd.DataFrame(data)
                frame.insert(1, "source", "ensemble_member")
                frame.insert(2, "model", model)
                frame.insert(3, "member", member)
                frame["timezone"] = payload.get("timezone")
                frames.append(frame)

    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def normalize_ensemble_mean(results: Iterable[FetchResult]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for result in results:
        if not result.name.startswith("ensemble_mean__") or result.payload is None:
            continue
        model = result.name.split("__", 1)[1]
        for payload in _payload_objects(result.payload):
            frame = section_to_frame(payload, "hourly", "ensemble_mean", model)
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def normalize_air_quality(results: Iterable[FetchResult]) -> pd.DataFrame:
    for result in results:
        if result.name != "air_quality" or result.payload is None:
            continue
        frames = []
        for payload in _payload_objects(result.payload):
            frame = section_to_frame(payload, "hourly", "air_quality", "cams_global")
            if not frame.empty:
                frames.append(frame)
        if frames:
            return pd.concat(frames, ignore_index=True, sort=False)
    return pd.DataFrame()


def normalize_profiles(results: Iterable[FetchResult]) -> pd.DataFrame:
    """Normalize separately fetched deep pressure-level profiles."""
    frames: list[pd.DataFrame] = []
    for result in results:
        if not result.name.startswith("profile__") or result.payload is None:
            continue
        model = result.name.split("__", 1)[1]
        for payload in _payload_objects(result.payload):
            frame = section_to_frame(payload, "hourly", "pressure_profile", model)
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
