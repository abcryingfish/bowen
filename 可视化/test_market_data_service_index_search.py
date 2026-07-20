from __future__ import annotations

import market_data_service as service


def test_daily_code_search_includes_index_when_stock_universe_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(
        service,
        "_load_stock_universe_records",
        lambda: [
            {
                "code": "301469.SZ",
                "name": "恒达新材",
                "pinyin_initials": "HDXC",
                "name_pinyin_aliases": (),
            }
        ],
    )
    monkeypatch.setattr(service, "_load_etf_universe_records", lambda: [])
    monkeypatch.setattr(
        service,
        "_load_index_universe_records",
        lambda: [
            {
                "code": "881121.THS",
                "name": "医药",
                "pinyin_initials": "YY",
                "name_pinyin_aliases": ("YIYAO",),
                "security_type": "index",
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "get_index_market_code_set",
        lambda: {"000001.SH", "881121.THS"},
    )

    result = service.search_market_codes(
        "881121",
        interval="1day",
        base_path=str(tmp_path),
    )

    assert result["codes"] == ["881121.THS"]
    assert result["items"][0]["security_type"] == "index"

    assert service.search_market_codes(
        "医药", interval="1day", base_path=str(tmp_path)
    )["codes"] == ["881121.THS"]
    assert service.search_market_codes(
        "YY", interval="1day", base_path=str(tmp_path)
    )["codes"] == ["881121.THS"]
