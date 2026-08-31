"""生成概率设计文档用的 SVG 分布图(纯 stdlib,不依赖 matplotlib)。

用法:  python docs/gen_probability_charts.py
输出:  docs/img/*.svg

数字与 src/reward_system.py / src/chest_opening.py 的常量保持一致。
"""
from __future__ import annotations

import math
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "img"
W, H, M = 560, 340, 46  # 宽、高、边距
FONT = "'Microsoft YaHei', 'PingFang SC', sans-serif"


def _axis(g: list[str], x_lo: float, x_hi: float, y_lo: float, y_hi: float) -> None:
    """画坐标轴 + 网格;x/y 均为数据坐标,映射到绘图区。"""
    g.append(
        f'<line x1="{M}" y1="{H - M}" x2="{W - M}" y2="{H - M}" stroke="#555" stroke-width="1"/>'
    )
    g.append(
        f'<line x1="{M}" y1="{M}" x2="{M}" y2="{H - M}" stroke="#555" stroke-width="1"/>'
    )
    for i in range(6):
        fx = M + i * (W - 2 * M) / 5
        g.append(f'<line x1="{fx:.1f}" y1="{M}" x2="{fx:.1f}" y2="{H - M}" stroke="#333" stroke-width="0.5"/>')
    for i in range(4):
        fy = M + i * (H - 2 * M) / 3
        g.append(f'<line x1="{M}" y1="{fy:.1f}" x2="{W - M}" y2="{fy:.1f}" stroke="#333" stroke-width="0.5"/>')


def _x(v: float, x_lo: float, x_hi: float) -> float:
    return M + (v - x_lo) / (x_hi - x_lo) * (W - 2 * M)


def _y(v: float, y_lo: float, y_hi: float) -> float:
    return H - M - (v - y_lo) / (y_hi - y_lo) * (H - 2 * M)


def _svg(title: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{FONT}">\n'
        f'  <rect width="{W}" height="{H}" fill="#14151d"/>\n'
        f'  <text x="{W/2}" y="26" fill="#e8eaf0" font-size="15" font-weight="700" '
        f'text-anchor="middle">{title}</text>\n{body}</svg>\n'
    )


def _lognormal_pdf(x: float, mu: float, sigma: float) -> float:
    if x <= 0:
        return 0.0
    return math.exp(-((math.log(x) - mu) ** 2) / (2 * sigma * sigma)) / (x * sigma * math.sqrt(2 * math.pi))


# ---------- 1. 字母数量:几何分布 p=0.5 ----------
def chart_letter_count_geometric() -> str:
    p = 0.5
    xs = list(range(1, 9))
    probs = [(1 - p) ** (k - 1) * p for k in xs]
    x_lo, x_hi, y_lo, y_hi = 0.5, 8.5, 0.0, 0.55
    g: list[str] = []
    _axis(g, x_lo, x_hi, y_lo, y_hi)
    for k, pr in zip(xs, probs):
        bw = (W - 2 * M) / 8 * 0.62
        x0 = _x(k, x_lo, x_hi) - bw / 2
        y0 = _y(pr, y_lo, y_hi)
        g.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{H - M - y0:.1f}" '
            f'fill="#7aa2ff" rx="2"><title>{k} 个: {pr*100:.1f}%</title></rect>'
        )
        g.append(
            f'<text x="{_x(k, x_lo, x_hi):.1f}" y="{y0 - 6:.1f}" fill="#e8eaf0" '
            f'font-size="11" text-anchor="middle">{pr*100:.1f}%</text>'
        )
        g.append(
            f'<text x="{_x(k, x_lo, x_hi):.1f}" y="{H - M + 16}" fill="#aeb6c8" '
            f'font-size="11" text-anchor="middle">{k} 个</text>'
        )
    g.append(
        f'<text x="{W - M}" y="{M + 14}" fill="#ffd56a" font-size="12" text-anchor="end">'
        "均值 = 1/p = 2 个</text>"
    )
    return _svg("字母数量:几何分布 p=0.5(P(X=k)=(1-p)^(k-1)·p)", "\n".join(g))


