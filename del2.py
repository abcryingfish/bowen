# -*- coding: utf-8 -*-
"""
两融数据探测脚本。

用途：
1. 连接 XtTrader 信用账号；
2. 查询融资余额、融券负债、负债合约、两融标的、可融券数量、担保品、普通柜台资金/持仓；
3. 把所有原始字段尽量完整输出到桌面，便于后续挑字段做正式功能。

运行前可按需设置环境变量：
    QMT_USERDATA_MINI      miniQMT 的 userdata_mini 路径
    XT_CREDIT_ACCOUNT      信用账号资金号
    XT_STOCK_ACCOUNT       普通股票账号资金号，未设置时复用信用账号

如果不设置账号，脚本会先用 query_account_infos() 尝试自动发现 CREDIT 账号。
"""

import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount
except Exception as import_error:
    XtQuantTrader = None
    StockAccount = None
    IMPORT_ERROR = import_error
else:
    IMPORT_ERROR = None


DEFAULT_QMT_PATHS = [
    r"D:\迅投极速交易终端 睿智融科版\userdata_mini",
    r"C:\迅投极速交易终端 睿智融科版\userdata_mini",
    r"D:\国金证券QMT交易端\userdata_mini",
    r"C:\国金证券QMT交易端\userdata_mini",
    r"D:\QMT\userdata_mini",
    r"C:\QMT\userdata_mini",
]


QUERY_PLAN = [
    {
        "name": "credit_detail",
        "title": "信用资产_融资余额核心",
        "method": "query_credit_detail",
        "account_kind": "credit",
    },
    {
        "name": "stk_compacts",
        "title": "负债合约_逐合约融资融券明细",
        "method": "query_stk_compacts",
        "account_kind": "credit",
    },
    {
        "name": "credit_subjects",
        "title": "融资融券标的",
        "method": "query_credit_subjects",
        "account_kind": "credit",
    },
    {
        "name": "credit_slo_code",
        "title": "可融券数据",
        "method": "query_credit_slo_code",
        "account_kind": "credit",
    },
    {
        "name": "credit_assure",
        "title": "标的担保品",
        "method": "query_credit_assure",
        "account_kind": "credit",
    },
    {
        "name": "com_fund_credit_account",
        "title": "普通柜台资金_信用账号",
        "method": "query_com_fund",
        "account_kind": "credit",
    },
    {
        "name": "com_position_credit_account",
        "title": "普通柜台持仓_信用账号",
        "method": "query_com_position",
        "account_kind": "credit",
    },
    {
        "name": "com_fund_stock_account",
        "title": "普通柜台资金_普通账号",
        "method": "query_com_fund",
        "account_kind": "stock",
    },
    {
        "name": "com_position_stock_account",
        "title": "普通柜台持仓_普通账号",
        "method": "query_com_position",
        "account_kind": "stock",
    },
    {
        "name": "stock_asset_credit_account",
        "title": "证券资产_信用账号",
        "method": "query_stock_asset",
        "account_kind": "credit",
    },
    {
        "name": "stock_positions_credit_account",
        "title": "证券持仓_信用账号",
        "method": "query_stock_positions",
        "account_kind": "credit",
    },
    {
        "name": "stock_orders_credit_account",
        "title": "当日委托_信用账号",
        "method": "query_stock_orders",
        "account_kind": "credit",
    },
    {
        "name": "stock_trades_credit_account",
        "title": "当日成交_信用账号",
        "method": "query_stock_trades",
        "account_kind": "credit",
    },
]


FIELD_NOTES = {
    "m_dBalance": "总资产",
    "m_dAvailable": "可用金额",
    "m_dMarketValue": "总市值",
    "m_dTotalDebt": "总负债",
    "m_dEnableBailBalance": "可用保证金",
    "m_dPerAssurescaleValue": "维持担保比例",
    "m_dAssureAsset": "净资产",
    "m_dFinDebt": "融资负债/融资余额核心字段",
    "m_dFinDealAvl": "融资本金",
    "m_dFinFee": "融资息费",
    "m_dSloDebt": "融券负债",
    "m_dSloMarketValue": "融券市值",
    "m_dSloFee": "融券息费",
    "m_dFinMaxQuota": "融资授信额度",
    "m_dFinEnableQuota": "融资可用额度",
    "m_dFinUsedQuota": "融资冻结额度",
    "m_dSloMaxQuota": "融券授信额度",
    "m_dSloEnableQuota": "融券可用额度",
    "m_dSloUsedQuota": "融券冻结额度",
    "m_dSloSellBalance": "融券卖出资金",
    "m_dUsedSloSellBalance": "已用融券卖出资金",
    "m_dSurplusSloSellBalance": "剩余融券卖出资金",
    "real_compact_balance": "未还合约金额",
    "real_compact_fare": "未还合约息费",
    "business_balance": "合约金额",
    "businessFare": "合约息费",
    "business_vol": "合约证券数量",
    "real_compact_vol": "未还合约数量",
    "compact_type": "合约类型",
    "fin_status": "融资状态",
    "slo_status": "融券状态",
    "fin_ratio": "融资保证金比例",
    "slo_ratio": "融券保证金比例",
    "enable_amount": "融券可融数量",
    "assure_status": "是否可做担保",
    "assure_ratio": "担保品折算比例",
}

