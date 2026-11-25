from __future__ import annotations

import ast
from pathlib import Path

import firms_client

SRC = Path(firms_client.__file__).parent

#: Limen and its other libraries. Limen pins all of them: if one imported
#: another, Limen would get a circular dependency and pins in conflict.
FORBIDDEN = {
    "limen",
    "dpc_radar",
    "ispra_idrogeo",
    "rainfall_thresholds",
    "egms_client",
    "effis_client",
    "fwi_chain",
    "glofas_ewds",
    "copernicus_ems",
    "ingv_shakemap",
    "imageserver_export",
    "mcp_geo_server",
}


def test_version_is_exposed() -> None:
    assert firms_client.__version__


def test_the_package_imports_no_sister_library() -> None:
    found = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            found += [f"{path.name}: {n}" for n in names if n.split(".")[0] in FORBIDDEN]
    assert found == []


def test_llms_txt_names_every_public_name() -> None:
    llms = (Path(__file__).parents[1] / "docs" / "llms.txt").read_text(encoding="utf-8")
    assert [name for name in firms_client.__all__ if name not in llms] == []