# ---------- 2. 字母稀有度:5×5 权重 ----------
def chart_letter_rarity_weights() -> str:
    weights = (
        (70, 20, 7, 2, 1),
        (50, 28, 15, 5, 2),
        (30, 30, 25, 12, 3),
        (15, 25, 30, 22, 8),
        (5, 12, 28, 30, 25),
    )
    names = ("普通", "罕见", "稀有", "史诗", "传奇")
    colors = ("#c8c0b4", "#7dcc96", "#7aa2ff", "#c9a0ff", "#ffd56a")
    x_lo, x_hi, y_lo, y_hi = -0.4, 4.4, 0.0, 80.0
    g: list[str] = []
    _axis(g, x_lo, x_hi, y_lo, y_hi)
    for r in range(5):
        pts = []
        for c in range(5):
            pr = weights[r][c] / sum(weights[r]) * 100
            pts.append(f"{_x(c, x_lo, x_hi):.1f},{_y(pr, y_lo, y_hi):.1f}")
        g.append(
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{colors[r]}" '
            f'stroke-width="2" stroke-linejoin="round"><title>{names[r]}箱</title></polyline>'
        )
    for c in range(5):
        g.append(
            f'<text x="{_x(c, x_lo, x_hi):.1f}" y="{H - M + 16}" fill="#aeb6c8" '
            f'font-size="11" text-anchor="middle">{names[c]}</text>'
        )
    g.append(f'<text x="{M}" y="{M + 14}" fill="#e8eaf0" font-size="12">各宝箱开出的字母稀有度占比(加权)</text>')
    for r in range(5):
        g.append(
            f'<line x1="{W - M - 118}" y1="{M + 26 + r*15}" x2="{W - M - 96}" y2="{M + 26 + r*15}" '
            f'stroke="{colors[r]}" stroke-width="3"/>'
            f'<text x="{W - M - 90}" y="{M + 30 + r*15}" fill="#aeb6c8" font-size="11">{names[r]}箱</text>'
        )
    return _svg("字母稀有度:按宝箱稀有度加权的分布", "\n".join(g))


