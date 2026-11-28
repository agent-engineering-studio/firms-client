"""The functions moved from Limen in 0.10.0 give what Limen's gave (tests/limen_frozen.py)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import firms_client as firms
from firms_client import LaeaGrid, WorldCover
from tests import limen_frozen as limen

FIXTURES = Path(__file__).parent / "fixtures"
VIIRS = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_text(encoding="utf-8")
MODIS = (FIXTURES / "modis_2025_Italy_sample.csv").read_text(encoding="utf-8")

HEADER = "latitude,longitude,bright_ti4,acq_date,acq_time,confidence,frp,daynight,type"
#: The area API: no ``type``; a malformed row, a low confidence, a weak one.
NRT = "\n".join(
    [
        HEADER.removesuffix(",type"),
        "40.5005,17.2005,330.1,2025-07-01,0126,h,12.5,N",
        "40.5005,17.2005,331.0,2025-07-02,0130,n,0.4,N",
        "41.9000,12.5000,305.0,2025-07-02,1210,l,3.0,D",
        "not-a-number,12.5,305.0,2025-07-02,1210,n,3.0,D",
        "42.1000,13.1000,310.0,2025-07-03,2501,n,3.0,D",
        "42.1000,13.1000,310.0,2025-07-03,1201,,3.0,D",
    ]
)


def plant(year: int) -> str:
    """A year of archive with a steelworks (``type`` 2) at 40.5005 N 17.2005 E and one fire."""
    rows = [f"40.5005,17.2005,330,{year}-{m:02d}-1{m % 9},0126,h,20,N,2" for m in range(1, 13)]
    rows.append(f"44.1005,8.2005,320,{year}-08-01,1201,n,5,D,0")
    return "\n".join([HEADER, *rows])


ARCHIVES = {year: plant(year) for year in range(2019, 2025)}
MASK = firms.static_mask_from_archives(ARCHIVES, country="Italy")

BARS = [
    {},
    {"min_confidence": "high"},
    {"min_confidence": "low", "min_confidence_pct": 0},
    {"min_confidence_pct": 80},
    {"min_frp_mw": 1.0},
    {"min_frp_mw": 10.0, "min_confidence": "high", "min_confidence_pct": 60},
]


@pytest.mark.parametrize("text", [VIIRS, MODIS, NRT, plant(2024), "", "Invalid MAP_KEY.\n"])
@pytest.mark.parametrize("bar", BARS)
@pytest.mark.parametrize("mask", [None, MASK])
def test_read_csv_keeps_and_drops_what_limen_did(
    text: str, bar: dict[str, object], mask: firms.StaticMask | None
) -> None:
    kept, dropped = limen.parse_hotspot_csv(text, static_mask=mask, **bar)  # type: ignore[arg-type]
    # Limen's own default for a MODIS percentage was 50, not the library's mapping.
    ours = firms.read_csv(
        text,
        mask=mask,
        vegetation_only=False,
        **{"min_confidence_pct": 50, **bar},  # type: ignore[arg-type]
    )
    assert ours.hotspots == kept
    assert ours.dropped == dropped


def test_read_csv_counts_the_malformed_rows_and_labels_with_the_mask() -> None:
    reading = firms.read_csv(NRT, mask=MASK, vegetation_only=False, min_confidence="low")
    assert (reading.rows, reading.malformed, reading.dropped) == (6, 2, 2)
    assert [h.detection_type for h in reading.hotspots] == [2, 2, None, None]
    # With the default, what the mask calls a plant is dropped.
    assert len(firms.read_csv(NRT, mask=MASK, min_confidence="low").hotspots) == 2


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, VIIRS),
        (200, ""),
        (400, "Invalid MAP_KEY.\n"),
        (429, "Exceeding allowed transaction limit."),
        (500, "<html>error</html>"),
        (404, ""),
    ],
)
def test_area_error_is_limens_no_data(status: int, body: str) -> None:
    assert (firms.area_error(status, body) is None) == limen.has_data(status, body.encode()) or (
        # An empty 200: no data for Limen, no detections here. Nothing is stored either way.
        status == 200 and not body and firms.area_error(status, body) is None
    )


def test_area_error_also_catches_an_error_page_with_http_200() -> None:
    # Limen parsed it and got no rows, silently; the library says what came back.
    assert limen.has_data(200, b"Invalid MAP_KEY.")
    assert (
        firms.area_error(200, "Invalid MAP_KEY.") == "FIRMS area API (HTTP 200): Invalid MAP_KEY."
    )


def test_sp_source_is_limens_source_column() -> None:
    assert {p: p.sp_source for p in firms.ARCHIVE_PRODUCTS} == limen.ARCHIVE_SOURCES
    assert all(p.sp_source in firms.SP_SOURCES for p in firms.ARCHIVE_PRODUCTS)


@pytest.mark.parametrize(
    "name",
    [
        "viirs-snpp_2025_Italy.csv",
        "modis_2020_Italy.csv",
        "MODIS_2020_Italy.CSV",
        "VIIRS-SNPP_2012_Greece.csv",
        "fire_archive_M-C61_1234.csv",
        "export.csv",
    ],
)
def test_archive_product_of_is_limens_guess_from_the_name(name: str) -> None:
    found = firms.archive_product_of(f"/data/firms/{name}")
    assert (found or firms.ARCHIVE_PRODUCTS[0]) == limen.product_of_stem(Path(name).stem)
    assert (found is None) == name.startswith(("fire", "export"))


@pytest.mark.parametrize("product", firms.ARCHIVE_PRODUCTS)
@pytest.mark.parametrize(("lo", "hi"), [(0, 2025), (2015, 2025), (1990, 2003), (2030, 2025)])
def test_archive_years_from_a_first_year(product: firms.ArchiveProduct, lo: int, hi: int) -> None:
    assert firms.archive_years(product, until=hi, first=lo or None) == limen.years_to_download(
        product, lo=lo, hi=hi
    )


@pytest.mark.parametrize("today", [date(2026, 1, 1), date(2026, 11, 28), date(2024, 12, 31)])
def test_last_archive_year(today: date) -> None:
    assert firms.last_archive_year(today) == limen.last_year(today)
    assert firms.last_archive_year() == date.today().year - 1


def test_static_mask_name() -> None:
    assert firms.static_mask_filename("Italy", 2012, 2025) == limen.mask_name(
        slug="viirs-snpp", country="Italy", first=2012, last=2025
    )
    assert firms.static_mask_filename("Greece", 2000, 2024, firms.MODIS) == limen.mask_name(
        slug="modis", country="Greece", first=2000, last=2024
    )


def test_static_mask_from_archives_is_limens_mask() -> None:
    theirs = limen.build_mask(ARCHIVES, country="Italy", slug="viirs-snpp")
    assert MASK.cells == theirs.cells
    assert MASK.cells  # the steelworks is in it
    assert MASK.known == theirs.known
    assert MASK.rules == theirs.rules
    assert MASK.meta == {**theirs.meta, "detections": 13 * len(ARCHIVES)}


@pytest.mark.parametrize(
    "found",
    [
        [2012, 2013, 2014, 2015],
        [2012, 2013, 2014],
        [2012, 2014, 2015],
        [2013, 2014, 2015],
        [2012, 2013],
        [],
    ],
)
def test_archive_years_complete_is_limens_rule_for_saving(found: list[int]) -> None:
    wanted = [2012, 2013, 2014, 2015]
    texts = dict.fromkeys(found, "")
    assert firms.archive_years_complete(wanted, found) == limen.worth_saving(wanted, texts, 2015)


def test_archive_years_complete_with_nothing_wanted() -> None:
    assert firms.archive_years_complete([], [])


def test_worldcover_local_is_limens_worldcover_locale(tmp_path: Path) -> None:
    folder = tmp_path / firms.WORLDCOVER_DIR
    assert firms.WorldCover.local(tmp_path) is None
    assert limen.worldcover_locale(folder) is None
    folder.mkdir()
    (folder / "notes.txt").write_text("no tile yet")
    assert firms.WorldCover.local(tmp_path) is None
    assert limen.worldcover_locale(folder) is None

    tile = firms.worldcover_path(firms.worldcover_tiles((12.1, 41.1, 12.9, 41.9))[0], tmp_path)
    tile.parent.mkdir(parents=True)
    tile.touch()
    ours, theirs = firms.WorldCover.local(tmp_path), limen.worldcover_locale(folder)
    assert isinstance(ours, WorldCover)
    assert theirs is not None
    assert (ours.source, ours.year) == (theirs.source, theirs.year) == (str(folder), 2021)
    # Never the bucket, as WorldCover.synced() would be without the folder.
    assert not ours.source.startswith("http")


def test_worldcover_local_reads_the_default_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    assert firms.WorldCover.local() is None
    tile = tmp_path / "firms-client" / firms.WORLDCOVER_DIR / "v200" / "x.tif"
    tile.parent.mkdir(parents=True)
    tile.touch()
    assert firms.WorldCover.local() is not None


def stored_cells(grid: LaeaGrid, cells: list[tuple[int, int]]) -> list[dict[str, float]]:
    """The rows Limen read from its table: indices, south-west corner (EPSG:3035), centre."""
    rows = []
    for row, col in cells:
        lat, lon = grid.centre((row, col))
        rows.append(
            {
                "row_idx": row,
                "col_idx": col,
                "x": grid.origin[0] + col * grid.size_m,
                "y": grid.origin[1] + row * grid.size_m,
                "lat": lat,
                "lon": lon,
            }
        )
    return rows


CELLS = [(17, 4), (0, 0), (3, 250), (411, 9), (120, 120)]


@pytest.mark.parametrize("origin", [(4_321_123.4, 2_100_456.7), (4_000_000.0, 1_500_000.0)])
@pytest.mark.parametrize("size_m", [1000.0, 250.0])
def test_anchored_is_limens_grid(origin: tuple[float, float], size_m: float) -> None:
    rows = stored_cells(LaeaGrid(size_m=size_m, origin=origin), CELLS)
    theirs = limen.griglia(rows, size_m)
    first = rows[0]
    ours = LaeaGrid.anchored(
        (int(first["row_idx"]), int(first["col_idx"])), (first["x"], first["y"]), size_m=size_m
    )
    assert ours == theirs
    centres = [((int(r["row_idx"]), int(r["col_idx"])), (r["lat"], r["lon"])) for r in rows]
    assert ours.misplaced(centres) == []


def test_misplaced_starts_with_the_cell_limen_raised_on() -> None:
    # Cells stored on a 500 m grid, read as if they were 1 km.
    rows = stored_cells(LaeaGrid(size_m=500.0, origin=(4_321_000.0, 2_100_000.0)), CELLS)
    with pytest.raises(limen.GrigliaDiversaError, match="0,0"):
        limen.griglia(rows, 1000.0)
    first = rows[0]
    grid = LaeaGrid.anchored((17, 4), (first["x"], first["y"]))
    centres = [((int(r["row_idx"]), int(r["col_idx"])), (r["lat"], r["lon"])) for r in rows]
    assert grid.misplaced(centres) == [(0, 0), (3, 250), (411, 9), (120, 120)]
