from __future__ import annotations

import firms_client


def test_version_is_exposed() -> None:
    assert firms_client.__version__