# ---------- 3. 伴生货币:对数正态 PDF ----------
def chart_currency_lognormal() -> str:
    sigma = 0.6
    means = (2.0, 18.0)
    colors = ("#7aa2ff", "#ffd56a")
    labels = ("普通箱(均值 2)", "传奇箱(均值 18)")
    x_lo, x_hi, y_lo, y_hi = 0.0, 40.0, 0.0, 0.32
    g: list[str] = []
    _axis(g, x_lo, x_hi, y_lo, y_hi)
    for mean, color, label in zip(means, colors, labels):
        mu = math.log(mean) - sigma * sigma / 2
        pts = []
        for i in range(161):
            x = x_lo + (x_hi - x_lo) * i / 160
            pts.append(f"{_x(x, x_lo, x_hi):.1f},{_y(_lognormal_pdf(x, mu, sigma), y_lo, y_hi):.1f}")
        g.append(
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        g.append(
            f'<text x="{W - M - 120}" y="{M + 24 + means.index(mean)*18}" fill="{color}" '
            f'font-size="12">{label}</text>'
        )
    # 众数/中位数/均值标注(传奇箱)
    mu = math.log(18.0) - sigma * sigma / 2
    for i in range(6):
        g.append(f'<text x="{W - M}" y="{M + 60 + i*18}" fill="#8a90a0" font-size="11" text-anchor="end">{["", "众数 ≈ 0.7·均值", "中位数 ≈ 0.84·均值", "均值 = 设定值", "P(X>10·均值) ≈ 0.02%", "0-∞ 无上限"][i]}</text>')
    return _svg("伴生货币金额:对数正态右偏(σ=0.6)", "\n".join(g))


# ---------- 4. 开奖概率:截断对数正态 ----------
def chart_roll_chance_lognormal() -> str:
    sigma = 0.55
    ranges = ((0.22, 0.48), (0.03, 0.10))
    colors = ("#ffd54f", "#7dd3fc")
    labels = ("金币概率 0.22-0.48", "钻石概率 0.03-0.10")
    x_lo, x_hi, y_lo, y_hi = 0.0, 0.55, 0.0, 12.0
    g: list[str] = []
    _axis(g, x_lo, x_hi, y_lo, y_hi)
    for (lo, hi), color, label in zip(ranges, colors, labels):
        med = lo + 0.25 * (hi - lo)
        mu = math.log(max(med, 1e-9))
        pts = []
        for i in range(161):
            x = x_lo + (x_hi - x_lo) * i / 160
            pdf = _lognormal_pdf(x, mu, sigma) if lo <= x <= hi else 0.0
            pts.append(f"{_x(x, x_lo, x_hi):.1f},{_y(pdf, y_lo, y_hi):.1f}")
        g.append(
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        g.append(
            f'<text x="{W - M - 10}" y="{M + 24 + list(ranges).index((lo, hi))*18}" fill="{color}" '
            f'font-size="12" text-anchor="end">{label}</text>'
        )
    return _svg("开奖概率:每 10 分钟重抽的截断对数正态", "\n".join(g))


# ---------- 5. 暴击倍率:右偏 ----------
def chart_crit_mult() -> str:
    sigma = 0.95
    x_lo, x_hi, y_lo, y_hi = 1.0, 20.0, 0.0, 0.85
    g: list[str] = []
    _axis(g, x_lo, x_hi, y_lo, y_hi)
    med = 1.2 + 0.25 * (20.0 - 1.2)
    mu = math.log(med)
    pts = []
    for i in range(161):
        x = x_lo + (x_hi - x_lo) * i / 160
        pdf = _lognormal_pdf(x, mu, sigma) if 1.2 <= x <= 20.0 else 0.0
        pts.append(f"{_x(x, x_lo, x_hi):.1f},{_y(pdf, y_lo, y_hi):.1f}")
    g.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#c9a0ff" stroke-width="2"/>')
    for i, t in enumerate(["多数 1.2-3x", "极少数接近 20x", "命中概率 8%"]):
        g.append(f'<text x="{W - M}" y="{M + 24 + i*18}" fill="#8a90a0" font-size="11" text-anchor="end">{t}</text>')
    return _svg("暴击倍率:截断对数正态(σ=0.95,1.2x-20x)", "\n".join(g))


# ---------- 6. 开奖周期:均匀分布对比 ----------
def chart_roll_span_uniform() -> str:
    x_lo, x_hi, y_lo, y_hi = 0.0, 400.0, 0.0, 1.3
    g: list[str] = []
    _axis(g, x_lo, x_hi, y_lo, y_hi)
    y1 = _y(0.6, y_lo, y_hi)
    g.append(
        f'<rect x="{_x(6, x_lo, x_hi):.1f}" y="{y1:.1f}" '
        f'width="{_x(14, x_lo, x_hi) - _x(6, x_lo, x_hi):.1f}" height="26" fill="#ffd54f" rx="3"/>'
    )
    g.append(f'<text x="{_x(10, x_lo, x_hi):.1f}" y="{y1 + 17:.1f}" fill="#14151d" font-size="11" '
             f'text-anchor="middle" font-weight="700">6-14 操作</text>')
    y2 = _y(0.2, y_lo, y_hi)
    g.append(
        f'<rect x="{_x(258, x_lo, x_hi):.1f}" y="{y2:.1f}" '
        f'width="{_x(342, x_lo, x_hi) - _x(258, x_lo, x_hi):.1f}" height="26" fill="#7aa2ff" rx="3"/>'
    )
    g.append(f'<text x="{_x(300, x_lo, x_hi):.1f}" y="{y2 + 17:.1f}" fill="#e8eaf0" font-size="11" '
             f'text-anchor="middle">258-342 秒</text>')
    g.append(f'<text x="{W - M}" y="{y1 + 4}" fill="#ffd54f" font-size="12" text-anchor="end">开奖周期(均匀)</text>')
    g.append(f'<text x="{W - M}" y="{y2 + 4}" fill="#7aa2ff" font-size="12" text-anchor="end">缓动条周期(确定性)</text>')
    return _svg("开奖周期与视觉宝箱条周期对比", "\n".join(g))


# ---------- 7. 缓动条周期跨度:确定性算法 ----------
def chart_ease_span_distribution() -> str:
    spans = [258 + ((cid * 7) % 15) * 6 for cid in range(15)]
    x_lo, x_hi, y_lo, y_hi = 0, 14, 0, 400
    g: list[str] = []
    _axis(g, x_lo, x_hi, y_lo, y_hi)
    bw = (W - 2 * M) / 15 * 0.55
    for i, s in enumerate(spans):
        x0 = _x(i, x_lo, x_hi) - bw / 2
        y0 = _y(s, y_lo, y_hi)
        g.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{H - M - y0:.1f}" '
            f'fill="#7aa2ff" rx="2"><title>cycle {i}: {s}s</title></rect>'
        )
    for i in (0, 5, 10, 14):
        g.append(
            f'<text x="{_x(i, x_lo, x_hi):.1f}" y="{H - M + 16}" fill="#aeb6c8" '
            f'font-size="10" text-anchor="middle">#{i}</text>'
        )
    g.append(
        f'<text x="{W - M}" y="{M + 14}" fill="#ffd56a" font-size="12" text-anchor="end">'
        "跨度 258-342 秒,步长 6,15 轮走遍全部</text>"
    )
    g.append(
        f'<text x="{W - M}" y="{M + 32}" fill="#8a90a0" font-size="11" text-anchor="end">'
        "span = 258 + ((cycle_id × 7) % 15) × 6</text>"
    )
    return _svg("视觉宝箱条周期:确定性算法(15 种跨度)", "\n".join(g))


# ---------- 8. 缓动条检查点:终点一箱 ----------
def chart_ease_checkpoints() -> str:
    g: list[str] = []
    bar_y = M + 60
    g.append(
        f'<rect x="{M}" y="{bar_y}" width="{W - 2*M}" height="18" fill="#252838" rx="9"/>'
    )
    fill_w = W - 2 * M
    g.append(
        f'<rect x="{M}" y="{bar_y}" width="{fill_w:.1f}" height="18" fill="#7aa2ff" rx="9"/>'
    )
    x = _x(1.0, 0, 1)
    g.append(
        f'<line x1="{x:.1f}" y1="{bar_y - 12}" x2="{x:.1f}" y2="{bar_y + 30}" '
        f'stroke="#ffd56a" stroke-width="3"/>'
    )
    g.append(
        f'<text x="{x:.1f}" y="{bar_y + 48}" fill="#ffd56a" font-size="11" '
        f'text-anchor="end">终点箱 1.00</text>'
    )
    g.append(
        f'<text x="{W - M}" y="{bar_y + 100}" fill="#8a90a0" font-size="11" '
        f'text-anchor="end">每轮一只箱子,固定在 100%</text>'
    )
    return _svg("缓动条检查点:终点一箱", "\n".join(g))


# ---------- 9. 缓动条单箱稀有度权重 ----------
def chart_ease_rarity_weights() -> str:
    weights = (22, 25, 25, 18, 10)
    names = ("普通", "罕见", "稀有", "史诗", "传奇")
    colors = ("#c8c0b4", "#7dcc96", "#7aa2ff", "#c9a0ff", "#ffd56a")
    total = sum(weights)
    x_lo, x_hi, y_lo, y_hi = -0.4, 4.4, 0.0, 40.0
    g: list[str] = []
    _axis(g, x_lo, x_hi, y_lo, y_hi)
    bw = (W - 2 * M) / 5 * 0.45
    for c, (w, name, color) in enumerate(zip(weights, names, colors)):
        pr = w / total * 100
        x0 = _x(c, x_lo, x_hi) - bw / 2
        y0 = _y(pr, y_lo, y_hi)
        g.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{H - M - y0:.1f}" '
            f'fill="{color}" rx="2"><title>{name} {pr:.0f}%</title></rect>'
        )
        g.append(
            f'<text x="{_x(c, x_lo, x_hi):.1f}" y="{H - M + 16}" fill="#aeb6c8" '
            f'font-size="11" text-anchor="middle">{name}</text>'
        )
    g.append(
        f'<text x="{W - M}" y="{M + 14}" fill="#ffd56a" font-size="12" text-anchor="end">'
        "权重 22 / 25 / 25 / 18 / 10</text>"
    )
    return _svg("缓动条单箱稀有度权重", "\n".join(g))


CHARTS = {
    "letter_count_geometric.svg": chart_letter_count_geometric,
    "letter_rarity_weights.svg": chart_letter_rarity_weights,
    "currency_lognormal.svg": chart_currency_lognormal,
    "roll_chance_lognormal.svg": chart_roll_chance_lognormal,
    "crit_mult_lognormal.svg": chart_crit_mult,
    "roll_span_uniform.svg": chart_roll_span_uniform,
    "ease_span_distribution.svg": chart_ease_span_distribution,
    "ease_checkpoints.svg": chart_ease_checkpoints,
    "ease_rarity_weights.svg": chart_ease_rarity_weights,
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, fn in CHARTS.items():
        (OUT_DIR / name).write_text(fn(), encoding="utf-8")
        print(f"wrote {OUT_DIR / name}")


if __name__ == "__main__":
    main()
