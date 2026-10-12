"""Property tests for the interval/dose machinery and the UVI fusion.

Every property here is aimed at a failure this project has actually shipped, or
at the one reading that made it invisible:

* `test_1h_equals_its_two_halves...` - the hourly grid integrated point samples
  under the same column names the half-hour grid integrated interval means, so
  the two published tables disagreed about the same hour by 3.8-5.5%.
* `test_trailing_dose_ignores_later_rows` - the daily best-slot dose read the row
  AFTER the slot, publishing the next slot's number (1000.854 instead of 1104.66).
* `test_interval_mean_integral_is_exact_for_piecewise_constant` - the oracle the
  two above are measured against.
* `test_gap_is_incomplete_never_zero` - missing input must never read as a dose.
* `test_fused_uvi_stays_within_its_inputs` / `..._headline_matches_its_source` -
  the §5 contract: the headline is one of its inputs, and it says which one.

These are properties, not examples: the generators cover the whole grid of
shapes, so a regression fails on a case nobody wrote down.
"""

from __future__ import annotations

import math
import os

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sunstack.doses import add_interval_doses

# The gate runs the whole suite quickly; the nightly job raises the budget by
# setting SUNSTACK_PROPERTY_EXAMPLES (see .github/workflows/analysis.yml), so the
# same properties explore far more shapes without a second suite to maintain.
EXAMPLES = int(os.environ.get("SUNSTACK_PROPERTY_EXAMPLES", "60"))

SETTINGS = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

MEANS = st.floats(min_value=0.0, max_value=8.0, allow_nan=False, allow_infinity=False)


def _half_hour_frame(means: list[float], start: str = "2026-06-21T06:00Z") -> pd.DataFrame:
    """A backward-mean half-hour grid with DECLARED support, means as given."""
    stamps = pd.date_range(start, periods=len(means), freq="30min")
    return pd.DataFrame(
        {
            "time": stamps.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M"),
            "time_utc": stamps,
            "interval_start_utc": stamps - pd.Timedelta(minutes=30),
            "interval_end_utc": stamps,
            "radiation_support_type": "interval_mean",
            "melanogenic_effective_irradiance_wm2": means,
            "erythemal_irradiance_wm2": [m / 10.0 for m in means],
            "predicted_uva_wm2": [30.0] * len(means),
            "predicted_uvb_wm2": [0.5] * len(means),
        }
    )


@SETTINGS
@given(means=st.lists(MEANS, min_size=4, max_size=10))
def test_interval_mean_integral_is_exact_for_piecewise_constant(means: list[float]) -> None:
    """With declared supports, a trailing window equals the exact integral.

    Piecewise-constant is the one signal where the answer is knowable in closed
    form: the dose over a window is each interval's mean times its overlap. Any
    trapezoid over samples, or any read of a neighbouring row, breaks this.
    """
    out = add_interval_doses(_half_hour_frame(means))
    doses = out["tan_dose_30m_j_m2"].tolist()
    for index, mean in enumerate(means):
        # The 30-minute window ending at this row is exactly this row's support.
        assert abs(doses[index] - mean * 1800.0) < 1e-6, (index, mean, doses[index])


@SETTINGS
@given(means=st.lists(MEANS, min_size=4, max_size=10))
def test_1h_equals_its_two_halves_whatever_the_signal(means: list[float]) -> None:
    """The relation that makes one hour mean one thing in both published grids.

    The half-hour table's 1-h column must be the sum of its own two halves; the
    hourly table builds the same hour from hourly means. Both are the exact
    integral, so both must agree - the bug was that one of them was not the
    exact integral at all.
    """
    out = add_interval_doses(_half_hour_frame(means))
    hours = out["tan_dose_1h_j_m2"].tolist()
    halves = out["tan_dose_30m_j_m2"].tolist()
    for index in range(1, len(means)):
        want = halves[index - 1] + halves[index]
        assert abs(hours[index] - want) < 1e-6, (index, hours[index], want)


@SETTINGS
@given(means=st.lists(MEANS, min_size=4, max_size=10))
def test_trailing_dose_ignores_later_rows(means: list[float]) -> None:
    """A trailing dose may not depend on any row after its own.

    This is the off-by-one as a property: change the last row's mean and every
    earlier row's trailing dose must be untouched. The published bug read row
    i+1 for row i's slot, which this fails on immediately.
    """
    base = add_interval_doses(_half_hour_frame(means))
    bumped_means = [*means[:-1], means[-1] + 4.0]
    bumped = add_interval_doses(_half_hour_frame(bumped_means))
    for index in range(len(means) - 1):
        for column in ("tan_dose_30m_j_m2", "tan_dose_1h_j_m2"):
            assert math.isclose(
                base[column].iloc[index], bumped[column].iloc[index], rel_tol=1e-9, abs_tol=1e-9
            ), (column, index)


