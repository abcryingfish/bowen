"""对五类状态标签应用无未来函数的两日确认过滤。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
import polars as pl


DEFAULT_INPUT = Path("outputs/sector_peak_valley_ml/stage_an_state_labels_5class/sector_state_labels.parquet")
DEFAULT_OUTPUT = Path("outputs/sector_peak_valley_ml/stage_ao_state_labels_confirmed_5class")
HORIZONS = ("ultra_short", "5d", "20d")
STATE_CODE = {
    "波谷看涨": 1,
    "波峰看跌": 2,
    "双向高波": 3,
    "横盘看涨": 4,
    "横盘看跌": 5,
}


def sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confirm_two_days(frame: pd.DataFrame, state_column: str) -> pd.Series:
    """状态变更连续出现两次才切换；首个观测沿用原始状态。"""
    result = pd.Series(index=frame.index, dtype="string")
    for _, group in frame.sort_values(["htsc_code", "time"]).groupby("htsc_code", sort=False):
        raw = group[state_column].astype("string").tolist()
        if not raw:
            continue
        effective = [raw[0]]
        for index in range(1, len(raw)):
            if raw[index] == effective[-1]:
                effective.append(effective[-1])
            elif index >= 2 and raw[index] == raw[index - 1]:
                effective.append(raw[index])
            else:
                effective.append(effective[-1])
        result.loc[group.index] = effective
    return result


def run(*, input_path: Path = DEFAULT_INPUT, output_path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    frame = pd.read_parquet(input_path)
    required = {"htsc_code", "time", "sector_family", *(f"state_{horizon}" for horizon in HORIZONS), "state_consensus"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"状态标签缺少字段: {sorted(missing)}")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame.duplicated(["htsc_code", "time"]).any():
        raise ValueError("状态标签存在重复主键")
    result = frame.copy()
    for horizon in HORIZONS:
        result[f"state_{horizon}"] = confirm_two_days(result, f"state_{horizon}")
        result[f"state_code_{horizon}"] = result[f"state_{horizon}"].map(STATE_CODE).astype("Int64")
    # 共识重新由过滤后的三个周期多数票构造；同票时保留原共识，确保稳定且可复现。
    vote_columns = [f"state_{horizon}" for horizon in HORIZONS]
    result["state_consensus"] = result[vote_columns].mode(axis=1).iloc[:, 0]
    result["state_consensus_code"] = result["state_consensus"].map(STATE_CODE).astype("Int64")
    result["state_consensus_agreement"] = sum(result[column].eq(result["state_consensus"]).astype(int) for column in vote_columns) / len(vote_columns)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / "sector_state_labels_confirmed.parquet"
    pl.from_pandas(result, include_index=False).write_parquet(output_file, compression="zstd")
    manifest = {"version": "v2_five_state_confirm_two_days", "input": str(input_path), "input_sha256": sha256_file(input_path), "output": str(output_file), "output_sha256": sha256_file(output_file), "rows": int(len(result)), "confirmation_rule": "state change becomes effective after two consecutive raw observations", "future_data_used": False}
    (output_path / "confirmed_state_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成两日确认版板块状态标签")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    run(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
