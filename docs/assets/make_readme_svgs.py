"""Generate the README header and "how it works" diagrams (English and Chinese).

Run from the repo root after changing any text below:

    python3 docs/assets/make_readme_svgs.py

Colours are Bambu Lab's: green #00AE42 on near-black. The SVGs animate with SMIL, which
GitHub keeps when it shows them as images.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent
GREEN = "#00AE42"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei','Noto Sans CJK SC',Helvetica,Arial,sans-serif"
MONO = "'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"

TEXT = {
    "en": {
        "tag": "AGENT SKILL · BAMBU STUDIO AI",
        "subtitle": "Tell your AI agent what you need. It designs it, checks it, and prints it on your Bambu Lab.",
        "request": "Your Request",
        "stages": [["GET A", "MODEL"], ["MAKE IT", "PRINTABLE"], ["PRINT"]],
        # (icon, title, subtitle, tag in the top-right corner)
        "cards": [
            [("search", "Search Models", "MakerWorld · Printables", "EVERYDAY OBJECT"),
             ("caliper", "Parametric CAD", "exact mm, screw holes", "EXACT PART"),
             ("spark", "AI Generation", "text or photo → 3D", "FIGURINE / PHOTO")],
            [("shield", "Check & Repair", "scale, overhangs, fit", ""),
             ("spools", "Multi-Color", "texture → AMS colors", "OPTIONAL"),
             ("eye", "Preview Render", "see it before slicing", "")],
            [("layers", "Bambu Studio", "you review and slice", ""),
             ("play", "You Press Print", "never the agent", ""),
             ("pulse", "Monitor", "progress + alerts", "READ-ONLY")],
        ],
        "footer": "Made for the Bambu Lab community · by TieGaier",
    },
    "zh": {
        "tag": "AGENT SKILL · 拓竹 AI 打印助手",
        "subtitle": "跟你的 AI 说一句话，它来建模、检查、打印到你的拓竹。",
        "request": "你的需求",
        "stages": [["获取模型"], ["变得可打印"], ["打印"]],
        "cards": [
            [("search", "搜索模型", "MakerWorld · Printables", "日常物件"),
             ("caliper", "参数化 CAD", "精确到毫米、螺丝孔", "精密件"),
             ("spark", "AI 生成", "文字或照片 → 3D", "手办 · 照片")],
            [("shield", "检查与修复", "尺寸、悬垂、能否放下", ""),
             ("spools", "AMS 多色", "贴图 → AMS 配色", "可选"),
             ("eye", "渲染预览", "切片之前先看一眼", "")],
            [("layers", "Bambu Studio", "你来检查、切片", ""),
             ("play", "你点「打印」", "只由你来开始", ""),
             ("pulse", "进度监控", "进度与提醒", "只读")],
        ],
        "footer": "为拓竹社区而做 · by TieGaier",
    },
}

ICONS = {  # 24×24 line icons, drawn in green
    "search": '<circle cx="10" cy="10" r="6.5"/><path d="M15 15l6 6"/>',
    "caliper": '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7.5 12.5l2 2M10.5 9.5l2 2M13.5 6.5l2 2"/>',
    "spark": '<path d="M12 2l2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2z"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.6 8.2-8 9-4.4-.8-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "spools": '<circle cx="7.5" cy="7.5" r="3.5"/><circle cx="16.5" cy="7.5" r="3.5"/>'
              '<circle cx="7.5" cy="16.5" r="3.5"/><circle cx="16.5" cy="16.5" r="3.5"/>',
    "eye": '<path d="M2 12c3-6 17-6 20 0-3 6-17 6-20 0z"/><circle cx="12" cy="12" r="3"/>',
    "layers": '<path d="M12 3l9 4.5-9 4.5-9-4.5z"/><path d="M3 12l9 4.5 9-4.5M3 16.5L12 21l9-4.5"/>',
    "play": '<circle cx="12" cy="12" r="9.5"/><path d="M10 8l6 4-6 4z"/>',
    "pulse": '<path d="M2 12h5l2.5-6 4.5 12 2.5-6H22"/>',
}


def header(lang: str) -> str:
    """Banner: the title is 'printed' layer by layer by a moving nozzle, then the subtitle fades in."""
    t = TEXT[lang]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300" width="1200" height="300" role="img" aria-label="Bambu Lab AI">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#00200F"/><stop offset=".55" stop-color="#030C07"/><stop offset="1" stop-color="#000000"/>
    </linearGradient>
    <radialGradient id="glow" cx=".5" cy=".55" r=".5">
      <stop offset="0" stop-color="{GREEN}" stop-opacity=".28"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/>
    </radialGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
      <path d="M28 0H0V28" fill="none" stroke="{GREEN}" stroke-opacity=".09"/>
    </pattern>
    <radialGradient id="fade" cx=".5" cy=".5" r=".6">
      <stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
    <mask id="gridmask"><rect width="1200" height="300" fill="url(#fade)"/></mask>
    <pattern id="layerlines" width="8" height="5" patternUnits="userSpaceOnUse">
      <rect width="8" height="1.2" fill="#000" fill-opacity=".28"/>
    </pattern>
    <clipPath id="printed">
      <rect x="0" y="72" width="1200" height="108">
        <animate attributeName="y" from="180" to="72" dur="2.6s" fill="freeze" calcMode="spline" keySplines=".3 0 .7 1"/>
        <animate attributeName="height" from="0" to="108" dur="2.6s" fill="freeze" calcMode="spline" keySplines=".3 0 .7 1"/>
      </rect>
    </clipPath>
    <linearGradient id="sweep" x1="0" x2="1">
      <stop offset="0" stop-color="{GREEN}" stop-opacity="0"/><stop offset=".5" stop-color="{GREEN}"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/>
    </linearGradient>
    <clipPath id="frame"><rect width="1200" height="300" rx="24"/></clipPath>
  </defs>
  <g clip-path="url(#frame)">
  <rect width="1200" height="300" fill="url(#bg)"/>
  <rect width="1200" height="300" rx="22" fill="url(#grid)" mask="url(#gridmask)"/>
  <ellipse cx="600" cy="170" rx="520" ry="150" fill="url(#glow)"/>
  <text x="48" y="54" font-family="{MONO}" font-size="15" letter-spacing="3" fill="{GREEN}">● {escape(t["tag"])}</text>
  <text x="1152" y="54" text-anchor="end" font-family="{MONO}" font-size="15" letter-spacing="2" fill="#5E8C6E">SKILL.md</text>
  <g clip-path="url(#printed)" font-family="{FONT}" font-size="96" font-weight="800" text-anchor="middle">
    <text x="600" y="168" fill="#FFFFFF">Bambu Lab <tspan fill="{GREEN}">AI</tspan></text>
    <text x="600" y="168" fill="url(#layerlines)">Bambu Lab AI</text>
  </g>
  <!-- The nozzle is hidden unless animation runs, so a static render shows the finished title. -->
  <g opacity="0">
    <animateTransform attributeName="transform" type="translate" from="0 0" to="0 -108" dur="2.6s" fill="freeze" calcMode="spline" keySplines=".3 0 .7 1"/>
    <animate attributeName="opacity" values="1;1;0" keyTimes="0;.85;1" dur="3s" fill="freeze"/>
    <g>
      <animateTransform attributeName="transform" type="translate" values="300 0;900 0;300 0" dur=".42s" repeatCount="7"/>
      <rect x="-9" y="160" width="18" height="12" rx="2" fill="#D9E8DE"/>
      <path d="M-5 172h10l-5 7z" fill="{GREEN}"/>
      <rect x="-60" y="179" width="120" height="2" fill="url(#sweep)"/>
    </g>
  </g>
  <text x="600" y="226" text-anchor="middle" font-family="{FONT}" font-size="22" fill="#B7D8C1">{escape(t["subtitle"])}
    <animate attributeName="opacity" values="0;0;1" keyTimes="0;.7;1" dur="3.2s" fill="freeze"/>
  </text>
  <rect x="0" y="296" width="1200" height="4" fill="#0B2415"/>
  <rect x="-300" y="296" width="300" height="4" fill="url(#sweep)">
    <animate attributeName="x" from="-300" to="1200" dur="4s" repeatCount="indefinite"/>
  </rect>
  </g>
</svg>
'''


def footer(lang: str) -> str:
    """Closing band: the same black-green as the header, with a light sweeping along the top edge."""
    t = TEXT[lang]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 110" width="1200" height="110" role="img" aria-label="{escape(t["footer"])}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#000000"/><stop offset=".45" stop-color="#030C07"/><stop offset="1" stop-color="#00200F"/>
    </linearGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
      <path d="M28 0H0V28" fill="none" stroke="{GREEN}" stroke-opacity=".07"/>
    </pattern>
    <radialGradient id="glow" cx=".5" cy="1" r=".6">
      <stop offset="0" stop-color="{GREEN}" stop-opacity=".22"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="sweep" x1="0" x2="1">
      <stop offset="0" stop-color="{GREEN}" stop-opacity="0"/><stop offset=".5" stop-color="{GREEN}"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/>
    </linearGradient>
    <clipPath id="frame"><rect width="1200" height="110" rx="24"/></clipPath>
  </defs>
  <g clip-path="url(#frame)">
  <rect width="1200" height="110" fill="url(#bg)"/>
  <rect width="1200" height="110" fill="url(#grid)"/>
  <rect width="1200" height="110" fill="url(#glow)"/>
  <rect x="0" y="0" width="1200" height="3" fill="#0B2415"/>
  <rect x="-300" y="0" width="300" height="3" fill="url(#sweep)">
    <animate attributeName="x" from="1200" to="-300" dur="4s" repeatCount="indefinite"/>
  </rect>
  <g transform="translate(600 58)" text-anchor="middle">
    <text y="0" font-family="{FONT}" font-size="26" font-weight="800" fill="#FFFFFF">Bambu Lab <tspan fill="{GREEN}">AI</tspan></text>
    <text y="28" font-family="{MONO}" font-size="13" letter-spacing="2" fill="#6E9C7E">{escape(t["footer"])}</text>
  </g>
  </g>
</svg>
'''


# Flow diagram layout (viewBox units). One grid: 40 px outer padding, a 120 px stage rail,
# a 24 px gutter, then three 232 px cards with 20 px gaps. Rows are 88 px tall with 64 px
# between them for the connectors.
W, PAD, RAIL_W, GUTTER = 960, 40, 120, 24
CARD_W, CARD_H, GAP = 232, 88, 20
CARDS_X = PAD + RAIL_W + GUTTER                 # 184; the third card ends at 920 = W - PAD
PILL_Y, PILL_H = PAD, 40
ROW_Y = (128, 280, 432)
FLOW_H = ROW_Y[2] + CARD_H + PAD                # 560
LINE, SIGNAL, CARD_STROKE = "#1D5534", GREEN, "#1A402A"


def _card_x(i: int) -> int:
    return CARDS_X + i * (CARD_W + GAP)


def _cx(i: int) -> int:
    return _card_x(i) + CARD_W // 2


def _path(points: list[tuple[float, float]], radius: float = 12) -> str:
    """An orthogonal polyline through ``points`` with rounded bends."""
    d = f"M{points[0][0]:g} {points[0][1]:g}"
    for (ax, ay), (px, py), (bx, by) in zip(points, points[1:], points[2:]):
        ux, uy = (px - ax, py - ay)
        vx, vy = (bx - px, by - py)
        lu, lv = max(abs(ux), abs(uy)), max(abs(vx), abs(vy))
        r = min(radius, lu / 2, lv / 2)
        d += f" L{px - ux / lu * r:g} {py - uy / lu * r:g} Q{px:g} {py:g} {px + vx / lv * r:g} {py + vy / lv * r:g}"
    return d + f" L{points[-1][0]:g} {points[-1][1]:g}"


def _connector(points: list[tuple[float, float]], *, arrow: bool = True) -> str:
    """A thin line with a short bright signal travelling along it."""
    d = _path(points)
    marker = ' marker-end="url(#arrow)"' if arrow else ""
    return (f'  <path d="{d}" fill="none" stroke="{LINE}" stroke-width="1.5"{marker}/>\n'
            f'  <path d="{d}" fill="none" stroke="{SIGNAL}" stroke-width="1.6" stroke-linecap="round" '
            f'stroke-dasharray="3 27" opacity=".85"><animate attributeName="stroke-dashoffset" from="30" '
            f'to="0" dur="1.5s" repeatCount="indefinite"/></path>\n')


def _card(i: int, row: int, icon: str, title: str, sub: str, tag: str, *, accent: bool = False) -> str:
    x, y = _card_x(i), ROW_Y[row]
    stroke = f'stroke="{GREEN}" stroke-width="1.2"' if accent else f'stroke="{CARD_STROKE}"'
    glow = (f'    <rect x="{x - 4}" y="{y - 4}" width="{CARD_W + 8}" height="{CARD_H + 8}" rx="17" fill="none" '
            f'stroke="{GREEN}" stroke-opacity=".18" stroke-width="4"/>\n') if accent else ""
    tag_svg = (f'\n    <text x="{x + CARD_W - 14}" y="{y + 21}" text-anchor="end" font-family="{MONO}" '
               f'font-size="9.5" letter-spacing="1.2" fill="#4E8A63">{escape(tag)}</text>') if tag else ""
    return f"""  <g>
{glow}    <rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="14" fill="url(#card)" {stroke}/>
    <rect x="{x + 16}" y="{y + 26}" width="36" height="36" rx="10" fill="#0F2819" stroke="#1C4A2E" stroke-width=".8"/>
    <g transform="translate({x + 25} {y + 35}) scale(.75)" fill="none" stroke="{GREEN}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{ICONS[icon]}</g>
    <text x="{x + 66}" y="{y + 42}" font-family="{FONT}" font-size="15.5" font-weight="700" fill="#FFFFFF">{escape(title)}</text>
    <text x="{x + 66}" y="{y + 62}" font-family="{FONT}" font-size="12.5" fill="#7FA58C">{escape(sub)}</text>{tag_svg}
  </g>
