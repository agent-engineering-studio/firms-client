"""Client for NASA FIRMS active-fire detections."""

from importlib.metadata import version

from firms_client.anomaly import Anomaly, anomaly, season_anomaly
from firms_client.client import (
    ENV_DATA_DIR,
    default_directory,
    download_archive,
    fetch_archive,
    fetch_archive_csv,
    fetch_area,
    fetch_area_range,
)
from firms_client.errors import FirmsError
from firms_client.events import FireEvent, cluster, distance_m
from firms_client.export import CSV_COLUMNS, to_csv, to_geojson
from firms_client.hotspots import (
    ACTIVE_VOLCANO,
    OFFSHORE,
    STATIC_LAND_SOURCE,
    VEGETATION_FIRE,
    ConfidenceLevel,
    Hotspot,
    confidence_level,
    is_hotspot_csv,
    parse_csv,
    select,
    within,
)
from firms_client.mask import (
    CellVerdict,
    MaskRules,
    StaticMask,
    build_static_mask,
    fetch_static_mask,
)
from firms_client.retry import RetryPolicy
from firms_client.sources import (
    ARCHIVE_PRODUCTS,
    MAX_AREA_DAYS,
    MODIS,
    NRT_SOURCES,
    SP_SOURCES,
    VIIRS_SNPP,
    ArchiveProduct,
    BBox,
    archive_filename,
    archive_url,
    archive_years,
    area_url,
    area_windows,
)
from firms_client.summary import ATTRIBUTION, TYPE_NAMES, summarize

__version__ = version("firms-client")

__all__ = [
    "ACTIVE_VOLCANO",
    "ARCHIVE_PRODUCTS",
    "ATTRIBUTION",
    "CSV_COLUMNS",
    "ENV_DATA_DIR",
    "MAX_AREA_DAYS",
    "MODIS",
    "NRT_SOURCES",
    "OFFSHORE",
    "SP_SOURCES",
    "STATIC_LAND_SOURCE",
    "TYPE_NAMES",
    "VEGETATION_FIRE",
    "VIIRS_SNPP",
    "Anomaly",
    "ArchiveProduct",
    "BBox",
    "CellVerdict",
    "ConfidenceLevel",
    "FireEvent",
    "FirmsError",
    "Hotspot",
    "MaskRules",
    "RetryPolicy",
    "StaticMask",
    "__version__",
    "anomaly",
    "archive_filename",
    "archive_url",
    "archive_years",
    "area_url",
    "area_windows",
    "build_static_mask",
    "cluster",
    "confidence_level",
    "default_directory",
    "distance_m",
    "download_archive",
    "fetch_archive",
    "fetch_archive_csv",
    "fetch_area",
    "fetch_area_range",
    "fetch_static_mask",
    "is_hotspot_csv",
    "parse_csv",
    "season_anomaly",
    "select",
    "summarize",
    "to_csv",
    "to_geojson",
    "within",
]
