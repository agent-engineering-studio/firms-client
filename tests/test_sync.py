from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from firms_client import MODIS, VIIRS_SNPP, sync
from firms_client.sync import MANIFEST

from .test_cli import VIIRS


def archives(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith(("viirs-snpp_2024_Italy.csv", "viirs-snpp_2025_Italy.csv")):
        return httpx.Response(200, content=VIIRS)
    return httpx.Response(404, json={"error": "not found"})


def run(**kwargs: Any) -> Any:
    async def go() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(archives)) as client:
            return await sync(client, "Italy", **kwargs)

    return asyncio.run(go())


def test_sync_downloads_archives_builds_the_mask_and_writes_a_manifest(tmp_path: Path) -> None:
    report = run(first_year=2023, last_year=2025, directory=tmp_path)
    assert report.archives == {"viirs-snpp": [2024, 2025]}
    assert report.missing == {"viirs-snpp": [2023]}
    assert report.mask == str(tmp_path / "static-mask_viirs-snpp_Italy_2023-2025.json")
    assert Path(report.mask).exists() and report.worldcover == []
    manifest = json.loads((tmp_path / MANIFEST).read_text())
    assert manifest["archives"] == {"viirs-snpp": [2024, 2025]} and manifest["synced"]
    again = run(first_year=2023, last_year=2025, directory=tmp_path)
    assert again.archives == report.archives and again.mask_cells == report.mask_cells


def test_sync_without_viirs_builds_no_mask(tmp_path: Path) -> None:
    report = run(products=(MODIS,), first_year=2025, last_year=2025, directory=tmp_path)
    assert report.missing == {"modis": [2025]} and report.mask is None
    assert VIIRS_SNPP.slug not in report.archives


def test_sync_copies_worldcover_over_the_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import firms_client.landcover as landcover

    seen: list[Any] = []

    def save(bbox: Any, directory: Path) -> list[Path]:
        seen.append((bbox, directory))
        return [directory / "worldcover" / "tile.tif"]

    monkeypatch.setattr(landcover, "save_worldcover", save)
    report = run(
        first_year=2025, last_year=2025, directory=tmp_path, worldcover=(17, 40, 17.5, 40.5)
    )
    assert seen == [((17, 40, 17.5, 40.5), tmp_path)]
    assert report.worldcover == [str(tmp_path / "worldcover" / "tile.tif")]
    assert report.worldcover_bbox == (17, 40, 17.5, 40.5)
