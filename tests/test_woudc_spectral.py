"""Property tests for the WOUDC spectral validation script's parsers.

`scripts/validate_woudc_spectral.py` ingests third-party Brewer scans from the
network and feeds a published validation report, so its parser and its channel
integration are trust boundaries. Nothing else in the suite touches them.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import math
import urllib.request
from pathlib import Path
from typing import Protocol, Self, cast

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "data" / "research" / "woudc" / "brewer_saskatoon_19930127_scan0.csv"
SUMMARY_KEYS = ["Date", "Time", "ZenAngle", "IntCIE", "O3", "TempC"]


class _Woudc(Protocol):
    """The slice of the script module these tests exercise."""

    UNIT_SCALES: dict[str, float]

    def parse_brewer_csv(self, text: str) -> list[dict[str, object]]: ...

    def integrate_channels(
        self, waves: list[float], irr: list[float], *, unit_scale: float = ...
    ) -> dict[str, float]: ...

    def find_scans(
        self, station: str, date_from: str, date_to: str, limit: int = ..., page: int = ...
    ) -> list[tuple[str, str]]: ...

    def main(self, argv: list[str] | None = ...) -> None: ...


def _load_script() -> object:
    spec = importlib.util.spec_from_file_location(
        "validate_woudc_spectral", REPO / "scripts" / "validate_woudc_spectral.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


woudc = cast(_Woudc, _load_script())


def _channels(scan: dict[str, object]) -> tuple[list[float], list[float]]:
    waves = cast("list[float]", scan["wavelength_nm"])
    irr = cast("list[float]", scan["irradiance"])
    return waves, irr


def brewer_text(values: list[str], rows: list[tuple[float, float]]) -> str:
    """A real-shaped WOUDC Spectral_1.0 file: summary, #GLOBAL header, rows."""
    lines = [
        "#GLOBAL_SUMMARY",
        ",".join(SUMMARY_KEYS[: len(values)]),
        ",".join(values),
        "#GLOBAL",
        "Wavelength,S-Irradiance,Time",
    ]
    lines += [f"{w:.4f},{v:.6e}" for w, v in rows]
    return "\n".join(lines) + "\n"


summaries = st.lists(
    st.text(alphabet="0123456789.-", min_size=1, max_size=6), min_size=1, max_size=6
)
spec_rows = st.lists(
    st.tuples(
        st.floats(min_value=280, max_value=400, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False),
    ),
    min_size=0,
    max_size=8,
)


@given(summary=summaries, rows=spec_rows)
@settings(max_examples=200, deadline=None)
def test_one_scan_round_trips(summary: list[str], rows: list[tuple[float, float]]) -> None:
    scans = woudc.parse_brewer_csv(brewer_text(summary, rows))
    assert len(scans) == (1 if rows else 0), (len(scans), rows)
    for scan in scans:
        waves, irr = _channels(scan)
        assert len(waves) == len(irr) == len(rows)
        assert all(math.isfinite(x) for x in waves)
        assert all(math.isfinite(x) for x in irr)
        parsed = cast("dict[str, str]", scan["summary"])
        assert len(parsed) == len(summary)


@given(blocks=st.lists(st.tuples(summaries, spec_rows), min_size=1, max_size=5))
@settings(max_examples=150, deadline=None)
def test_multi_scan_count_matches_blocks(
    blocks: list[tuple[list[str], list[tuple[float, float]]]],
) -> None:
    text = "".join(brewer_text(values, rows) for values, rows in blocks)
    assert len(woudc.parse_brewer_csv(text)) == sum(1 for _, rows in blocks if rows)


@given(text=st.text(max_size=400))
@settings(max_examples=300, deadline=None)
def test_parser_never_raises(text: str) -> None:
    for scan in woudc.parse_brewer_csv(text):
        waves, irr = _channels(scan)
        assert len(waves) == len(irr)


