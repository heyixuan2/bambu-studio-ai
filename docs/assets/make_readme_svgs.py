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
        "request": "Your request",
        "branches": ["everyday object", "exact part", "figurine / photo"],
        "stages": [["GET A", "MODEL"], ["MAKE IT", "PRINTABLE"], ["PRINT"]],
        "cards": [
            [("search", "Search models", "MakerWorld & Printables"),
             ("caliper", "Parametric CAD", "exact mm, real screw holes"),
             ("spark", "AI text / photo → 3D", "figurines and characters")],
            [("shield", "Check & repair", "scale, overhangs, fit"),
             ("spools", "Multi-colour", "texture → AMS filaments"),
             ("eye", "Preview render", "see it before slicing")],
            [("layers", "Bambu Studio", "you review and slice"),
             ("play", "You press Print", "the agent can't start one"),
             ("pulse", "Monitor", "progress + alerts, read-only")],
        ],
        "optional": "optional",
        "footer": "Made for the Bambu Lab community · by TieGaier",
    },
    "zh": {
        "tag": "AGENT SKILL · 拓竹 AI 打印助手",
        "subtitle": "跟你的 AI 说一句话，它来建模、检查、打印到你的拓竹。",
        "request": "你的需求",
        "branches": ["日常物件", "精密件", "手办 / 照片"],
        "stages": [["获取模型"], ["变得可打印"], ["打印"]],
        "cards": [
            [("search", "搜索模型", "MakerWorld 与 Printables"),
             ("caliper", "参数化 CAD", "精确到毫米，真实螺丝孔"),
             ("spark", "AI 文生 / 图生 3D", "手办、角色、照片")],
            [("shield", "检查与修复", "尺寸、悬垂、能否放下"),
             ("spools", "AMS 多色", "贴图 → AMS 耗材"),
             ("eye", "渲染预览", "切片之前先看一眼")],
            [("layers", "Bambu Studio", "你来检查、切片"),
             ("play", "你点「打印」", "AI 无法替你开始打印"),
             ("pulse", "进度监控", "进度与提醒，只读")],
        ],
        "optional": "可选",
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
    <clipPath id="frame"><rect width="1200" height="300" rx="22"/></clipPath>
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
    <clipPath id="frame"><rect width="1200" height="110" rx="22"/></clipPath>
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


CARD_W, CARD_H, GAP, LEFT = 246, 84, 18, 170
ROW_Y = [150, 322, 494]  # tops of the three card rows


def _card_x(i: int) -> int:
    return LEFT + i * (CARD_W + GAP)


def _card(i: int, row: int, icon: str, title: str, sub: str, *, dashed: bool = False, badge: str = "") -> str:
    x, y = _card_x(i), ROW_Y[row]
    dash = ' stroke-dasharray="5 5"' if dashed else ""
    tag = (f'<text x="{x + CARD_W - 14}" y="{y + 22}" text-anchor="end" font-family="{MONO}" font-size="11" '
           f'letter-spacing="1.5" fill="#5E8C6E">{escape(badge.upper())}</text>') if badge else ""
    return f'''  <g>
    <rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="12" fill="#0A1A10" stroke="#1F6B3D"{dash}/>
    <rect x="{x + 16}" y="{y}" width="46" height="3" rx="1.5" fill="{GREEN}"/>
    <g transform="translate({x + 18} {y + 30})" fill="none" stroke="{GREEN}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[icon]}</g>
    <text x="{x + 54}" y="{y + 40}" font-family="{FONT}" font-size="16" font-weight="700" fill="#FFFFFF">{escape(title)}</text>
    <text x="{x + 54}" y="{y + 61}" font-family="{FONT}" font-size="12.5" fill="#8CB89A">{escape(sub)}</text>
    {tag}
  </g>
'''


def _flow(d: str, *, arrow: bool = True) -> str:
    """A connector: a faint base line plus green dashes that flow along it."""
    marker = ' marker-end="url(#arrow)"' if arrow else ""
    return (f'  <path d="{d}" fill="none" stroke="{GREEN}" stroke-opacity=".28" stroke-width="2"{marker}/>\n'
            f'  <path d="{d}" fill="none" stroke="{GREEN}" stroke-width="2" stroke-dasharray="6 12">'
            f'<animate attributeName="stroke-dashoffset" from="36" to="0" dur="1.1s" repeatCount="indefinite"/></path>\n')


def flow(lang: str) -> str:
    """Three stages: get a model, make it printable, print."""
    t = TEXT[lang]
    cx = [_card_x(i) + CARD_W // 2 for i in range(3)]
    mid_y = [y + CARD_H // 2 for y in ROW_Y]
    bottom = [y + CARD_H for y in ROW_Y]
    parts: list[str] = []

    # Request pill and its three branches
    top = cx[1]
    parts.append(f'  <rect x="{top - 90}" y="36" width="180" height="42" rx="21" fill="{GREEN}"/>\n'
                 f'  <text x="{top}" y="63" text-anchor="middle" font-family="{FONT}" font-size="17" font-weight="700" '
                 f'fill="#02140A">{escape(t["request"])}</text>\n')
    for i in range(3):
        parts.append(_flow(f"M{top} 78 C{top} 112 {cx[i]} 104 {cx[i]} {ROW_Y[0] - 4}"))
    for i, label in enumerate(t["branches"]):
        lx = (top + cx[i]) / 2 if i != 1 else top
        parts.append(f'  <rect x="{lx - 62}" y="100" width="124" height="22" rx="11" fill="#030C07" stroke="#1F6B3D"/>\n'
                     f'  <text x="{lx}" y="115.5" text-anchor="middle" font-family="{FONT}" font-size="12.5" '
                     f'fill="#B7D8C1">{escape(label)}</text>\n')

    # Stage 1 → bus → stage 2 (left to right) → bus → stage 3 (left to right)
    bus1 = bottom[0] + 30
    for i in range(3):
        parts.append(_flow(f"M{cx[i]} {bottom[0]} V{bus1}", arrow=False))
    parts.append(_flow(f"M{cx[2]} {bus1} H{cx[0]} V{ROW_Y[1] - 4}"))
    for i in range(2):
        parts.append(_flow(f"M{_card_x(i) + CARD_W} {mid_y[1]} H{_card_x(i + 1) - 4}"))
    bus2 = bottom[1] + 30
    parts.append(_flow(f"M{cx[2]} {bottom[1]} V{bus2} H{cx[0]} V{ROW_Y[2] - 4}"))
    for i in range(2):
        parts.append(_flow(f"M{_card_x(i) + CARD_W} {mid_y[2]} H{_card_x(i + 1) - 4}"))

    # Stage rail on the left: big number, stage name, and a line tying the rail together
    parts.append(f'  <path d="M58 {ROW_Y[0] + 10} V{ROW_Y[2] + CARD_H - 10}" stroke="{GREEN}" stroke-opacity=".25" '
                 f'stroke-width="2" stroke-dasharray="2 6"/>\n')
    for row, lines in enumerate(t["stages"]):
        y = ROW_Y[row] + 34
        parts.append(f'  <circle cx="58" cy="{y - 10}" r="21" fill="#030C07" stroke="{GREEN}" stroke-width="1.5"/>\n'
                     f'  <text x="58" y="{y - 3}" text-anchor="middle" font-family="{MONO}" font-size="19" font-weight="700" '
                     f'fill="{GREEN}">{row + 1:02d}</text>\n')
        for k, line in enumerate(lines):
            parts.append(f'  <text x="90" y="{y - 12 + k * 16}" font-family="{MONO}" font-size="11" letter-spacing="1" '
                         f'fill="#8CB89A">{escape(line)}</text>\n')

    # A pulse that travels the main route, request → print → monitor
    route = (f"M{top} 78 V{bus1} H{cx[0]} V{mid_y[1]} H{cx[2]} "
             f"V{bus2} H{cx[0]} V{mid_y[2]} H{cx[2]}")
    for radius, alpha in ((5, ".9"), (12, ".18")):  # invisible unless animation runs
        parts.append(f'  <circle r="{radius}" fill="{GREEN}" opacity="0">'
                     f'<animate attributeName="opacity" values="{alpha}" dur="7s" repeatCount="indefinite"/>'
                     f'<animateMotion dur="7s" repeatCount="indefinite" path="{route}"/></circle>\n')

    for row, cards in enumerate(t["cards"]):
        for i, (icon, title, sub) in enumerate(cards):
            optional = row == 1 and i == 1
            parts.append(_card(i, row, icon, title, sub, dashed=optional, badge=t["optional"] if optional else ""))

    height = ROW_Y[2] + CARD_H + 44
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 {height}" width="960" height="{height}" '
            f'role="img" aria-label="How Bambu Lab AI works">\n'
            f'  <defs>\n'
            f'    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#00200F"/>'
            f'<stop offset=".6" stop-color="#030C07"/><stop offset="1" stop-color="#000"/></linearGradient>\n'
            f'    <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">'
            f'<path d="M24 0H0V24" fill="none" stroke="{GREEN}" stroke-opacity=".06"/></pattern>\n'
            f'    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0 0L10 5L0 10z" fill="{GREEN}"/></marker>\n'
            f'  </defs>\n'
            f'  <rect width="960" height="{height}" rx="20" fill="url(#bg)"/>\n'
            f'  <rect width="960" height="{height}" rx="20" fill="url(#grid)"/>\n'
            + "".join(parts) + "</svg>\n")


def main() -> None:
    for lang in ("en", "zh"):
        suffix = "" if lang == "en" else "-zh"
        (OUT / f"readme-header{suffix}.svg").write_text(header(lang), encoding="utf-8")
        (OUT / f"how-it-works{suffix}.svg").write_text(flow(lang), encoding="utf-8")
        (OUT / f"readme-footer{suffix}.svg").write_text(footer(lang), encoding="utf-8")
        print(f"wrote readme-header{suffix}.svg, how-it-works{suffix}.svg, readme-footer{suffix}.svg")


if __name__ == "__main__":
    main()