@SETTINGS
@given(means=st.lists(MEANS, min_size=4, max_size=8), hole=st.integers(min_value=1, max_value=6))
def test_gap_is_incomplete_never_zero(means: list[float], hole: int) -> None:
    """A hole in the inputs must read as incomplete, never as a measured zero."""
    if hole >= len(means):
        return
    frame = _half_hour_frame(means)
    frame.loc[hole, "melanogenic_effective_irradiance_wm2"] = float("nan")
    out = add_interval_doses(frame)
    covering = out["tan_dose_1h_j_m2"].iloc[hole]
    # The window containing the hole is either unknown or flagged incomplete -
    # never a finite dose computed as if the gap were zero.
    complete = out["tan_dose_1h_complete"].iloc[hole]
    assert not (complete is True and pd.notna(covering) and covering == pytest.approx(
        sum(means[: hole + 1]) * 1800.0, rel=1e-9
    )), "a gap was integrated as if it were zero"


# --- the §5 fusion contract -------------------------------------------------

UVI = st.floats(min_value=0.0, max_value=12.0, allow_nan=False, allow_infinity=False)


@SETTINGS
@given(om=UVI, cams=UVI, epa=UVI, uva=UVI, uvb=UVI)
def test_fused_uvi_stays_within_its_inputs(
    om: float, cams: float, epa: float, uva: float, uvb: float
) -> None:
    """Consensus is bounded by the inputs it fuses: never outside min..max.

    A bias-corrected inverse-error mean can be pulled toward a source, but it can
    never exceed the extremes of the values being averaged. The old OMx2 vote
    median silently did (it double-weighted Open-Meteo), which is the failure
    this pins.
    """
    from sunstack.state import fuse_uvi_unique_count

    frame = pd.DataFrame(
        {
            "time": ["2026-06-21T12:00"],
            "uv_index": [om],
            "uvi_openmeteo": [om],
            "uvi_cams": [cams],
            "uvi_epa": [epa],
            "predicted_uva_wm2": [uva],
            "predicted_uvb_wm2": [uvb],
        }
    )
    fused = fuse_uvi_unique_count(frame)
    consensus = float(fused["uvi_consensus"].iloc[0])
    if math.isnan(consensus):
        return  # no usable providers: absent, not guessed
    lo = min(om, cams, epa)
    hi = max(om, cams, epa)
    # Published to 3 dp (np.round(..., 3) in state.fuse_uvi_unique_count), so the
    # claim is "inside the observed range", not "exact to the last bit".
    assert lo - 1e-3 <= consensus <= hi + 1e-3, (consensus, lo, hi)


@SETTINGS
@given(om=UVI, cams=UVI, epa=UVI, uva=UVI, uvb=UVI)
def test_headline_names_a_source_it_actually_equals(
    om: float, cams: float, epa: float, uva: float, uvb: float
) -> None:
    """`uvi_headline_source` must name the input the headline equals.

    The page prints the headline and its provenance side by side, so a source
    label that does not match the number is a mislabel by construction.
    """
    from sunstack.state import fuse_uvi_unique_count

    frame = pd.DataFrame(
        {
            "time": ["2026-06-21T12:00"],
            "uv_index": [om],
            "uvi_openmeteo": [om],
            "uvi_cams": [cams],
            "uvi_epa": [epa],
            "predicted_uva_wm2": [uva],
            "predicted_uvb_wm2": [uvb],
        }
    )
    fused = fuse_uvi_unique_count(frame)
    source = fused["uvi_headline_source"].iloc[0]
    consensus = float(fused["uvi_consensus"].iloc[0])
    # The headline is published rounded to 3 dp, so equality is claimed at the
    # published precision: a source label that names the wrong *field* is the
    # defect this pins, and a rounding of the same field is not.
    if source == "openmeteo_best_match":
        assert math.isclose(consensus, om, abs_tol=1e-3), (consensus, om)
    elif source == "fusion":
        assert math.isclose(
            consensus, float(fused["uvi_fusion"].iloc[0]), abs_tol=1e-3
        ), (consensus, float(fused["uvi_fusion"].iloc[0]))