OUTPUT_ENCODING = "gbk"


def setup_console_encoding():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def safe_repr(value):
    try:
        return repr(value)
    except Exception as error:
        return "<repr_error:%s>" % error.__class__.__name__


def to_plain(value, depth=0):
    if depth >= 5:
        return safe_repr(value)

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (datetime, Path)):
        return str(value)

    if isinstance(value, dict):
        return {str(k): to_plain(v, depth + 1) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_plain(item, depth + 1) for item in value]

    result = {}
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        for key, item in attrs.items():
            if not str(key).startswith("_"):
                result[str(key)] = to_plain(item, depth + 1)

    for name in dir(value):
        if name.startswith("_") or name in result:
            continue
        try:
            item = getattr(value, name)
        except Exception:
            continue
        if callable(item):
            continue
        result[name] = to_plain(item, depth + 1)

    if result:
        result["__class__"] = value.__class__.__name__
        return result

    return safe_repr(value)


def as_rows(value):
    plain = to_plain(value)
    if plain is None:
        return []
    if isinstance(plain, list):
        return [item if isinstance(item, dict) else {"value": item} for item in plain]
    if isinstance(plain, dict):
        return [plain]
    return [{"value": plain}]


def find_qmt_userdata_path():
    env_path = os.environ.get("QMT_USERDATA_MINI", "").strip()
    if env_path and Path(env_path).exists():
        return env_path

    for path in DEFAULT_QMT_PATHS:
        if Path(path).exists():
            return path

    for drive in ("D:\\", "C:\\"):
        root = Path(drive)
        try:
            first_level = list(root.glob("*"))
        except Exception:
            first_level = []
        for parent in first_level:
            for candidate in (
                parent / "userdata_mini",
                parent / "bin.x64" / "userdata_mini",
                parent / "userdata" / "userdata_mini",
            ):
                if candidate.is_dir():
                    return str(candidate)

    return env_path or DEFAULT_QMT_PATHS[0]


def get_qmt_context_account():
    return str(globals().get("account", "") or "").strip()


def make_session_id():
    return int(datetime.now().strftime("%H%M%S"))


def connect_trader(path):
    trader = XtQuantTrader(path, make_session_id())
    trader.start()
    connect_result = trader.connect()
    return trader, connect_result


def account_type_text(value):
    text = str(value).upper()
    if text in {"CREDIT", "2"}:
        return "CREDIT"
    if text in {"STOCK", "0"}:
        return "STOCK"
    return text


def read_account_info(item):
    data = to_plain(item)
    if not isinstance(data, dict):
        return {}
    return data


def discover_accounts(trader):
    accounts = []
    try:
        infos = trader.query_account_infos()
    except Exception as error:
        return [], "query_account_infos异常: %s" % error

    for item in infos or []:
        data = read_account_info(item)
        account_id = str(data.get("account_id", "") or "").strip()
        account_type = account_type_text(data.get("account_type", data.get("broker_type", "")))
        if account_id:
            accounts.append({"account_id": account_id, "account_type": account_type, "raw": data})
    return accounts, ""


def pick_account_id(accounts, wanted_type):
    wanted_type = wanted_type.upper()
    for item in accounts:
        if item.get("account_type") == wanted_type:
            return item.get("account_id", "")
    return ""


