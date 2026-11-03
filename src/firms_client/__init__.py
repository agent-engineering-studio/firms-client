"""Client for NASA FIRMS active-fire detections."""

from importlib.metadata import version

from firms_client.client import fetch_archive, fetch_archive_csv, fetch_area
from firms_client.errors import FirmsError
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
from firms_client.sources import (
    ARCHIVE_PRODUCTS,
    MODIS,
    NRT_SOURCES,
    VIIRS_SNPP,
    ArchiveProduct,
    BBox,
    archive_url,
    archive_years,
    area_url,
)

__version__ = version("firms-client")

__all__ = [
    "ACTIVE_VOLCANO",
    "ARCHIVE_PRODUCTS",
    "MODIS",
    "NRT_SOURCES",
    "OFFSHORE",
    "STATIC_LAND_SOURCE",
    "VEGETATION_FIRE",
    "VIIRS_SNPP",
    "ArchiveProduct",
    "BBox",
    "ConfidenceLevel",
    "FirmsError",
    "Hotspot",
    "__version__",
    "archive_url",
    "archive_years",
    "area_url",
    "confidence_level",
    "fetch_archive",
    "fetch_archive_csv",
    "fetch_area",
    "is_hotspot_csv",
    "parse_csv",
    "select",
]
