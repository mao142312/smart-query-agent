from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "AI意图驱动业务流程.png"
W, H = 1800, 3800
BG, NODE, AI, DEC, FIX, EDGE, TEXT = "#0a0d12", "#f7f8fa", "#e4f0ff", "#fff3cc", "#fff7e8", "#929cab", "#121827"

def ft(size, bold=False):
    return ImageFont.truetype(f"C:/Windows/Fonts/{'msyhbd.ttc' if bold else 'msyh.ttc'}", size)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
title, body, small = ft(38, True), ft(27), ft(24, True)

def text_center(rect, lines):
    x1,y1,x2,y2=rect; hs=[]
    for i,s in enumerate(lines):
        f=title if i==0 else body; b=d.textbbox((0,0),s,font=f); hs.append(b[3]-b[1])
    y=(y1+y2-sum(hs)-10*(len(lines)-1))/2
    for i,(s,h) in enumerate(zip(lines,hs)):
        f=title if i==0 else body; b=d.textbbox((0,0),s,font=f)
        d.text(((x1+x2-(b[2]-b[0]))/2,y),s,font=f,fill=TEXT); y+=h+10

def box(cx,cy,w,h,lines,fill=NODE,blue=False):
    r=(cx-w/2,cy-h/2,cx+w/2,cy+h/2); d.rounded_rectangle(r,18,fill=fill,outline="#3378c6" if blue else EDGE,width=4); text_center(r,lines); return r

def diamond(cx,cy,w,h,lines):
    p=[(cx,cy-h/2),(cx+w/2,cy),(cx,cy+h/2),(cx-w/2,cy)]; d.polygon(p,fill=DEC,outline=EDGE,width=4); text_center((cx-w*.32,cy-h*.3,cx+w*.32,cy+h*.3),lines)

def arrow(points,label=None,pos=None):
    import math
    d.line(points,fill=EDGE,width=6,joint="curve"); (x1,y1),(x2,y2)=points[-2:]; a=math.atan2(y2-y1,x2-x1); L=24
    d.polygon([(x2,y2),(x2-L*math.cos(a-.55),y2-L*math.sin(a-.55)),(x2-L*math.cos(a+.55),y2-L*math.sin(a+.55))],fill=EDGE)
    if label and pos: d.text(pos,label,font=small,fill="white")

# Main-line connectors
ys=[190,420,650,870,1090,1320,1560,1790,2010,2240,2460,2680,2910,3140]
for a,b in zip(ys,ys[1:]): arrow([(1000,a+85),(1000,b-85)])
arrow([(860,650),(350,650),(350,830)],"否",(590,610)); arrow([(350,970),(350,1020),(620,1020),(620,420),(650,420)])
arrow([(850,1090),(350,1090),(350,1270)],"否",(590,1050)); arrow([(350,1410),(350,1470),(620,1470),(620,870),(650,870)])
arrow([(850,1560),(350,1560),(350,1740)],"否",(590,1520)); arrow([(350,1880),(350,1940),(620,1940),(620,1320),(650,1320)])
arrow([(870,2240),(350,2240),(350,2420)],"否",(590,2200)); arrow([(350,2560),(350,2620),(620,2620),(620,2010),(650,2010)])
arrow([(1130,3140),(1350,3140),(1350,3370)],"是",(1190,3100)); arrow([(870,3140),(650,3140),(650,3370)],"否",(770,3100))

box(1000,110,760,160,["用户提出业务问题","例如：查询齐鑫涛最近一个月业绩"])
box(1000,420,900,190,["Business Intent Recognizer · AI","提取业务对象 / 指标描述 / 动作 / 时间","维度 / 筛选 / 分组 / 歧义"],AI,True)
diamond(1000,650,500,180,["是否具备可检索条件？"]); box(350,900,560,140,["请求用户澄清","补充条件或消除歧义"],FIX)
box(1000,870,820,160,["Structured Retrieval Query","生成指标线索 / 实体 / 动作 / 时间 / 维度"])
box(1000,1090,900,180,["Knowledge Retrieval","根据结构化意图检索公司知识库","返回 Top N 指标 / 维度 / 业务口径 / 数据源"],AI,True)
diamond(1000,1320,500,180,["Top N 候选知识可靠？"]); box(350,1340,560,140,["检索修复","扩展召回 / 调整查询 / 请求澄清"],FIX)
box(1000,1560,940,190,["Grounded Logical Plan Generator · AI","融合原问题 + 结构化意图 + Top N 知识","生成指标 / 时间 / 过滤 / 分组 / 计算计划"],AI,True)
diamond(1000,1790,500,180,["逻辑计划完整","且符合知识口径？"]); box(350,1810,560,140,["计划修复","重新消歧 / 检索知识 / 调整计划"],FIX)
box(1000,2010,700,150,["SQL Generator","根据已校验逻辑计划生成只读 SQL"])
box(1000,2240,820,170,["SQL Validator","白名单表 / 强制过滤 / 时间范围 / LIMIT"])
diamond(1000,2460,480,170,["SQL 是否通过？"]); box(350,2490,560,140,["SQL 修复 / 重试","记录反馈并重新生成"],FIX)
box(1000,2680,700,150,["Execute + Result Validator","执行 SQL，并检查非空、完整性和业务范围"])
box(1000,2910,720,150,["Answer Generator","根据查询结果与业务口径生成自然语言回答"])
diamond(1000,3140,480,170,["综合可信度达标？"])
box(650,3450,560,150,["不可靠处理","请求澄清或返回 unreliable"],"#f8d7da")
box(1350,3450,520,150,["返回可靠答案","status = success"],"#d8efcf")
img.save(OUT,quality=95)
print(OUT)
