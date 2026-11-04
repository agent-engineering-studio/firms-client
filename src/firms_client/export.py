"""Hotspots out: GeoJSON for QGIS and web maps, CSV for everything else."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import asdict, fields
from datetime import date
from typing import Any

from firms_client.hotspots import Hotspot

#: The CSV header :func:`to_csv` writes: every :class:`Hotspot` field.
CSV_COLUMNS = tuple(f.name for f in fields(Hotspot))


def _plain(h: Hotspot) -> dict[str, Any]:
    return {k: v.isoformat() if isinstance(v, date) else v for k, v in asdict(h).items()}


def to_geojson(hotspots: Iterable[Hotspot]) -> dict[str, Any]:
    """A GeoJSON ``FeatureCollection`` of points; every other field is a property."""
    features = []
    for h in hotspots:
        properties = _plain(h)
        del properties["latitude"], properties["longitude"]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [h.longitude, h.latitude]},
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def to_csv(hotspots: Iterable[Hotspot]) -> str:
    """One row per hotspot, with :data:`CSV_COLUMNS`; missing values are empty."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for h in hotspots:
        writer.writerow(_plain(h))
    return out.getvalue()
