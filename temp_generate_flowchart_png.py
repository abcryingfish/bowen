# -*- coding: utf-8 -*-
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parent / "project_flowchart_2026_06.png"
W, H = 1280, 720


def make_font(size):
    for path in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), "#f5f7fb")
d = ImageDraw.Draw(img)

f_title = make_font(36)
f_sub = make_font(16)
f_range = make_font(18)
f_date = make_font(17)
f_h2 = make_font(23)
f_body = make_font(16)
f_tag = make_font(14)
f_arrow = make_font(34)

margin = 52
d.rectangle([0, 0, W, H], fill="#f5f7fb")
d.rectangle([0, 0, W, 112], fill="#ffffff")
d.text((margin, 34), "项目推进流程图", fill="#10213d", font=f_title)
d.text((margin, 82), "按周拆分任务重点，覆盖测试、实盘隔离、前后端联调与模拟实盘。", fill="#5d6b82", font=f_sub)
d.rounded_rectangle([984, 42, 1228, 84], radius=8, fill="#ffffff", outline="#d4ddec", width=1)
d.text((1001, 52), "2026年6月8日 - 6月28日", fill="#24476f", font=f_range)
d.line([margin, 112, W - margin, 112], fill="#dce4f2", width=2)

steps = [
    (
        "2026年6月8日 - 2026年6月14日",
        "测试与数据基础准备",
        [
            "简单测试，验证基础流程可跑通。",
            "找了16年的分钟数据。",
            "数据接口从 Insight 转 qmt，包含部分市值类分钟数据。",
            "研究分时价差逻辑，后续有空切分与处理数据。",
            "处理数据一致性问题。",
            "日内增量信息存入 SQLite。",
            "处理日内数据合并与前端显示问题。",
        ],
        "阶段一：数据底座",
    ),
    (
        "2026年6月15日 - 2026年6月21日",
        "实盘与回测算法隔离",
        [
            "隔离实盘与回测算法。",
            "确认实盘出的信号是否需要多一份备份。",
            "优化实盘交易信号算法。",
            "设计预实盘数据读取方案。",
            "设计实盘操作界面。",
            "优化机器出信号时的主观判断效率。",
        ],
        "阶段二：交易链路",
    ),
    (
        "2026年6月22日 - 2026年6月28日",
        "前后端联调与模拟实盘",
        [
            "出页面，整理页面开发中需要考虑的事项。",
            "确认前端发送信号和后端数据一致性。",
            "设置一定风控，避免误操作。",
            "模拟实盘，验证完整操作流程。",
        ],
        "阶段三：落地验证",
    ),
]

card_w = 360
card_h = 505
gap = 34
start_x = 70
y = 170
line_y = 152
cx1 = start_x + card_w // 2
cx3 = start_x + 2 * (card_w + gap) + card_w // 2
d.line([cx1, line_y, cx3, line_y], fill="#7ba7d7", width=4)

for i, (date, title, items, tag) in enumerate(steps):
    x = start_x + i * (card_w + gap)
    cx = x + card_w // 2
    d.ellipse([cx - 18, line_y - 18, cx + 18, line_y + 18], fill="#ffffff")
    d.ellipse([cx - 13, line_y - 13, cx + 13, line_y + 13], fill="#2e74b5")
    if i < 2:
        ax = x + card_w + gap // 2
        d.ellipse([ax - 17, line_y - 17, ax + 17, line_y + 17], fill="#2e74b5")
        d.text((ax - 6, line_y - 22), ">", fill="#ffffff", font=f_arrow)

    d.rounded_rectangle([x + 4, y + 8, x + card_w + 4, y + card_h + 8], radius=8, fill="#e6ebf3")
    d.rounded_rectangle([x, y, x + card_w, y + card_h], radius=8, fill="#ffffff", outline="#d7e0ed", width=1)
    d.rounded_rectangle([x + 22, y + 24, x + card_w - 22, y + 66], radius=6, fill="#eaf2fb")

    bbox = d.textbbox((0, 0), date, font=f_date)
    d.text((x + (card_w - (bbox[2] - bbox[0])) / 2, y + 35), date, fill="#174a7c", font=f_date)
    bbox = d.textbbox((0, 0), title, font=f_h2)
    d.text((x + (card_w - (bbox[2] - bbox[0])) / 2, y + 86), title, fill="#10213d", font=f_h2)

    ty = y + 128
    for item in items:
        lines = textwrap.wrap(item, width=18)
        d.ellipse([x + 24, ty + 8, x + 32, ty + 16], fill="#2e74b5")
        for line in lines:
            d.text((x + 44, ty), line, fill="#26364d", font=f_body)
            ty += 24
        ty += 5

    bbox = d.textbbox((0, 0), tag, font=f_tag)
    tw = bbox[2] - bbox[0]
    tx = x + (card_w - tw) / 2
    d.rounded_rectangle([tx - 13, y + card_h - 48, tx + tw + 13, y + card_h - 18], radius=6, fill="#f1f5f9")
    d.text((tx, y + card_h - 41), tag, fill="#526175", font=f_tag)

img.save(OUT)
print(OUT)
