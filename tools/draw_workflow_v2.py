from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "流程图-v2.png"
W, H = 2000, 3600
BG = "#090b10"
NODE = "#f5f7fa"
NODE_ACCENT = "#e9f2ff"
DECISION = "#fff7e8"
EDGE = "#8e99a8"
TEXT = "#111827"
BLUE = "#2774c7"


def font(size: int, bold: bool = False):
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


img = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)
f_title, f_body, f_small = font(42, True), font(31), font(27, True)


def center_text(box, lines, title_lines=1):
    x1, y1, x2, y2 = box
    heights = []
    for i, line in enumerate(lines):
        f = f_title if i < title_lines else f_body
        b = draw.textbbox((0, 0), line, font=f)
        heights.append(b[3] - b[1])
    gap = 12
    y = (y1 + y2 - (sum(heights) + gap * (len(lines) - 1))) / 2
    for i, (line, h) in enumerate(zip(lines, heights)):
        f = f_title if i < title_lines else f_body
        b = draw.textbbox((0, 0), line, font=f)
        draw.text(((x1 + x2 - (b[2] - b[0])) / 2, y), line, fill=TEXT, font=f)
        y += h + gap


def box(cx, cy, width, height, lines, accent=False, title_lines=1):
    b = (cx-width/2, cy-height/2, cx+width/2, cy+height/2)
    draw.rounded_rectangle(b, radius=18, fill=NODE_ACCENT if accent else NODE,
                           outline=BLUE if accent else EDGE, width=4)
    center_text(b, lines, title_lines)
    return b


def diamond(cx, cy, width, height, lines):
    pts = [(cx, cy-height/2), (cx+width/2, cy), (cx, cy+height/2), (cx-width/2, cy)]
    draw.polygon(pts, fill=DECISION, outline=EDGE, width=4)
    b = (cx-width*.34, cy-height*.28, cx+width*.34, cy+height*.28)
    center_text(b, lines, 0)
    return (cx-width/2, cy-height/2, cx+width/2, cy+height/2)


def arrow(points, label=None, label_at=None):
    draw.line(points, fill=EDGE, width=6, joint="curve")
    (x1, y1), (x2, y2) = points[-2], points[-1]
    import math
    angle = math.atan2(y2-y1, x2-x1)
    length, spread = 25, .55
    p1 = (x2-length*math.cos(angle-spread), y2-length*math.sin(angle-spread))
    p2 = (x2-length*math.cos(angle+spread), y2-length*math.sin(angle+spread))
    draw.polygon([(x2, y2), p1, p2], fill=EDGE)
    if label and label_at:
        b = draw.textbbox((0, 0), label, font=f_small)
        pad = 8
        x, y = label_at
        draw.rounded_rectangle((x-pad, y-pad, x+b[2]+pad, y+b[3]+pad), 6, fill=BG)
        draw.text((x, y), label, fill="#f8fafc", font=f_small)


# Coordinates and connectors are defined first so arrows stay behind nodes.
arrow([(1000, 210), (1000, 295)])
arrow([(1000, 485), (1000, 575)])
arrow([(1000, 765), (1000, 865)], "是", (1025, 795))
arrow([(760, 670), (380, 670), (380, 850)], "否", (545, 625))
arrow([(380, 1010), (380, 1080), (720, 1080), (720, 390), (740, 390)])
arrow([(1000, 1045), (1000, 1135)])
arrow([(1000, 1325), (1000, 1425)], "是", (1025, 1355))
arrow([(750, 1230), (390, 1230), (390, 1425)], "否", (560, 1188))
arrow([(390, 1585), (390, 1660), (700, 1660), (700, 955), (740, 955)])
arrow([(1000, 1615), (1000, 1715)])
arrow([(1000, 1905), (1000, 2005)], "是", (1025, 1935))
arrow([(750, 1810), (390, 1810), (390, 2005)], "否", (560, 1768))
arrow([(390, 2165), (390, 2240), (690, 2240), (690, 1810), (740, 1810)])
arrow([(1000, 2195), (1000, 2285)])
arrow([(1000, 2455), (1000, 2545)])
arrow([(1000, 2735), (1000, 2825)], "是", (1025, 2765))
arrow([(750, 2640), (390, 2640), (390, 2825)], "否", (560, 2598))
arrow([(390, 2985), (390, 3050), (690, 3050), (690, 1520), (740, 1520)])
arrow([(1000, 2995), (1000, 3085)])
arrow([(1000, 3255), (1000, 3345)])

# Main path.
box(1000, 120, 760, 180, ["用户提出问题", "例如：查询齐鑫涛最近一个月业绩"], title_lines=1)
box(1000, 390, 820, 190,
    ["Intent Recognizer · 大模型意图识别", "提取指标描述 / 业务对象 / 动作", "时间 / 维度 / 筛选 / 分组 / 歧义"], True)
diamond(1000, 670, 520, 190, ["意图信息是否完整？"])
box(380, 930, 610, 160, ["请求用户澄清", "补充缺失条件或消除歧义"])

box(1000, 955, 850, 180,
    ["Structured Knowledge Retrieval", "使用结构化线索检索知识库", "返回指标 / 维度 / 业务口径 Top N"], True)
diamond(1000, 1230, 520, 190, ["Top N 候选知识是否可靠？"])
box(390, 1505, 620, 160, ["检索修复", "扩展召回词 / 调整检索 / 补充上下文"])

box(1000, 1520, 880, 190,
    ["Logical Plan Generator · 大模型", "融合：原问题 + 结构化意图 + Top N 知识", "生成指标 / 时间 / 过滤 / 分组 / 计算逻辑"], True)
diamond(1000, 1810, 520, 190, ["逻辑计划是否完整", "且符合知识口径？"])
box(390, 2085, 620, 160, ["计划修复", "重新消歧 / 检索知识 / 调整逻辑计划"])

box(1000, 2100, 610, 190, ["SQL Generator", "根据已校验逻辑计划生成 SQL"])
box(1000, 2370, 720, 170, ["SQL Validator", "只读 / 表字段 / 过滤 / 聚合 / 范围检查"])
diamond(1000, 2640, 520, 190, ["SQL 是否通过？"])
box(390, 2905, 620, 160, ["SQL 修复", "分析错误原因并重新规划或生成"])

box(1000, 2910, 610, 170, ["Execute Engine", "执行 SQL"])
box(1000, 3170, 720, 170, ["Result Validator", "执行状态 / 空值 / 完整性 / 合理性检查"])
box(1000, 3430, 760, 170, ["Answer Generator", "基于结果和可信度生成最终回答"])

img.save(OUT, quality=95)
print(OUT)
