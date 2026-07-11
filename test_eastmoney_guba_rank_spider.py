from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent / "工具" / "东方财富股吧人气榜爬虫.py"


def load_module():
    spec = importlib.util.spec_from_file_location("eastmoney_guba_rank_spider", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_extract_popularity_payload_and_decrypt_fixture():
    spider = load_module()
    script = (
        "var popularityList='"
        "Hmc6pZaFBREpr5BaHrj6w/IvCN/XJ5OgUJaGD3cq4kkPCRO8WsQNRzy5uNibfVm31pyd834DS/PjMcwNEpjacrf6FicpFiTZSbdypawRuUGGktB4rLA5eBblEdZ/TVt+2vpZ2Ut0GnSmIA89ZmViz1lzAJWBNNS27M0JDCdn9IWQUjcRBhCYQptD2uATnKmssFhnJHO63q6HVHqPeWm8lMt9UuVOmkzQ8QDFJ8M8SMAk51JqEN5N+sQMLT4pCVNZ"
        "';"
    )

    payload = spider.extract_popularity_payload(script)
    rows = spider.decrypt_popularity_payload(payload)

    assert rows == [
        {
            "code": "000001",
            "rankNumber": 1,
            "changeNumber": -2,
            "exactTime": "2026-07-08 17:02:00",
            "ironsFans": "80.00",
            "newFans": "20.00",
            "history": [{"CALCTIME": "2026-07-07 23:58:00", "RANK": 3}],
        }
    ]


def test_flatten_rank_row_keeps_history_as_json_text():
    spider = load_module()
    row = {
        "code": "000001",
        "rankNumber": 1,
        "changeNumber": -2,
        "exactTime": "2026-07-08 17:02:00",
        "ironsFans": "80.00",
        "newFans": "20.00",
        "history": [{"CALCTIME": "2026-07-07 23:58:00", "RANK": 3}],
    }

    flat = spider.flatten_rank_row(row, market_type=0, sort_type=0, page=1)

    assert flat["市场"] == "A股"
    assert flat["榜单"] == "热门排行"
    assert flat["页码"] == 1
    assert flat["股票代码"] == "000001"
    assert flat["当前排名"] == 1
    assert flat["排名变化"] == -2
    assert flat["更新时间"] == "2026-07-08 17:02:00"
    assert flat["老股民占比"] == "80.00"
    assert flat["新股民占比"] == "20.00"
    assert flat["历史排名"] == '[{"CALCTIME":"2026-07-07 23:58:00","RANK":3}]'
