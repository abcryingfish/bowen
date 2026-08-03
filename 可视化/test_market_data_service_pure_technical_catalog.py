from __future__ import annotations

import json

import market_data_service as service


def test_signal_factor_list_merges_pure_technical_chinese_metadata(tmp_path):
    factor_ids = ["MACD_golden_cross", "RSI_oversold_signal"]
    for factor_id in factor_ids:
        (tmp_path / f"factor={factor_id}").mkdir()

    meta_dir = tmp_path / "_meta"
    meta_dir.mkdir()
    (meta_dir / "pure_technical_factor_catalog_cache.json").write_text(
        json.dumps(
            {
                "factor_ids": factor_ids,
                "factor_labels": {
                    "MACD_golden_cross": "MACD_金叉",
                    "RSI_oversold_signal": "RSI_超卖信号",
                },
                "groups": [
                    {
                        "group_id": "pure_technical_macd",
                        "group_name": "纯技术-MACD",
                        "indicator": "MACD",
                        "children": ["MACD_golden_cross"],
                    },
                    {
                        "group_id": "pure_technical_rsi",
                        "group_name": "纯技术-RSI",
                        "indicator": "RSI",
                        "children": ["RSI_oversold_signal"],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = service.list_signal_factors(base_path=str(tmp_path), refresh=True)

    assert result["factor_labels"]["MACD_golden_cross"] == "MACD_金叉"
    assert result["factor_labels"]["RSI_oversold_signal"] == "RSI_超卖信号"
    pure_groups = {
        group["group_id"]: group
        for group in result["groups"]
        if group["group_id"].startswith("pure_technical_")
    }
    assert pure_groups["pure_technical_macd"]["children"] == ["MACD_golden_cross"]
    assert pure_groups["pure_technical_rsi"]["children"] == ["RSI_oversold_signal"]