"""


def _rail(t: dict[str, object]) -> str:
    """Stage markers: a numbered badge on the left padding line, its name beside it."""
    stages = t["stages"]
    assert isinstance(stages, list)
    r = 17
    badge_x = PAD + r
    mids = [y + CARD_H // 2 for y in ROW_Y]
    out = ""
    for a, b in zip(mids, mids[1:]):  # dotted spine between badges, never behind text
        out += (f'  <path d="M{badge_x} {a + r + 8} V{b - r - 8}" stroke="{LINE}" stroke-width="1.5" '
                f'stroke-dasharray="1 6" stroke-linecap="round"/>\n')
    for row, lines in enumerate(stages):
        assert isinstance(lines, list)
        cy = mids[row]
        out += (f'  <circle cx="{badge_x}" cy="{cy}" r="{r}" fill="#07130C" stroke="{GREEN}" stroke-width="1.2"/>\n'
                f'  <text x="{badge_x}" y="{cy + 5}" text-anchor="middle" font-family="{MONO}" font-size="14" '
                f'font-weight="700" fill="{GREEN}">{row + 1:02d}</text>\n')
        first = cy + 4 - (len(lines) - 1) * 7
        for k, line in enumerate(lines):
            out += (f'  <text x="{badge_x + r + 12}" y="{first + k * 14}" font-family="{MONO}" font-size="10" '
                    f'letter-spacing="1.2" fill="#6E9C7E">{escape(str(line))}</text>\n')
    return out


def flow(lang: str) -> str:
    """Three stages: get a model, make it printable, print."""
    t = TEXT[lang]
    top, bottom = ROW_Y, [y + CARD_H for y in ROW_Y]
    mid = [y + CARD_H // 2 for y in ROW_Y]
    split_y, bus1, bus2 = PILL_Y + PILL_H + 22, bottom[0] + 32, bottom[1] + 32
    c0, c1, c2 = _cx(0), _cx(1), _cx(2)
    parts: list[str] = [_rail(t)]

    # Request → the three ways to get a model
    parts.append(_connector([(c1, PILL_Y + PILL_H), (c1, top[0] - 3)]))
    for cx in (c0, c2):
        parts.append(_connector([(c1, PILL_Y + PILL_H), (c1, split_y), (cx, split_y), (cx, top[0] - 3)]))
    # Any of them → Check & Repair
    parts.append(_connector([(c0, bottom[0]), (c0, top[1] - 3)]))
    parts.append(_connector([(c1, bottom[0]), (c1, bus1), (c0, bus1), (c0, bus1 + 14)], arrow=False))
    parts.append(_connector([(c2, bottom[0]), (c2, bus1), (c1 - 12, bus1)], arrow=False))
    # Along each row, and from Preview down to Bambu Studio
    for row in (1, 2):
        for i in range(2):
            parts.append(_connector([(_card_x(i) + CARD_W, mid[row]), (_card_x(i + 1) - 3, mid[row])]))
    parts.append(_connector([(c2, bottom[1]), (c2, bus2), (c0, bus2), (c0, top[2] - 3)]))

    # A pulse that runs the main route behind the cards
    route = _path([(c1, PILL_Y + PILL_H), (c1, bus1), (c0, bus1), (c0, mid[1]), (c2, mid[1]),
                   (c2, bus2), (c0, bus2), (c0, mid[2]), (c2, mid[2])])
    for radius, alpha in ((9, ".22"), (3.5, "1")):  # invisible unless animation runs
        parts.append(f'  <circle r="{radius}" fill="{GREEN}" opacity="0"><animate attributeName="opacity" '
                     f'values="{alpha}" dur="8s" repeatCount="indefinite"/><animateMotion dur="8s" '
                     f'repeatCount="indefinite" path="{route}"/></circle>\n')

    # Request pill
    pill_w = 172
    parts.append(f'  <rect x="{c1 - pill_w / 2 - 5}" y="{PILL_Y - 5}" width="{pill_w + 10}" height="{PILL_H + 10}" '
                 f'rx="{(PILL_H + 10) / 2}" fill="{GREEN}" opacity=".16"/>\n'
                 f'  <rect x="{c1 - pill_w / 2}" y="{PILL_Y}" width="{pill_w}" height="{PILL_H}" rx="{PILL_H / 2}" '
                 f'fill="{GREEN}"/>\n'
                 f'  <text x="{c1}" y="{PILL_Y + 25.5}" text-anchor="middle" font-family="{FONT}" font-size="15" '
                 f'font-weight="700" fill="#03140A">{escape(str(t["request"]))}</text>\n')

    cards = t["cards"]
    assert isinstance(cards, list)
    for row, row_cards in enumerate(cards):
        for i, (icon, title, sub, tag) in enumerate(row_cards):
            parts.append(_card(i, row, icon, title, sub, tag, accent=(row, i) == (2, 1)))

    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {FLOW_H}" width="{W}" height="{FLOW_H}" '
            f'role="img" aria-label="How Bambu Lab AI works">\n'
            f'  <defs>\n'
            f'    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#001C0D"/>'
            f'<stop offset=".6" stop-color="#030B06"/><stop offset="1" stop-color="#000"/></linearGradient>\n'
            f'    <linearGradient id="card" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0D1D14"/>'
            f'<stop offset="1" stop-color="#08140D"/></linearGradient>\n'
            f'    <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">'
            f'<path d="M24 0H0V24" fill="none" stroke="{GREEN}" stroke-opacity=".05"/></pattern>\n'
            f'    <marker id="arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="9" markerHeight="9" '
            f'markerUnits="userSpaceOnUse" orient="auto"><path d="M1.5 1.5L8.5 5L1.5 8.5" fill="none" '
            f'stroke="{GREEN}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></marker>\n'
            f'    <clipPath id="frame"><rect width="{W}" height="{FLOW_H}" rx="20"/></clipPath>\n'
            f'  </defs>\n'
            f'  <g clip-path="url(#frame)">\n'
            f'  <rect width="{W}" height="{FLOW_H}" fill="url(#bg)"/>\n'
            f'  <rect width="{W}" height="{FLOW_H}" fill="url(#grid)"/>\n'
            + "".join(parts)
            + f'  </g>\n  <rect x=".5" y=".5" width="{W - 1}" height="{FLOW_H - 1}" rx="19.5" fill="none" '
            f'stroke="#12301F"/>\n</svg>\n')


def main() -> None:
    for lang in ("en", "zh"):
        suffix = "" if lang == "en" else "-zh"
        (OUT / f"readme-header{suffix}.svg").write_text(header(lang), encoding="utf-8")
        (OUT / f"how-it-works{suffix}.svg").write_text(flow(lang), encoding="utf-8")
        (OUT / f"readme-footer{suffix}.svg").write_text(footer(lang), encoding="utf-8")
        print(f"wrote readme-header{suffix}.svg, how-it-works{suffix}.svg, readme-footer{suffix}.svg")


if __name__ == "__main__":
    main()
