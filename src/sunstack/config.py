from __future__ import annotations

import os
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

LATITUDE = float(os.getenv("SUNSTACK_LAT", "41.703293"))
LONGITUDE = float(os.getenv("SUNSTACK_LON", "-86.238292"))
TIMEZONE = os.getenv("SUNSTACK_TZ", "America/Indiana/Indianapolis")
FORECAST_DAYS = int(os.getenv("SUNSTACK_FORECAST_DAYS", "14"))
AIR_QUALITY_DAYS = int(os.getenv("SUNSTACK_AIR_QUALITY_DAYS", "7"))
HRRR_15MIN_STEPS = int(os.getenv("SUNSTACK_HRRR_15MIN_STEPS", "72"))

# Absolute score is intentionally NOT local-normalized. These are reference anchors
# for unusually strong natural terrestrial UV, not local South Bend maxima.
ABSOLUTE_UVI_REFERENCE = 20.0
ABSOLUTE_UVA_REFERENCE_WM2 = 60.0
ABSOLUTE_TAN_WEIGHTS = {"uvi": 0.55, "uva": 0.30, "interaction": 0.15}
LOCAL_DOY_WINDOW_DAYS = 21
LOCAL_SOLAR_ELEVATION_WINDOW_DEG = 7.5
SKIN_TILT_DEG = float(os.getenv("SUNSTACK_SKIN_TILT_DEG", "0"))
SKIN_AZIMUTH_DEG = float(os.getenv("SUNSTACK_SKIN_AZIMUTH_DEG", "180"))

# Outdoor opportunity / usability. These do NOT change physical TanScore.
MIN_TAN_TEMP_F = float(os.getenv("SUNSTACK_MIN_TAN_TEMP_F", "50"))
COMFORTABLE_TAN_TEMP_F = float(os.getenv("SUNSTACK_COMFORTABLE_TAN_TEMP_F", "68"))
HEAT_WARNING_TEMP_F = float(os.getenv("SUNSTACK_HEAT_WARNING_TEMP_F", "100"))
MAX_TAN_TEMP_F = float(os.getenv("SUNSTACK_MAX_TAN_TEMP_F", "110"))
ACTIVE_PRECIP_IN_THRESHOLD = float(os.getenv("SUNSTACK_ACTIVE_PRECIP_IN_THRESHOLD", "0.001"))
ACTIVE_SNOW_IN_THRESHOLD = float(os.getenv("SUNSTACK_ACTIVE_SNOW_IN_THRESHOLD", "0.001"))
PRECIP_PROBABILITY_PENALTY_MAX = float(os.getenv("SUNSTACK_PRECIP_PROBABILITY_PENALTY_MAX", "0.55"))
WIND_WARNING_MPH = float(os.getenv("SUNSTACK_WIND_WARNING_MPH", "25"))
WIND_STRONG_MPH = float(os.getenv("SUNSTACK_WIND_STRONG_MPH", "35"))
OVERALL_SCORE_WEIGHTS = {"absolute": 0.60, "local": 0.15, "atmosphere": 0.10, "confidence": 0.15}
OVERALL_ABSOLUTE_HEADROOM = float(os.getenv("SUNSTACK_OVERALL_ABSOLUTE_HEADROOM", "20"))
STRICT_DEFAULT = os.getenv("SUNSTACK_STRICT", "1").strip().lower() not in {"0", "false", "no"}
REQUIRE_DIRECT_CAMS = os.getenv("SUNSTACK_REQUIRE_DIRECT_CAMS", "1").strip().lower() not in {"0", "false", "no"}
UI_HOST = os.getenv("SUNSTACK_UI_HOST", "127.0.0.1")
UI_PORT = int(os.getenv("SUNSTACK_UI_PORT", "8765"))

# Historical bootstrap. NASA POWER UV begins in 2001. POWER can lag NRT by months,
# so default to 120 days behind today; unavailable tail years are skipped cleanly.
NASA_POWER_START = date(2001, 1, 1)
NASA_POWER_END = date.today() - timedelta(days=120)
OPENMETEO_HISTORY_START = date(2022, 1, 1)
OPENMETEO_HISTORY_END = date.today() - timedelta(days=2)
OPENMETEO_PREVIOUS_RUNS_DAYS = int(os.getenv("SUNSTACK_PREVIOUS_RUNS_DAYS", "1000"))
CAMS_EAC4_START_YEAR = int(os.getenv("SUNSTACK_CAMS_EAC4_START_YEAR", "2003"))
CAMS_EAC4_END_YEAR = int(os.getenv("SUNSTACK_CAMS_EAC4_END_YEAR", "2025"))
CAMS_REQUEST_TIMEOUT_S = int(os.getenv("SUNSTACK_CAMS_TIMEOUT_S", "1800"))
CAMS_EAC4_WORKERS = int(os.getenv("SUNSTACK_CAMS_WORKERS", "3"))