@given(
    rows=st.lists(
        st.tuples(
            st.floats(min_value=280, max_value=400, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
        ),
        min_size=50,
        max_size=60,
    ),
    scale=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
)
@settings(max_examples=50, deadline=None)
def test_integrate_channels_is_scale_equivariant(
    rows: list[tuple[float, float]], scale: float
) -> None:
    """A spectrum's channels must scale with the spectrum.

    This is the regression for the old magnitude sniff: `sum(UVA) > 500 ->
    divide by 1000` made the reported channels a function of brightness, so two
    otherwise identical spectra on opposite sides of the threshold differed by
    1000x (UVI 74.6 vs 0.08). Units are an argument now, so no threshold exists
    to straddle.
    """
    waves = [r[0] for r in rows]
    irr = [r[1] for r in rows]
    base = woudc.integrate_channels(waves, irr)
    scaled = woudc.integrate_channels(waves, [v * scale for v in irr])
    assert base
    for key, value in base.items():
        assert math.isclose(value * scale, scaled[key], rel_tol=1e-9, abs_tol=1e-12), key


def test_milliwatt_files_are_read_at_their_declared_scale() -> None:
    """The same file read as mW/m2/nm is exactly 1000x smaller than as W/m2/nm."""
    scan = woudc.parse_brewer_csv(FIXTURE.read_text(encoding="utf-8"))[0]
    waves, irr = _channels(scan)
    w_units = woudc.integrate_channels(waves, irr)
    mw_units = woudc.integrate_channels(
        waves, irr, unit_scale=woudc.UNIT_SCALES["mW/m2/nm"]
    )
    for key, value in w_units.items():
        assert math.isclose(value / 1000.0, mw_units[key], rel_tol=1e-12), key
    # The default is the unit WOUDC actually ships, so the flag is opt-in.
    assert woudc.UNIT_SCALES["W/m2/nm"] == 1.0


def test_pinned_fixture_agrees_with_its_own_erythemal_integral() -> None:
    """Two conventions, one spectrum - and the file tells us which is which.

    WOUDC's own IntCIE column is the plain SUM over the reported samples, not the
    integral: on a 0.5 nm grid the sum is exactly 2x the trapezoid, and the
    committed fixture's mean step is 0.54 nm (it is truncated at 325 nm), so the
    ratio there is 1.85. A physical erythemal irradiance is the integral, so our
    integral must equal IntCIE x the grid step. That relation pins the unit and
    the integration convention in one assertion: a return to summing samples, or
    a wrong unit scale, breaks it by a factor of ~2.
    """
    scan = woudc.parse_brewer_csv(FIXTURE.read_text(encoding="utf-8"))[0]
    summary = cast("dict[str, str]", scan["summary"])
    waves, irr = _channels(scan)
    channels = woudc.integrate_channels(waves, irr)

    declared_sum = float(summary["IntCIE"]) * 1e-3  # mW/m2 -> W/m2, sum convention
    gaps = sorted(b - a for a, b in itertools.pairwise(waves))
    step = gaps[len(gaps) // 2]
    assert declared_sum > 0 and step > 0
    ratio = channels["e_ery"] / (declared_sum * step)
    assert abs(ratio - 1.0) < 0.15, (channels["e_ery"], declared_sum, step, ratio)


def _api(days: list[str]):
    payload = {
        "features": [
            {
                "properties": {
                    "url": f"http://example.invalid/{d.replace('-', '')}.csv",
                    "timestamp_date": f"{d}T12:00:00Z",
                    "platform_name": "Station",
                }
            }
            for d in days
        ]
    }

    class _Response:
        def read(self) -> bytes:
            return json.dumps(payload).encode()

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    def _urlopen(url: str, timeout: int | None = None, context: object = None) -> _Response:
        _ = (url, timeout, context)
        return _Response()

    return _urlopen


def _dates(count: int) -> list[str]:
    import datetime as dt

    start = dt.date(2023, 1, 1)
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(count)]


@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    n=st.integers(min_value=1, max_value=90),
    limit=st.integers(min_value=0, max_value=30),
    lo=st.integers(min_value=0, max_value=50),
    span=st.integers(min_value=0, max_value=89),
)
def test_find_scans_stays_in_window_and_samples_distinctly(
    monkeypatch: pytest.MonkeyPatch, n: int, limit: int, lo: int, span: int
) -> None:
    """The API 500s on date filters, so the window is applied client-side.

    That makes these invariants load-bearing: every returned scan must fall
    inside the window, and the even-stride subsample must not repeat a scan
    (which would silently weight one date twice in the report).
    """
    days = _dates(n)
    monkeypatch.setattr(urllib.request, "urlopen", _api(days))
    lo = lo % n
    date_from, date_to = days[lo], days[min(n - 1, lo + span)]
    got = woudc.find_scans("Station", date_from, date_to, limit=limit)
    in_window = [d for d in days if date_from <= d <= date_to]
    if limit <= 0 or not in_window:
        assert got == []
        return
    assert len(got) == min(limit, len(in_window))
    urls = [url for _, url in got]
    assert len(set(urls)) == len(urls)
    for _, url in got:
        day = url.rsplit("/", 1)[1][:8]
        assert date_from <= f"{day[:4]}-{day[4:6]}-{day[6:]}" <= date_to
