"""Draw the README images in docs/images from the real 2025 Italian archives.

    uv run python docs/make_images.py [DATA_DIR] [OUT_DIR]

The archives are fetched with firms-client into DATA_DIR (default: the
firms-client data directory), so a second run reads them from disk.
"""

import asyncio
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from firms_client import MODIS, VIIRS_SNPP, Hotspot, fetch_archive, select

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else None
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "images"
OUT.mkdir(parents=True, exist_ok=True)


async def load() -> tuple[list[Hotspot], list[Hotspot]]:
    async with httpx.AsyncClient(timeout=120) as client:
        v = await fetch_archive(client, VIIRS_SNPP, 2025, "Italy", DATA)
        m = await fetch_archive(client, MODIS, 2025, "Italy", DATA)
    assert v is not None and m is not None
    return v, m


viirs, modis = asyncio.run(load())

FONT = 'text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}'
LIGHT = {
    "bg": "#fcfcfb",
    "t1": "#0b0b0b",
    "t2": "#52514e",
    "ax": "#7a7974",
    "grid": "#e6e5e0",
    "chip": "#f0efec",
    "veg": "#eb6834",
    "ind": "#2a78d6",
    "off": "#1baf7a",
    "vol": "#eda100",
    "na": "#d9d8d2",
}
DARK = {
    "bg": "#1a1a19",
    "t1": "#f0efec",
    "t2": "#c3c2b7",
    "ax": "#8f8e88",
    "grid": "#2e2e2b",
    "chip": "#2a2a28",
    "veg": "#d95926",
    "ind": "#3987e5",
    "off": "#199e70",
    "vol": "#c98500",
    "na": "#45443f",
}


def style() -> str:
    def rules(p: dict[str, str]) -> str:
        fills = " ".join(f".{k}{{fill:{v}}}" for k, v in p.items() if k != "grid")
        return f"{fills} .grid{{stroke:{p['grid']};stroke-width:1}} .mark{{stroke:{p['t1']}}}"

    return (
        f"<style>\n  {FONT}\n  {rules(LIGHT)}\n"
        f"  @media (prefers-color-scheme: dark){{ {rules(DARK)} }}\n</style>"
    )