DETERMINISTIC_MODELS = [
    "best_match",
    "ncep_hrrr_conus",
    "ncep_nbm_conus",
    "ncep_nam_conus",
    "ncep_gfs_global",
    "ncep_aigfs025",
    "ecmwf_ifs",
    "ecmwf_aifs025_single",
    "icon_seamless",
    "cmc_gem_seamless",
    "gem_regional",
    "gem_hrdps_continental",
    "ukmo_seamless",
    "bom_access_global",
    "cma_grapes_global",
]

ENSEMBLE_MEMBER_MODELS = [
    "ncep_gefs025",
    "ncep_aigefs025",
    "ecmwf_ifs025_ensemble",
    "ecmwf_aifs025_ensemble",
]

ENSEMBLE_MEAN_MODELS = [
    "ncep_gefs025_ensemble_mean",
    "ecmwf_ifs025_ensemble_mean",
    "ecmwf_aifs025_ensemble_mean",
    "ncep_aigefs025_ensemble_mean",
    "ncep_hgefs025_ensemble_mean",
    "cmc_gem_geps_ensemble_mean",
    "bom_access_global_ensemble_mean",
    "ukmo_global_ensemble_mean_20km",
    "google_weathernext2_ensemble_mean",
]

HOURLY_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "apparent_temperature", "wet_bulb_temperature_2m",
    "pressure_msl", "surface_pressure", "visibility", "weather_code",
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "precipitation_probability", "precipitation", "rain", "showers", "snowfall",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "uv_index", "uv_index_clear_sky", "sunshine_duration", "is_day",
    "cape", "lifted_index", "convective_inhibition", "freezing_level_height",
    "boundary_layer_height", "total_column_integrated_water_vapour",
    "evapotranspiration", "et0_fao_evapotranspiration", "vapour_pressure_deficit",
    "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "direct_normal_irradiance", "terrestrial_radiation",
    "shortwave_radiation_instant", "direct_radiation_instant",
    "diffuse_radiation_instant", "direct_normal_irradiance_instant",
    "terrestrial_radiation_instant",
    "relative_humidity_925hPa", "relative_humidity_850hPa",
    "relative_humidity_700hPa", "relative_humidity_500hPa", "relative_humidity_300hPa",
    "cloud_cover_925hPa", "cloud_cover_850hPa", "cloud_cover_700hPa",
    "cloud_cover_500hPa", "cloud_cover_300hPa",
    "geopotential_height_925hPa", "geopotential_height_850hPa",
    "geopotential_height_700hPa", "geopotential_height_500hPa",
    "geopotential_height_300hPa",
]

# Deep profile is fetched separately so unsupported pressure-level fields cannot
# break the main forecast request for any model.
PROFILE_MODELS = [
    "best_match", "ncep_hrrr_conus", "ncep_gfs_global", "ecmwf_ifs",
    "cmc_gem_seamless", "cma_grapes_global",
]
PROFILE_LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300]
PROFILE_VARIABLES = [
    f"{var}_{level}hPa"
    for level in PROFILE_LEVELS
    for var in (
        "temperature", "relative_humidity", "dew_point", "cloud_cover",
        "vertical_velocity", "geopotential_height",
    )
]

DAILY_VARIABLES = [
    "weather_code", "temperature_2m_min", "temperature_2m_mean", "temperature_2m_max",
    "apparent_temperature_min", "apparent_temperature_mean", "apparent_temperature_max",
    "uv_index_max", "uv_index_clear_sky_max", "sunrise", "sunset",
    "daylight_duration", "sunshine_duration", "shortwave_radiation_sum",
    "precipitation_sum", "rain_sum", "showers_sum", "snowfall_sum",
    "precipitation_hours", "precipitation_probability_min",
    "precipitation_probability_mean", "precipitation_probability_max",
    "cloud_cover_min", "cloud_cover_mean", "cloud_cover_max",
    "visibility_min", "visibility_mean", "visibility_max",
    "cape_min", "cape_mean", "cape_max", "relative_humidity_2m_min",
    "relative_humidity_2m_mean", "relative_humidity_2m_max",
    "dew_point_2m_min", "dew_point_2m_mean", "dew_point_2m_max",
    "wet_bulb_temperature_2m_min", "wet_bulb_temperature_2m_mean",
    "wet_bulb_temperature_2m_max", "wind_speed_10m_min", "wind_speed_10m_mean",
    "wind_speed_10m_max", "wind_gusts_10m_min", "wind_gusts_10m_mean",
    "wind_gusts_10m_max", "wind_direction_10m_dominant", "pressure_msl_min",
    "pressure_msl_mean", "pressure_msl_max", "surface_pressure_min",
    "surface_pressure_mean", "surface_pressure_max", "et0_fao_evapotranspiration",
    "vapour_pressure_deficit_max", "leaf_wetness_probability_mean",
]

