# Notebooks

Four notebooks on the open data of NASA FIRMS, stored with their outputs. None
needs a MAP_KEY.

| Notebook | What it shows | Data |
|---|---|---|
| [01_fire_history](01_fire_history.ipynb) | Italy since 2012: detections, vegetation fires and fire-days per year, North, Centre and South | the yearly archives, about 2 MB a year, downloaded once |
| [02_season_comparison](02_season_comparison.ipynb) | the last season month by month against the others, and every summer ranked with `anomaly()` | the same archives |
| [03_how_much_to_trust](03_how_much_to_trust.ipynb) | `trust()` and `facts.place()` on a steelworks, two burnt places and the sea; what FIRMS sees by fire size | the crops of the benchmark, offline |
| [04_cells_for_a_model](04_cells_for_a_model.ipynb) | `cell_stats()` on the 1 km LAEA grid, with `None` kept as NaN | the crops of the benchmark, offline |

Run them:

```bash
make notebooks           # all four (01 and 02 download the archives the first time)
make notebooks-offline   # 03 and 04 only: no network, as CI does
docker compose --profile notebook up   # JupyterLab on http://127.0.0.1:8890
```

The archives go to the data directory: `$DATA_ROOT/firms-client`, else
`~/.cache/firms-client`. Anything published from these notebooks carries the
NASA acknowledgement (`ATTRIBUTION`), and the ESA WorldCover credit (CC BY 4.0)
where the land cover was used.