def build_accounts(trader):
    discovered, discover_error = discover_accounts(trader)
    context_account = get_qmt_context_account()

    credit_id = (
        os.environ.get("XT_CREDIT_ACCOUNT", "").strip()
        or pick_account_id(discovered, "CREDIT")
        or context_account
    )
    stock_id = (
        os.environ.get("XT_STOCK_ACCOUNT", "").strip()
        or pick_account_id(discovered, "STOCK")
        or credit_id
    )

    credit_account = StockAccount(credit_id, "CREDIT") if credit_id else None
    stock_account = StockAccount(stock_id, "STOCK") if stock_id else None

    return {
        "credit": credit_account,
        "stock": stock_account,
        "credit_id": credit_id,
        "stock_id": stock_id,
        "discovered": discovered,
        "discover_error": discover_error,
    }


def query_one(trader, method_name, account):
    if account is None:
        return {"ok": False, "error": "账号为空，跳过查询", "data": None}
    if not hasattr(trader, method_name):
        return {"ok": False, "error": "当前xtquant版本没有方法: %s" % method_name, "data": None}

    try:
        data = getattr(trader, method_name)(account)
        return {"ok": True, "error": "", "data": data}
    except Exception as error:
        return {"ok": False, "error": "%s: %s" % (error.__class__.__name__, error), "data": None}


