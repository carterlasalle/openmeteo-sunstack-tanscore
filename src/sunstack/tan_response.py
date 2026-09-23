"""TanResponse interface (future delayed-pigmentation response model).

TanDose answers: how much melanogenic-effective radiation accumulated?
TanResponse will answer: how much delayed visible pigmentation is expected
to develop from this exposure history?

Status: INTERFACE ONLY. No fitted response model ships in production because
no candidate has yet beaten a simple cumulative-dose baseline on held-out
study data (required gate). Repeated exposure NEVER modifies physical
TanDose; adaptation/saturation/recovery belong exclusively here.

Relevant human datasets to encode before fitting (aggregate observations
only; never fabricate individual-subject data):
  Miller et al. 2008 (PMID 18616777), Ravnbak & Wulf 2007 (PMID 17256147),
  Ravnbak et al. 2009 (PMID 19688146), Keong et al. 1990 (PMID 2103131),
  Wolber et al. 2008 (PMID 18627527), Ravnbak et al. 2010 (PMID 20584251),
  MITF timer mechanistic prior only (PMID 30401431; do NOT hard-code 48 h).
"""
from __future__ import annotations

from dataclasses import dataclass, field

TAN_RESPONSE_MODEL_VERSION = "none-v1"
TAN_RESPONSE_STATUS = "interface-only"


@dataclass(frozen=True)
class ExposureEpisode:
    dose_melanogenic_j_m2: float
    interval_since_previous_s: float | None = None
    pigment_baseline: float | None = None


@dataclass
class ExposureHistory:
    episodes: list[ExposureEpisode] = field(default_factory=list)

    @property
    def cumulative_tandose_j_m2(self) -> float:
        return float(sum(e.dose_melanogenic_j_m2 for e in self.episodes))

    def add_episode(self, dose_melanogenic_j_m2: float,
                    interval_since_previous_s: float | None = None,
                    pigment_baseline: float | None = None) -> None:
        if dose_melanogenic_j_m2 < 0:
            raise ValueError("episode dose must be non-negative")
        self.episodes.append(ExposureEpisode(
            dose_melanogenic_j_m2=float(dose_melanogenic_j_m2),
            interval_since_previous_s=interval_since_previous_s,
            pigment_baseline=pigment_baseline,
        ))


class TanResponseModel:
    """Abstract response-model interface. Production returns cumulative dose."""

    model_version = TAN_RESPONSE_MODEL_VERSION

    def predict(self, history: ExposureHistory) -> dict[str, object]:
        # Baseline: cumulative physical dose with no biological transformation.
        # Any future fitted model (Hill/Emax, exponential saturation, delayed
        # kernels, interval/recovery terms with cross-validation/AIC and
        # bootstrap uncertainty) must beat this on held-out study data first.
        return {
            "tan_response_model_version": self.model_version,
            "tan_response_status": TAN_RESPONSE_STATUS,
            "cumulative_tandose_j_m2": history.cumulative_tandose_j_m2,
            "predicted_response": None,
            "note": (
                "No validated response model shipped; exposing physical "
                "TanDose only. See tan_response.py docstring for the gate."
            ),
        }