def svg(name: str, w: int, h: int, label: str, body: str) -> None:
    text = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{label}">\n{style()}\n<rect class="bg" width="{w}" height="{h}" rx="14"/>\n'
        f"{body}\n</svg>\n"
    )
    (OUT / name).write_text(text)
    print(name, len(text) // 1024, "KB")


def legend(items: list[tuple[str, str]], x: float, y: float, gap: float = 26) -> str:
    out = []
    for i, (cls, label) in enumerate(items):
        yy = y + i * gap
        out.append(
            f'<rect class="{cls}" x="{x}" y="{yy - 11}" width="13" height="13" rx="3"/>'
            f'<text class="t2" x="{x + 21}" y="{yy}" font-size="14">{label}</text>'
        )
    return "".join(out)


# --- map: 0.1° cells, coloured by what most of their detections are ------------------
W_, S_, E_, N_ = 6.4, 36.5, 18.6, 47.2
COS = math.cos(math.radians(42))
CELL = 0.1


def cells(rows, scale: float, x0: float, y0: float):  # type: ignore[no-untyped-def]
    by_cell: dict[tuple[int, int], Counter[str]] = defaultdict(Counter)
    for r in rows:
        if not (W_ <= r.longitude <= E_ and S_ <= r.latitude <= N_):
            continue
        key = (int((r.longitude - W_) / CELL), int((N_ - r.latitude) / CELL))
        kind = {0: "veg", 2: "ind"}.get(r.detection_type, "off")  # type: ignore[arg-type]
        by_cell[key][kind] += 1
    cw, ch = CELL * COS * scale, CELL * scale
    out = []
    counts: Counter[str] = Counter()
    for (cx, cy), c in sorted(by_cell.items()):
        kind = c.most_common(1)[0][0]
        counts[kind] += 1
        out.append(
            f'<rect class="{kind}" x="{x0 + cx * cw:.1f}" y="{y0 + cy * ch:.1f}" '
            f'width="{cw - 0.4:.1f}" height="{ch - 0.4:.1f}"/>'
        )
    return "".join(out), counts


def to_xy(lon: float, lat: float, scale: float, x0: float, y0: float) -> tuple[float, float]:
    return x0 + (lon - W_) * COS * scale, y0 + (N_ - lat) * scale


SCALE = 46.0
X0, Y0 = 40.0, 84.0
grid, counts = cells(viirs, SCALE, X0, Y0)
map_w = (E_ - W_) * COS * SCALE
map_h = (N_ - S_) * SCALE

# Annotations: the two busiest industrial cells of 2025 (a plant in the Po valley, and
# the ILVA steelworks in Taranto) and Etna, the volcano.
notes = [
    (17.21, 40.52, "ILVA steelworks, Taranto", "industry · type 2"),
    (15.00, 37.75, "Etna", "volcano · type 1"),
]
side = X0 + map_w + 60
body = [
    f'<text class="t1" x="40" y="42" font-size="20" font-weight="700">'
    f"Italy, 2025: {len(viirs):,} VIIRS detections. Not all of them are fires.</text>",
    '<text class="t2" x="40" y="64" font-size="14">Each square is 0.1°, coloured by what '
    'most of its detections are (the FIRMS <tspan font-family="monospace">type</tspan> '
    "column).</text>",
    grid,
    legend(
        [
            ("veg", f"Vegetation fire (type 0) · {counts['veg']:,} squares"),
            ("ind", f"Industry, gas flares (type 2) · {counts['ind']:,} squares"),
            ("off", f"Volcano or offshore (type 1, 3) · {counts['off']:,} squares"),
        ],
        side,
        Y0 + 40,
    ),
]
# Callouts on the right, connected to the map.
for i, (lon, lat, title, sub) in enumerate(notes):
    x, y = to_xy(lon, lat, SCALE, X0, Y0)
    ty = Y0 + 190 + i * 70
    body.append(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" class="mark" fill="none" stroke-width="1.5"/>'
    )
    body.append(
        f'<line x1="{x + 8:.1f}" y1="{y:.1f}" x2="{side - 8}" y2="{ty - 5}" class="mark" '
        f'stroke-width="1" style="stroke-dasharray:3 3;opacity:.55"/>'
        f'<text class="t1" x="{side}" y="{ty}" font-size="15" font-weight="600">{title}</text>'
        f'<text class="t2" x="{side}" y="{ty + 20}" font-size="13">{sub}</text>'
    )
nonveg_rows = [r for r in viirs if r.detection_type not in (0, None)]
nonveg = len(nonveg_rows)
passed = len(select(nonveg_rows, vegetation_only=False)) / nonveg
body.append(
    f'<text class="t1" x="{side}" y="{Y0 + 380}" font-size="34" font-weight="700">'
    f"{nonveg / len(viirs):.0%}</text>"
    f'<text class="t2" x="{side}" y="{Y0 + 404}" font-size="14">of the detections are not '
    "vegetation fires:</text>"
    f'<text class="t2" x="{side}" y="{Y0 + 424}" font-size="14">a confidence filter keeps '
    f"{passed:.0%} of them.</text>"
    f'<text class="ax" x="{side}" y="{Y0 + map_h}" font-size="11">Source: NASA FIRMS, '
    "VIIRS S-NPP archive, Italy 2025</text>"
)
map_svg = "".join(body)
svg(
    "map.svg",
    980,
    int(Y0 + map_h + 30),
    "Map of Italy with 2025 VIIRS detections coloured by type: vegetation fires across the "
    "south and the islands, industrial sources in the Po valley and Taranto",
    map_svg,
)
text = (OUT / "map.svg").read_text()
text = text.replace(
    "@media (prefers-color-scheme: dark){",
    ".mark{stroke:#0b0b0b}\n  @media (prefers-color-scheme: dark){ .mark{stroke:#f0efec} ",
)
(OUT / "map.svg").write_text(text)


# --- types: share of each detection type, per product ----------------------------
KINDS = [
    (0, "veg", "Vegetation fire"),
    (2, "ind", "Industry"),
    (3, "off", "Offshore"),
    (1, "vol", "Volcano"),
]
bx, bw, bh = 200, 640, 38
body = [
    '<text class="t1" x="40" y="42" font-size="20" font-weight="700">'
    "What the satellites saw over Italy in 2025</text>",
    '<text class="t2" x="40" y="64" font-size="14">Share of detections by FIRMS '
    '<tspan font-family="monospace">type</tspan>. Only the orange part is what you want.</text>',
]
for x in range(0, 101, 25):
    gx = bx + bw * x / 100
    body.append(
        f'<line class="grid" x1="{gx}" y1="92" x2="{gx}" y2="232"/>'
        f'<text class="ax" x="{gx}" y="250" font-size="11" text-anchor="middle">{x}%</text>'
    )
for i, (label, rows) in enumerate((("MODIS", modis), ("VIIRS S-NPP", viirs))):
    y = 110 + i * 62
    c = Counter(r.detection_type for r in rows)
    total = len(rows)
    body.append(
        f'<text class="t1" x="{bx - 14}" y="{y + 18}" font-size="15" font-weight="600" '
        f'text-anchor="end">{label}</text>'
        f'<text class="t2" x="{bx - 14}" y="{y + 35}" font-size="12" text-anchor="end">'
        f"{total:,} detections</text>"
    )
    x = bx
    for k, cls, _name in KINDS:
        w = bw * c[k] / total
        if w <= 0:
            continue
        body.append(
            f'<rect class="{cls}" x="{x:.1f}" y="{y}" width="{max(w - 2, 1):.1f}" '
            f'height="{bh}" rx="3"/>'
        )
        if w > 46:
            body.append(
                f'<text x="{x + 8:.1f}" y="{y + 24}" font-size="13" font-weight="600" '
                f'fill="#ffffff">{c[k] / total:.0%}</text>'
            )
        x += w
leg = []
lx = 200
for _k, cls, name in KINDS:
    leg.append(
        f'<rect class="{cls}" x="{lx}" y="274" width="13" height="13" rx="3"/>'
        f'<text class="t2" x="{lx + 21}" y="285" font-size="14">{name}</text>'
    )
    lx += 40 + 8 * len(name)
body.append("".join(leg))
svg(
    "types.svg",
    980,
    310,
    "Share of detection types over Italy in 2025: MODIS 67% vegetation, 32% industry; "
    "VIIRS S-NPP 75% vegetation, 18% industry, 4% offshore, 3% volcano",
    "".join(body),
)


# --- monthly: vegetation fires vs the rest, VIIRS ---------------------------------
veg = [0] * 12
rest = [0] * 12
for r in viirs:
    if r.detection_type is None:
        continue
    (veg if r.detection_type == 0 else rest)[r.acq_date.month - 1] += 1
top = 6000
px, py, pw, ph = 90, 92, 850, 240
body = [
    '<text class="t1" x="40" y="42" font-size="20" font-weight="700">'
    "Fires come in summer. Factories burn all year.</text>",
    '<text class="t2" x="40" y="64" font-size="14">VIIRS S-NPP detections over Italy per '
    "month, 2025. In winter most hotspots are not fires at all.</text>",
]
for v in range(0, top + 1, 1500):
    gy = py + ph - ph * v / top
    body.append(
        f'<line class="grid" x1="{px}" y1="{gy:.1f}" x2="{px + pw}" y2="{gy:.1f}"/>'
        f'<text class="ax" x="{px - 10}" y="{gy + 4:.1f}" font-size="11" '
        f'text-anchor="end">{v:,}</text>'
    )
step = pw / 12
cw = step * 0.62
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
for m in range(12):
    x = px + m * step + (step - cw) / 2
    h_rest = ph * rest[m] / top
    h_veg = ph * veg[m] / top
    base = py + ph
    body.append(
        f'<rect class="ind" x="{x:.1f}" y="{base - h_rest:.1f}" width="{cw:.1f}" '
        f'height="{h_rest:.1f}" rx="2"/>'
        f'<rect class="veg" x="{x:.1f}" y="{base - h_rest - h_veg:.1f}" width="{cw:.1f}" '
        f'height="{max(h_veg - 2, 0.5):.1f}" rx="3"/>'
        f'<text class="ax" x="{x + cw / 2:.1f}" y="{base + 18}" font-size="12" '
        f'text-anchor="middle">{months[m]}</text>'
    )
    if m in (0, 6, 11):
        tot = veg[m] + rest[m]
        body.append(
            f'<text class="t2" x="{x + cw / 2:.1f}" y="{base - h_rest - h_veg - 8:.1f}" '
            f'font-size="12" text-anchor="middle">{veg[m] / tot:.0%} fire</text>'
        )
lx = px
leg = []
for cls, name in (
    ("veg", "Vegetation fire (type 0)"),
    ("ind", "Everything else: industry, volcano, offshore (type 1-3)"),
):
    leg.append(
        f'<rect class="{cls}" x="{lx}" y="{py + ph + 38}" width="13" height="13" rx="3"/>'
        f'<text class="t2" x="{lx + 21}" y="{py + ph + 49}" font-size="14">{name}</text>'
    )
    lx += 240
body.append("".join(leg))
svg(
    "monthly.svg",
    980,
    py + ph + 74,
    "Monthly VIIRS detections over Italy in 2025, stacked: vegetation fires peak in July "
    f"({veg[6]:,}); the other types stay between {min(rest)} and {max(rest)} a month",
    "".join(body),
)
print("veg", veg)
print("rest", rest)


# --- coverage: which product, which years, which endpoint -------------------------
y0, y1 = 2000, 2027
tx, tw = 230, 700


def to_x(year: float) -> float:
    return tx + tw * (year - y0) / (y1 - y0)


rows_ = [
    ("modis", "MODIS (Terra + Aqua)", 2000, 2026, "veg", "archive 2000-2025 · no key"),
    ("viirs-snpp", "VIIRS S-NPP", 2012, 2026, "veg", "archive 2012-2025 · no key"),
    ("viirs-noaa20", "VIIRS NOAA-20", 2018, 2026, None, "area API only · MAP_KEY"),
    ("viirs-noaa21", "VIIRS NOAA-21", 2023, 2026, None, "area API only · MAP_KEY"),
]
body = [
    '<text class="t1" x="40" y="42" font-size="20" font-weight="700">'
    "26 years of fires, two doors in</text>",
    '<text class="t2" x="40" y="64" font-size="14">Open per-country archives for the '
    "history, the area API for the last days.</text>",
]
for yr in range(2000, 2027, 5):
    body.append(
        f'<line class="grid" x1="{to_x(yr):.1f}" y1="86" x2="{to_x(yr):.1f}" y2="300"/>'
        f'<text class="ax" x="{to_x(yr):.1f}" y="318" font-size="11" '
        f'text-anchor="middle">{yr}</text>'
    )
for i, (_slug, name, start, end, cls, note) in enumerate(rows_):
    y = 100 + i * 48
    body.append(
        f'<text class="t1" x="{tx - 14}" y="{y + 18}" font-size="14" font-weight="600" '
        f'text-anchor="end">{name}</text>'
    )
    if cls:
        body.append(
            f'<rect class="{cls}" x="{to_x(start):.1f}" y="{y}" '
            f'width="{to_x(end) - to_x(start) - 2:.1f}" height="26" rx="4"/>'
        )
    else:
        body.append(
            f'<rect class="na" x="{to_x(start):.1f}" y="{y}" '
            f'width="{to_x(end) - to_x(start) - 2:.1f}" height="26" rx="4"/>'
        )
    # NRT window: the last few days, always via the area API
    body.append(
        f'<rect class="ind" x="{to_x(2026):.1f}" y="{y}" width="{to_x(2026.84) - to_x(2026):.1f}" '
        f'height="26" rx="4"/>'
    )
    body.append(
        f'<text class="t2" x="{to_x(start) + 10:.1f}" y="{y + 18}" font-size="12">{note}</text>'
        if to_x(end) - to_x(start) > 190
        else f'<text class="t2" x="{to_x(start) - 10:.1f}" y="{y + 18}" font-size="12" '
        f'text-anchor="end">{note}</text>'
    )
lx = tx
leg = []
tx_leg = 40
lx = tx_leg
for cls, name in (
    ("veg", "per-country yearly CSV (fetch_archive)"),
    ("ind", "near-real-time (fetch_area)"),
    ("na", "satellite flying, no country archive"),
):
    leg.append(
        f'<rect class="{cls}" x="{lx}" y="288" width="13" height="13" rx="3" '
        f'transform="translate(0,52)"/>'
        f'<text class="t2" x="{lx + 21}" y="351" font-size="13">{name}</text>'
    )
    lx += 52 + 7 * len(name)
body.append("".join(leg))
svg(
    "coverage.svg",
    980,
    375,
    "Timeline: MODIS archive from 2000 and VIIRS S-NPP from 2012, both open with no key; "
    "VIIRS NOAA-20 and NOAA-21 only through the near-real-time area API with a MAP_KEY",
    "".join(body),
)

# --- banner: the real map, small, beside the name ----------------------------------
grid_s, _ = cells(viirs, 19.0, 690, 14)
body = [
    '<text class="t1" x="40" y="92" font-size="44" font-weight="700">firms-client</text>',
    '<text class="t2" x="40" y="128" font-size="18">'
    "NASA active fires in Python: 26 years of</text>",
    '<text class="t2" x="40" y="152" font-size="18">open archives, and the one column that</text>',
    '<text class="t2" x="40" y="176" font-size="18">tells a wildfire from a steelworks.</text>',
]
chips = ["MODIS", "VIIRS", "async", "no key needed", "1 dependency"]
cx = 40
for c in chips:
    w = 22 + 8.2 * len(c)
    body.append(
        f'<rect class="chip" x="{cx}" y="198" width="{w:.0f}" height="28" rx="14"/>'
        f'<text class="t2" x="{cx + w / 2:.0f}" y="217" font-size="13" '
        f'text-anchor="middle">{c}</text>'
    )
    cx += w + 8
body.append(grid_s)
body.append(
    '<text class="ax" x="960" y="236" font-size="11" text-anchor="end">'
    "Italy 2025, real VIIRS data</text>"
)
svg(
    "banner.svg",
    1000,
    250,
    "firms-client: NASA active fires in Python, with a map of 2025 VIIRS detections over Italy",
    "".join(body),
)
