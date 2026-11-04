from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from firms_client import CSV_COLUMNS, parse_csv, to_csv, to_geojson

VIIRS = parse_csv(
    (Path(__file__).parent / "fixtures" / "viirs-snpp_2025_Italy_sample.csv").read_text()
)


def test_geojson_points_are_lon_lat_with_every_other_field() -> None:
    collection = to_geojson(VIIRS)
    assert collection["type"] == "FeatureCollection"
    first = collection["features"][0]
    assert first["geometry"] == {
        "type": "Point",
        "coordinates": [VIIRS[0].longitude, VIIRS[0].latitude],
    }
    assert first["properties"]["acq_date"] == "2025-01-01"
    assert first["properties"]["detection_type"] == 2
    assert "latitude" not in first["properties"]
    json.dumps(collection)  # serialisable as is


def test_csv_round_trips_every_field() -> None:
    text = to_csv(VIIRS)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert tuple(rows[0]) == CSV_COLUMNS
    assert len(rows) == len(VIIRS)
    assert rows[0]["acq_date"] == "2025-01-01" and rows[0]["version"] == "2"
    assert to_csv([]).strip() == ",".join(CSV_COLUMNS)