HRRR_15MIN_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
    "precipitation", "rain", "snowfall", "weather_code", "cape", "visibility",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "sunshine_duration",
    "is_day", "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "direct_normal_irradiance", "terrestrial_radiation", "shortwave_radiation_instant",
    "direct_radiation_instant", "diffuse_radiation_instant",
    "direct_normal_irradiance_instant", "terrestrial_radiation_instant",
]

ENSEMBLE_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
    "precipitation", "rain", "cloud_cover", "cloud_cover_low", "cloud_cover_mid",
    "cloud_cover_high", "visibility", "wind_speed_10m", "wind_gusts_10m",
    "uv_index", "uv_index_clear_sky", "cape", "convective_inhibition",
    "sunshine_duration", "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "direct_normal_irradiance", "shortwave_radiation_instant",
    "direct_radiation_instant", "diffuse_radiation_instant",
    "direct_normal_irradiance_instant",
]
ENSEMBLE_MEAN_VARIABLES = [
    item for variable in ENSEMBLE_VARIABLES for item in (variable, f"{variable}_spread")
]

AIR_QUALITY_VARIABLES = [
    "pm10", "pm2_5", "carbon_monoxide", "carbon_dioxide", "nitrogen_dioxide",
    "sulphur_dioxide", "ozone", "methane", "aerosol_optical_depth", "dust",
    "uv_index", "uv_index_clear_sky", "us_aqi", "us_aqi_pm2_5", "us_aqi_pm10",
    "us_aqi_ozone",
]

CURRENT_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
    "is_day", "precipitation", "rain", "showers", "weather_code", "cloud_cover",
    "pressure_msl", "surface_pressure", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "direct_normal_irradiance", "uv_index", "uv_index_clear_sky",
]

# NASA POWER: exactly 15 parameters, the Hourly API maximum. UVA/UVB/UVI are
# calibration targets; the remainder are predictors shared with live forecasts.
NASA_POWER_PARAMETERS = [
    "ALLSKY_SFC_UVA", "ALLSKY_SFC_UVB", "ALLSKY_SFC_UV_INDEX",
    "ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_SW_DNI", "ALLSKY_SFC_SW_DIFF",
    "CLRSKY_SFC_SW_DWN", "ALLSKY_KT", "ALLSKY_SRF_ALB", "AOD_55",
    "CLOUD_AMT", "SZA", "T2M", "RH2M", "PS",
]

OPENMETEO_HISTORY_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "surface_pressure",
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "precipitation", "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "direct_normal_irradiance", "terrestrial_radiation", "uv_index",
    "uv_index_clear_sky", "sunshine_duration",
]

PREVIOUS_RUN_BASE_VARIABLES = [
    "cloud_cover", "precipitation", "shortwave_radiation", "diffuse_radiation",
    "direct_normal_irradiance", "uv_index", "uv_index_clear_sky",
]
PREVIOUS_RUN_LEADS = list(range(8))
PREVIOUS_RUN_MODELS = [
    "ncep_hrrr_conus", "ncep_nbm_conus", "ncep_gfs_global", "ecmwf_ifs",
]

# Direct CAMS NRT spectral/atmospheric inputs. Requests are split into groups to
# isolate dataset/variable incompatibilities and keep failures local.
CAMS_FORECAST_VARIABLE_GROUPS = {
    "uv": [
        "uv_biologically_effective_dose",
        "uv_biologically_effective_dose_clear_sky",
        "downward_uv_radiation_at_the_surface",
    ],
    "spectral_aod": [
        "total_aerosol_optical_depth_340nm", "total_aerosol_optical_depth_355nm",
        "total_aerosol_optical_depth_380nm", "total_aerosol_optical_depth_400nm",
        "total_absorption_aerosol_optical_depth_340nm",
        "total_absorption_aerosol_optical_depth_355nm",
        "total_absorption_aerosol_optical_depth_380nm",
        "total_absorption_aerosol_optical_depth_400nm",
    ],
    "aerosol_optics": [
        "single_scattering_albedo_340nm", "single_scattering_albedo_355nm",
        "single_scattering_albedo_380nm", "single_scattering_albedo_400nm",
        "asymmetry_factor_340nm", "asymmetry_factor_355nm",
        "asymmetry_factor_380nm", "asymmetry_factor_400nm",
    ],
    "columns": [
        "total_column_ozone", "total_column_water_vapour",
        "total_column_cloud_liquid_water", "total_column_cloud_ice_water",
        "forecast_albedo", "total_cloud_cover",
    ],
    "radiation_context": [
        "direct_solar_radiation", "surface_solar_radiation_downwards",
    ],
}

CAMS_EAC4_VARIABLES = [
    "total_aerosol_optical_depth_469nm", "total_aerosol_optical_depth_550nm",
    "total_aerosol_optical_depth_670nm", "total_aerosol_optical_depth_865nm",
    "total_column_ozone", "total_cloud_cover",
]
