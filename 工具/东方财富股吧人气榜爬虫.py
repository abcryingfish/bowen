from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


CDN_URL = "https://gbcdn.dfcfw.com/rank/popularityList.js"
AES_KEY = hashlib.md5("getUtilsFromFile".encode("utf-8")).hexdigest().encode("utf-8")
AES_IV = b"getClassFromFile"
MARKET_LABELS = {0: "A股", 1: "港股", 2: "美股"}
SORT_LABELS = {0: "热门排行", 1: "飙升排行"}
CSV_COLUMNS = [
    "市场",
    "榜单",
    "页码",
    "股票代码",
    "当前排名",
    "排名变化",
    "更新时间",
    "老股民占比",
    "新股民占比",
    "历史排名",
]


def _gf_mul(left: int, right: int) -> int:
    result = 0
    for _ in range(8):
        if right & 1:
            result ^= left
        high_bit = left & 0x80
        left = (left << 1) & 0xFF
        if high_bit:
            left ^= 0x1B
        right >>= 1
    return result


def _gf_pow(value: int, power: int) -> int:
    result = 1
    while power:
        if power & 1:
            result = _gf_mul(result, value)
        value = _gf_mul(value, value)
        power >>= 1
    return result


def _rotl(byte: int, shift: int) -> int:
    return ((byte << shift) | (byte >> (8 - shift))) & 0xFF


def _build_sboxes() -> tuple[list[int], list[int]]:
    sbox = [0] * 256
    inv_sbox = [0] * 256
    for value in range(256):
        inverse = 0 if value == 0 else _gf_pow(value, 254)
        subbed = inverse ^ _rotl(inverse, 1) ^ _rotl(inverse, 2) ^ _rotl(inverse, 3) ^ _rotl(inverse, 4) ^ 0x63
        sbox[value] = subbed
        inv_sbox[subbed] = value
    return sbox, inv_sbox


SBOX, INV_SBOX = _build_sboxes()
RCON = [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand_key(key: bytes) -> list[list[int]]:
    if len(key) != 32:
        raise ValueError("AES-256 key 必须是 32 字节")
    nk = 8
    nr = 14
    words = [list(key[index : index + 4]) for index in range(0, len(key), 4)]
    for index in range(nk, 4 * (nr + 1)):
        temp = words[index - 1].copy()
        if index % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [SBOX[item] for item in temp]
            temp[0] ^= RCON[index // nk]
        elif index % nk == 4:
            temp = [SBOX[item] for item in temp]
        words.append([words[index - nk][offset] ^ temp[offset] for offset in range(4)])
    round_keys: list[list[int]] = []
    for round_index in range(nr + 1):
        key_block: list[int] = []
        for word in words[round_index * 4 : (round_index + 1) * 4]:
            key_block.extend(word)
        round_keys.append(key_block)
    return round_keys


def _add_round_key(state: list[int], round_key: list[int]) -> None:
    for index, value in enumerate(round_key):
        state[index] ^= value


def _inv_sub_bytes(state: list[int]) -> None:
    for index, value in enumerate(state):
        state[index] = INV_SBOX[value]


def _inv_shift_rows(state: list[int]) -> None:
    for row in range(1, 4):
        values = [state[row + 4 * column] for column in range(4)]
        values = values[-row:] + values[:-row]
        for column, value in enumerate(values):
            state[row + 4 * column] = value


def _inv_mix_columns(state: list[int]) -> None:
    for column in range(4):
        offset = 4 * column
        a0, a1, a2, a3 = state[offset : offset + 4]
        state[offset] = _gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9)
        state[offset + 1] = _gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13)
        state[offset + 2] = _gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11)
        state[offset + 3] = _gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14)


def _decrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    state = list(block)
    _add_round_key(state, round_keys[14])
    for round_index in range(13, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, round_keys[round_index])
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, round_keys[0])
    return bytes(state)


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("解密结果为空")
    padding = data[-1]
    if padding < 1 or padding > 16 or data[-padding:] != bytes([padding]) * padding:
        raise ValueError("PKCS7 填充校验失败，可能是接口加密参数已变化")
    return data[:-padding]


