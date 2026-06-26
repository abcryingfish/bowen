from __future__ import annotations

import json
from pathlib import Path


NOTEBOOK_PATH = Path(__file__).resolve().parent / "ZXW因子" / "ZXW策略技术因子生成.ipynb"


def test_zxw_notebook_uses_ordinary_adjustment_service() -> None:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook.get("cells", []))

    assert "from daily_adjustment_service import apply_daily_adjustment" in source
    assert "_zxw_apply_ordinary_adjustment" in source
    assert "np.cumprod(xdy)" not in source
