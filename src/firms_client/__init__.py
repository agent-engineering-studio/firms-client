"""Client for NASA FIRMS active-fire detections."""

from importlib.metadata import version

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

__version__ = version("firms-client")

__all__ = [
    "ACTIVE_VOLCANO",
    "ARCHIVE_PRODUCTS",
    "CSV_COLUMNS",
    "ENV_DATA_DIR",
    "MAX_AREA_DAYS",
    "MODIS",
    "NRT_SOURCES",
    "OFFSHORE",
    "SP_SOURCES",
    "STATIC_LAND_SOURCE",
    "VEGETATION_FIRE",
    "VIIRS_SNPP",
    "ArchiveProduct",
    "BBox",
    "ConfidenceLevel",
    "FirmsError",
    "Hotspot",
    "RetryPolicy",
    "__version__",
    "archive_filename",
    "archive_url",
    "archive_years",
    "area_url",
    "area_windows",
    "confidence_level",
    "default_directory",
    "download_archive",
    "fetch_archive",
    "fetch_archive_csv",
    "fetch_area",
    "fetch_area_range",
    "is_hotspot_csv",
    "parse_csv",
    "select",
    "to_csv",
    "to_geojson",
]