def aes_256_cbc_decrypt(ciphertext: bytes, key: bytes = AES_KEY, iv: bytes = AES_IV) -> bytes:
    if len(iv) != 16:
        raise ValueError("AES-CBC IV 必须是 16 字节")
    if len(ciphertext) % 16 != 0:
        raise ValueError("密文长度必须是 16 的倍数")
    round_keys = _expand_key(key)
    previous = iv
    plaintext = bytearray()
    for offset in range(0, len(ciphertext), 16):
        block = ciphertext[offset : offset + 16]
        decrypted = _decrypt_block(block, round_keys)
        plaintext.extend(left ^ right for left, right in zip(decrypted, previous))
        previous = block
    return _pkcs7_unpad(bytes(plaintext))


def extract_popularity_payload(script_text: str) -> str:
    match = re.search(r"var\s+popularityList\s*=\s*'([^']+)'", script_text)
    if not match:
        raise ValueError("没有在脚本中找到 popularityList 字段")
    return match.group(1)


def decrypt_popularity_payload(payload: str) -> list[dict[str, Any]]:
    decrypted = aes_256_cbc_decrypt(base64.b64decode(payload))
    data = json.loads(decrypted.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("解密后的数据不是列表")
    return data


def fetch_rank_page(
    market_type: int,
    sort_type: int,
    page: int,
    session: requests.Session | None = None,
    timeout: int = 15,
) -> list[dict[str, Any]]:
    client = session or requests.Session()
    params = {
        "type": market_type,
        "sort": sort_type,
        "page": page,
        "m": datetime.now().minute,
    }
    response = client.get(
        CDN_URL,
        params=params,
        timeout=timeout,
        headers={
            "Referer": "https://guba.eastmoney.com/rank/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    response.raise_for_status()
    payload = extract_popularity_payload(response.text)
    return decrypt_popularity_payload(payload)


def flatten_rank_row(row: dict[str, Any], market_type: int, sort_type: int, page: int) -> dict[str, Any]:
    history = row.get("history") or []
    return {
        "市场": MARKET_LABELS.get(market_type, str(market_type)),
        "榜单": SORT_LABELS.get(sort_type, str(sort_type)),
        "页码": page,
        "股票代码": row.get("code", ""),
        "当前排名": row.get("rankNumber", ""),
        "排名变化": row.get("changeNumber", ""),
        "更新时间": row.get("exactTime", ""),
        "老股民占比": row.get("ironsFans", ""),
        "新股民占比": row.get("newFans", ""),
        "历史排名": json.dumps(history, ensure_ascii=False, separators=(",", ":")),
    }


def crawl_rank(market_type: int, sort_type: int, pages: int, sleep_sec: float) -> list[dict[str, Any]]:
    session = requests.Session()
    rows: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        page_rows = fetch_rank_page(market_type, sort_type, page, session=session)
        rows.extend(flatten_rank_row(row, market_type, sort_type, page) for row in page_rows)
        if page < pages and sleep_sec > 0:
            time.sleep(sleep_sec)
    return rows


def save_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_json(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="爬取东方财富股吧人气榜数据")
    parser.add_argument("--market", choices=["a", "hk", "us"], default="a", help="市场：a=A股，hk=港股，us=美股")
    parser.add_argument("--sort", choices=["hot", "up"], default="hot", help="榜单：hot=热门排行，up=飙升排行")
    parser.add_argument("--pages", type=int, default=1, help="爬取页数，默认 1")
    parser.add_argument("--sleep-sec", type=float, default=0.5, help="翻页间隔秒数，默认 0.5")
    parser.add_argument("--format", choices=["csv", "json"], default="csv", help="输出格式")
    parser.add_argument(
        "--output",
        default="outputs/eastmoney_guba_rank.csv",
        help="输出文件路径，CSV 使用 utf-8-sig 避免 Excel 中文乱码",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market_type = {"a": 0, "hk": 1, "us": 2}[args.market]
    sort_type = {"hot": 0, "up": 1}[args.sort]
    rows = crawl_rank(market_type, sort_type, args.pages, args.sleep_sec)
    output_path = Path(args.output)
    if args.format == "json":
        save_json(rows, output_path)
    else:
        save_csv(rows, output_path)
    print(f"已保存 {len(rows)} 条数据到 {output_path}")


if __name__ == "__main__":
    main()