def write_json(path, data):
    with open(path, "w", encoding=OUTPUT_ENCODING, errors="replace") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def write_csv(path, rows):
    normalized_rows = []
    columns = []
    seen = set()

    for row in rows:
        if not isinstance(row, dict):
            row = {"value": row}
        flat = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                flat[key] = json.dumps(value, ensure_ascii=False, default=str)
            else:
                flat[key] = value
            if key not in seen:
                seen.add(key)
                columns.append(key)
        normalized_rows.append(flat)

    if "字段说明" not in seen:
        columns.append("字段说明")

    with open(path, "w", encoding=OUTPUT_ENCODING, errors="replace", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in normalized_rows:
            row = dict(row)
            for key in columns:
                if key not in row:
                    row[key] = ""
            note_parts = []
            for key in columns:
                if key in FIELD_NOTES and row.get(key) not in ("", None):
                    note_parts.append("%s=%s" % (key, FIELD_NOTES[key]))
            row["字段说明"] = "；".join(note_parts)
            writer.writerow(row)


def make_output_dir():
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path(r"C:\Users\Administrator\Desktop")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = desktop / ("两融测试输出_" + timestamp)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def build_finance_balance_summary(result_map):
    rows = as_rows(result_map.get("credit_detail", {}).get("plain_data"))
    summary_rows = []
    for row in rows:
        summary_rows.append({
            "资金账号": row.get("account_id", ""),
            "总资产_m_dBalance": row.get("m_dBalance", ""),
            "可用金额_m_dAvailable": row.get("m_dAvailable", ""),
            "总市值_m_dMarketValue": row.get("m_dMarketValue", ""),
            "总负债_m_dTotalDebt": row.get("m_dTotalDebt", ""),
            "净资产_m_dAssureAsset": row.get("m_dAssureAsset", ""),
            "维持担保比例_m_dPerAssurescaleValue": row.get("m_dPerAssurescaleValue", ""),
            "融资余额_m_dFinDebt": row.get("m_dFinDebt", ""),
            "融资本金_m_dFinDealAvl": row.get("m_dFinDealAvl", ""),
            "融资息费_m_dFinFee": row.get("m_dFinFee", ""),
            "融资授信额度_m_dFinMaxQuota": row.get("m_dFinMaxQuota", ""),
            "融资可用额度_m_dFinEnableQuota": row.get("m_dFinEnableQuota", ""),
            "融资冻结额度_m_dFinUsedQuota": row.get("m_dFinUsedQuota", ""),
            "融券负债_m_dSloDebt": row.get("m_dSloDebt", ""),
            "融券市值_m_dSloMarketValue": row.get("m_dSloMarketValue", ""),
            "融券息费_m_dSloFee": row.get("m_dSloFee", ""),
            "融券授信额度_m_dSloMaxQuota": row.get("m_dSloMaxQuota", ""),
            "融券可用额度_m_dSloEnableQuota": row.get("m_dSloEnableQuota", ""),
            "融券冻结额度_m_dSloUsedQuota": row.get("m_dSloUsedQuota", ""),
            "融券卖出资金_m_dSloSellBalance": row.get("m_dSloSellBalance", ""),
            "已用融券卖出资金_m_dUsedSloSellBalance": row.get("m_dUsedSloSellBalance", ""),
            "剩余融券卖出资金_m_dSurplusSloSellBalance": row.get("m_dSurplusSloSellBalance", ""),
        })
    return summary_rows


def build_compact_summary(result_map):
    rows = as_rows(result_map.get("stk_compacts", {}).get("plain_data"))
    summary_rows = []
    for row in rows:
        summary_rows.append({
            "资金账号": row.get("account_id", ""),
            "证券代码": row.get("instrument_id", ""),
            "市场": row.get("exchange_id", ""),
            "合约编号": row.get("compact_id", ""),
            "合约类型": row.get("compact_type", ""),
            "头寸来源": row.get("cashgroup_prop", ""),
            "开仓日期": row.get("open_date", ""),
            "到期日": row.get("ret_end_date", ""),
            "合约证券数量": row.get("business_vol", ""),
            "未还合约数量": row.get("real_compact_vol", ""),
            "合约金额": row.get("business_balance", ""),
            "合约息费": row.get("businessFare", ""),
            "未还合约金额": row.get("real_compact_balance", ""),
            "未还合约息费": row.get("real_compact_fare", ""),
            "已还金额": row.get("repaid_balance", ""),
            "已还息费": row.get("repaid_fare", ""),
            "定位串": row.get("position_str", ""),
        })
    return summary_rows


def write_summary_txt(path, metadata, result_map):
    lines = []
    lines.append("两融测试输出摘要")
    lines.append("生成时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("QMT路径: %s" % metadata.get("qmt_path", ""))
    lines.append("连接返回值: %s" % metadata.get("connect_result", ""))
    lines.append("信用账号: %s" % metadata.get("credit_id", ""))
    lines.append("普通账号: %s" % metadata.get("stock_id", ""))
    lines.append("")
    lines.append("关键字段说明:")
    for key, note in FIELD_NOTES.items():
        lines.append("- %s: %s" % (key, note))
    lines.append("")
    lines.append("查询结果:")
    for name, result in result_map.items():
        rows = as_rows(result.get("plain_data"))
        lines.append("- %s: ok=%s, rows=%s, error=%s" % (
            result.get("title", name),
            result.get("ok"),
            len(rows),
            result.get("error", ""),
        ))

    with open(path, "w", encoding=OUTPUT_ENCODING, errors="replace") as file:
        file.write("\n".join(lines))


def main():
    setup_console_encoding()
    if IMPORT_ERROR is not None:
        print("导入 xtquant 失败:", IMPORT_ERROR)
        return 1

    qmt_path = find_qmt_userdata_path()
    output_dir = make_output_dir()
    print("输出目录:", output_dir)
    print("QMT userdata_mini:", qmt_path)

    trader, connect_result = connect_trader(qmt_path)
    print("连接返回值:", connect_result)

    account_info = build_accounts(trader)
    print("信用账号:", account_info.get("credit_id") or "<未找到>")
    print("普通账号:", account_info.get("stock_id") or "<未找到>")

    result_map = {}
    metadata = {
        "qmt_path": qmt_path,
        "connect_result": connect_result,
        "credit_id": account_info.get("credit_id", ""),
        "stock_id": account_info.get("stock_id", ""),
        "discovered_accounts": account_info.get("discovered", []),
        "discover_error": account_info.get("discover_error", ""),
    }
    write_json(output_dir / "00_账号和连接信息.json", metadata)

    for item in QUERY_PLAN:
        account_obj = account_info.get(item["account_kind"])
        result = query_one(trader, item["method"], account_obj)
        plain_data = to_plain(result["data"])
        result_map[item["name"]] = {
            "title": item["title"],
            "method": item["method"],
            "ok": result["ok"],
            "error": result["error"],
            "plain_data": plain_data,
        }

        rows = as_rows(plain_data)
        json_path = output_dir / ("%s_%s.json" % (item["name"], item["title"]))
        csv_path = output_dir / ("%s_%s.csv" % (item["name"], item["title"]))
        write_json(json_path, result_map[item["name"]])
        write_csv(csv_path, rows)
        print("%s: ok=%s rows=%s error=%s" % (item["title"], result["ok"], len(rows), result["error"]))

    write_csv(output_dir / "融资余额汇总_credit_detail.csv", build_finance_balance_summary(result_map))
    write_csv(output_dir / "负债合约汇总_stk_compacts.csv", build_compact_summary(result_map))
    write_json(output_dir / "全部结果汇总.json", {"metadata": metadata, "results": result_map})
    write_summary_txt(output_dir / "README_先看这个.txt", metadata, result_map)

    print("完成输出:", output_dir)
    time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
