"""Generate the interactive-warehouse benchmark report as standalone HTML.

Emits hand-built inline SVG for every chart so the report renders in any browser
with no external libraries and no network access. Re-run after refreshing the
source data (see the report's embedded metadata block for the queries).

Usage:
    python docs/build-interactive-report.py
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent / "interactive-zero-copy-benchmark-report.html"

C_INT = "#29b5e8"
C_CLUST = "#10b981"
C_STD = "#f59e0b"
C_INT2 = "#7dd3fc"
C_MUTED = "#94a3b8"

NAMES = ["Interactive table", "Standard clustered", "Standard unclustered"]
SERIES_COLORS = [C_INT, C_CLUST, C_STD]

# ---------------------------------------------------------------- source data

QPS = {
    "Interactive table": [503.1, 495.9, 519.7, 475.5, 519.6, 438.8],
    "Standard clustered": [489.8, 466.8, 432.9, 517.8, 490.2, 458.5],
    "Standard unclustered": [426.3, 379.9, 387.4, 415.2, 431.0, 367.4],
}
P50 = {
    "Interactive table": [71.7, 72.7, 71.2, 76.8, 70.6, 85.8],
    "Standard clustered": [69.9, 75.1, 70.9, 75.9, 70.3, 71.0],
    "Standard unclustered": [99.8, 102.6, 101.4, 100.4, 100.8, 102.4],
}
# Server-side SQL execution time only (Snowflake QUERY_HISTORY.EXECUTION_TIME,
# surfaced as QUERY_EXECUTIONS.SF_EXECUTION_MS). Pooled over 6,006,727 enriched,
# non-warmup, successful query rows belonging to the 18 runs. Per-run lists are
# in chronological order within each configuration, matching QPS/P50 above.
SRV_P50_RUNS = {
    "Interactive table": [7, 7, 7, 7, 7, 7],
    "Standard clustered": [8, 7, 7, 7, 7, 7],
    "Standard unclustered": [47, 48, 48, 45, 49, 45],
}
SRV_P95_RUNS = {
    "Interactive table": [9, 10, 9, 9, 9, 9],
    "Standard clustered": [12, 10, 10, 10, 10, 10],
    "Standard unclustered": [74, 77, 78, 76, 78, 75],
}
SRV_P99_RUNS = {
    "Interactive table": [14, 14, 13, 13, 13, 13],
    "Standard clustered": [17, 15, 15, 15, 14, 15],
    "Standard unclustered": [91, 95, 96, 94, 96, 93],
}
# Pooled percentiles across every query row, not medians of run-level values.
SRV_POOLED = {
    "Interactive table": [7.0, 9.0, 13.0],
    "Standard clustered": [7.0, 10.0, 15.0],
    "Standard unclustered": [47.0, 77.0, 94.0],
}
# Median latency decomposition, ms. Each component is its own pooled median, so
# the segments do not sum exactly to the end-to-end median.
DECOMP = {
    "Interactive table": [7.0, 27.0, 36.8],
    "Standard clustered": [7.0, 27.0, 37.2],
    "Standard unclustered": [47.0, 40.0, 10.0],
}
# Server execution as a share of the end-to-end median (exec p50 / app p50).
SRV_SHARE = {
    "Interactive table": 9.7,
    "Standard clustered": 9.5,
    "Standard unclustered": 46.3,
}

RAMP_WORKERS = [1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56, 61, 66, 71]
RAMP_QPS = [
    (
        "Standard clustered",
        C_CLUST,
        [
            14.4,
            92.2,
            163.7,
            205.4,
            319.6,
            404.6,
            420.1,
            551.0,
            546.8,
            497.2,
            535.9,
            524.6,
            None,
            None,
            None,
        ],
    ),
    (
        "Interactive table (run A)",
        C_INT,
        [
            15,
            87.5,
            168.2,
            207.8,
            319.1,
            410.9,
            413.8,
            515.2,
            543.7,
            503.2,
            526.0,
            531.9,
            467.0,
            495.8,
            479.7,
        ],
    ),
    (
        "Interactive table (run B)",
        C_INT2,
        [
            16.7,
            97.3,
            177.2,
            215.3,
            308.1,
            350.7,
            357.2,
            410.6,
            525.8,
            517.2,
            516.6,
            None,
            None,
            None,
            None,
        ],
    ),
    (
        "Standard unclustered",
        C_STD,
        [
            15,
            88.2,
            155.9,
            207.4,
            287.4,
            334.7,
            335.0,
            372.2,
            378.5,
            391.8,
            411.3,
            None,
            None,
            None,
            None,
        ],
    ),
]
RAMP_P95 = [
    (
        "Standard clustered",
        C_CLUST,
        [
            84.7,
            84.1,
            85.9,
            90.7,
            94.0,
            93.1,
            99.1,
            97.6,
            106.9,
            128.1,
            151.4,
            178.5,
            None,
            None,
            None,
        ],
    ),
    (
        "Interactive table (run A)",
        C_INT,
        [
            112.4,
            87.8,
            84.4,
            89.2,
            94.1,
            92.7,
            103.1,
            105.1,
            113.1,
            132.8,
            149.8,
            174.9,
            201.4,
            211.4,
            280.4,
        ],
    ),
    (
        "Interactive table (run B)",
        C_INT2,
        [
            70.7,
            76.9,
            80.4,
            86.9,
            99.0,
            104.6,
            113.8,
            119.8,
            137.8,
            138.7,
            160.3,
            None,
            None,
            None,
            None,
        ],
    ),
    (
        "Standard unclustered",
        C_STD,
        [
            85.3,
            83.3,
            85.7,
            92.6,
            96.8,
            103.2,
            115.1,
            130.0,
            144.6,
            155.3,
            173.9,
            None,
            None,
            None,
            None,
        ],
    ),
]

# ---------------------------------------------------------------- svg helpers

FS = 13  # base font size inside the viewBox
AX = "currentColor"


def _open(w: int, h: int, label: str, min_w: int = 540) -> list[str]:
    return [
        (
            f'<div class="svg-scroll"><svg viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{escape(label)}" style="min-width:{min_w}px">'
        ),
        (
            f"<style>.t{{font:{FS}px -apple-system,system-ui,sans-serif;fill:currentColor}}"
            f".tb{{font:600 {FS}px -apple-system,system-ui,sans-serif;fill:currentColor}}"
            f".ts{{font:{FS - 2}px -apple-system,system-ui,sans-serif;"
            f"fill:currentColor;opacity:.72}}</style>"
        ),
    ]


def _close() -> str:
    return "</svg></div>"


def _nice_max(v: float) -> float:
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000):
        if v <= step * 5:
            return step * 5
    return v * 1.1


def _grid_y(parts, x0, x1, y0, y1, vmax, ticks=5, fmt="{:g}"):
    for i in range(ticks + 1):
        val = vmax * i / ticks
        y = y1 - (y1 - y0) * (i / ticks)
        parts.append(
            f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" '
            f'stroke="{AX}" stroke-opacity="0.16"/>'
        )
        parts.append(
            f'<text class="ts" x="{x0 - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f"{fmt.format(val)}</text>"
        )


def _legend(parts, items, x, y, gap=170, cols=3):
    for i, (name, color) in enumerate(items):
        cx = x + (i % cols) * gap
        cy = y + (i // cols) * 18
        parts.append(
            f'<rect x="{cx}" y="{cy - 9}" width="11" height="11" rx="2" fill="{color}"/>'
        )
        parts.append(f'<text class="ts" x="{cx + 16}" y="{cy}">{escape(name)}</text>')


def grouped_bars(
    labels,
    series,
    ylabel,
    *,
    width=760,
    height=380,
    value_fmt="{:.0f}",
    stacked=False,
    legend_cols=3,
):
    """Vertical grouped or stacked bar chart."""
    legend_rows = (len(series) + legend_cols - 1) // legend_cols
    top = 24 + legend_rows * 18
    x0, y0 = 74, top
    x1, y1 = width - 14, height - 44
    if stacked:
        vmax = _nice_max(
            max(sum(vals[i] for _, _, vals in series) for i in range(len(labels)))
        )
    else:
        vmax = _nice_max(max(v for _, _, vals in series for v in vals))

    parts = _open(width, height, ylabel)
    _legend(
        parts,
        [(n, c) for n, c, _ in series],
        x0,
        16,
        gap=(x1 - x0) / legend_cols,
        cols=legend_cols,
    )
    _grid_y(parts, x0, x1, y0, y1, vmax, fmt=value_fmt)
    parts.append(
        f'<text class="ts" x="14" y="{(y0 + y1) / 2:.0f}" '
        f'transform="rotate(-90 14 {(y0 + y1) / 2:.0f})" text-anchor="middle">'
        f"{escape(ylabel)}</text>"
    )
    parts.append(
        f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{AX}" stroke-opacity="0.45"/>'
    )

    slot = (x1 - x0) / len(labels)
    n = 1 if stacked else len(series)
    bw = min(46, (slot * 0.74) / n)

    for gi, lab in enumerate(labels):
        gx = x0 + slot * gi + slot / 2
        if stacked:
            acc = 0.0
            for _, color, vals in series:
                v = vals[gi]
                h = (y1 - y0) * v / vmax
                yb = y1 - (y1 - y0) * (acc + v) / vmax
                parts.append(
                    f'<rect x="{gx - bw / 2:.1f}" y="{yb:.1f}" width="{bw:.1f}" '
                    f'height="{h:.1f}" fill="{color}"/>'
                )
                if h > 15:
                    parts.append(
                        f'<text class="ts" x="{gx:.1f}" y="{yb + h / 2 + 4:.1f}" '
                        f'text-anchor="middle" fill="#0b1220">{value_fmt.format(v)}</text>'
                    )
                acc += v
            parts.append(
                f'<text class="ts" x="{gx:.1f}" y="{y1 - (y1 - y0) * acc / vmax - 6:.1f}" '
                f'text-anchor="middle">{value_fmt.format(acc)}</text>'
            )
        else:
            start = gx - (n * bw) / 2
            for si, (_, color, vals) in enumerate(series):
                v = vals[gi]
                h = max(2.0, (y1 - y0) * v / vmax)
                bx = start + si * bw
                parts.append(
                    f'<rect x="{bx:.1f}" y="{y1 - h:.1f}" width="{bw - 3:.1f}" '
                    f'height="{h:.1f}" fill="{color}"/>'
                )
                parts.append(
                    f'<text class="ts" x="{bx + (bw - 3) / 2:.1f}" y="{y1 - h - 5:.1f}" '
                    f'text-anchor="middle">{value_fmt.format(v)}</text>'
                )
        for li, line in enumerate(str(lab).split("\n")):
            parts.append(
                f'<text class="t" x="{gx:.1f}" y="{y1 + 19 + li * 14}" '
                f'text-anchor="middle">{escape(line)}</text>'
            )
    parts.append(_close())
    return "\n".join(parts)


def hbars(labels, values, colors, xlabel, *, width=760, height=260, value_fmt="{:.2f}"):
    """Horizontal bar chart."""
    x0, y0, x1, y1 = 176, 26, width - 58, height - 48
    vmax = _nice_max(max(values))
    parts = _open(width, height, xlabel)
    for i in range(6):
        x = x0 + (x1 - x0) * i / 5
        parts.append(
            f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y1}" stroke="{AX}" stroke-opacity="0.16"/>'
        )
        parts.append(
            f'<text class="ts" x="{x:.1f}" y="{y1 + 18}" text-anchor="middle">'
            f"{vmax * i / 5:g}</text>"
        )
    slot = (y1 - y0) / len(labels)
    bh = min(34, slot * 0.6)
    for i, (lab, v) in enumerate(zip(labels, values)):
        cy = y0 + slot * i + slot / 2
        w = max(2.0, (x1 - x0) * v / vmax)
        parts.append(
            f'<rect x="{x0}" y="{cy - bh / 2:.1f}" width="{w:.1f}" height="{bh:.1f}" fill="{colors[i]}"/>'
        )
        parts.append(
            f'<text class="tb" x="{x0 + w + 8:.1f}" y="{cy + 4:.1f}">{value_fmt.format(v)}</text>'
        )
        parts.append(
            f'<text class="t" x="{x0 - 10}" y="{cy + 4:.1f}" text-anchor="end">{escape(lab)}</text>'
        )
    parts.append(
        f'<text class="ts" x="{(x0 + x1) / 2:.0f}" y="{height - 8}" text-anchor="middle">'
        f"{escape(xlabel)}</text>"
    )
    parts.append(_close())
    return "\n".join(parts)


def range_bars(labels, lows, highs, meds, colors, xlabel, *, width=760, height=250):
    """Horizontal floating min-max bars with a median marker."""
    x0, y0, x1, y1 = 176, 30, width - 24, height - 40
    lo_ax, hi_ax = 340, 540
    parts = _open(width, height, xlabel)

    def sx(v):
        return x0 + (x1 - x0) * (v - lo_ax) / (hi_ax - lo_ax)

    for v in range(lo_ax, hi_ax + 1, 40):
        parts.append(
            f'<line x1="{sx(v):.1f}" y1="{y0}" x2="{sx(v):.1f}" y2="{y1}" '
            f'stroke="{AX}" stroke-opacity="0.16"/>'
        )
        parts.append(
            f'<text class="ts" x="{sx(v):.1f}" y="{y1 + 18}" text-anchor="middle">{v}</text>'
        )
    slot = (y1 - y0) / len(labels)
    bh = min(30, slot * 0.5)
    for i, lab in enumerate(labels):
        cy = y0 + slot * i + slot / 2
        parts.append(
            f'<rect x="{sx(lows[i]):.1f}" y="{cy - bh / 2:.1f}" '
            f'width="{sx(highs[i]) - sx(lows[i]):.1f}" height="{bh:.1f}" '
            f'rx="3" fill="{colors[i]}" fill-opacity="0.55"/>'
        )
        parts.append(
            f'<line x1="{sx(meds[i]):.1f}" y1="{cy - bh / 2 - 4:.1f}" '
            f'x2="{sx(meds[i]):.1f}" y2="{cy + bh / 2 + 4:.1f}" '
            f'stroke="{colors[i]}" stroke-width="3"/>'
        )
        parts.append(
            f'<text class="ts" x="{sx(lows[i]) - 6:.1f}" y="{cy + 4:.1f}" '
            f'text-anchor="end">{lows[i]:.1f}</text>'
        )
        parts.append(
            f'<text class="ts" x="{sx(highs[i]) + 6:.1f}" y="{cy + 4:.1f}">{highs[i]:.1f}</text>'
        )
        parts.append(
            f'<text class="t" x="{x0 - 10}" y="{cy - 3:.1f}" text-anchor="end">'
            f"{escape(lab)}</text>"
        )
        parts.append(
            f'<text class="ts" x="{x0 - 10}" y="{cy + 12:.1f}" text-anchor="end">'
            f"median {meds[i]:.1f}</text>"
        )
    parts.append(
        f'<text class="ts" x="{(x0 + x1) / 2:.0f}" y="{height - 6}" text-anchor="middle">'
        f"{escape(xlabel)} (bar = observed min to max, tick = median)</text>"
    )
    parts.append(_close())
    return "\n".join(parts)


def lines(xs, series, ylabel, xlabel, *, width=760, height=420):
    """Multi-series line chart tolerating None gaps."""
    legend_rows = (len(series) + 1) // 2
    top = 24 + legend_rows * 18
    x0, y0, x1, y1 = 74, top, width - 14, height - 48
    vmax = _nice_max(max(v for _, _, vals in series for v in vals if v is not None))
    parts = _open(width, height, ylabel)
    _legend(parts, [(n, c) for n, c, _ in series], x0, 16, gap=(x1 - x0) / 2, cols=2)
    _grid_y(parts, x0, x1, y0, y1, vmax)
    parts.append(
        f'<text class="ts" x="14" y="{(y0 + y1) / 2:.0f}" '
        f'transform="rotate(-90 14 {(y0 + y1) / 2:.0f})" text-anchor="middle">'
        f"{escape(ylabel)}</text>"
    )
    parts.append(
        f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{AX}" stroke-opacity="0.45"/>'
    )

    def px(i):
        return x0 + (x1 - x0) * i / (len(xs) - 1)

    def py(v):
        return y1 - (y1 - y0) * v / vmax

    for i, xv in enumerate(xs):
        parts.append(
            f'<text class="ts" x="{px(i):.1f}" y="{y1 + 18}" text-anchor="middle">{xv}</text>'
        )
    for name, color, vals in series:
        dash = ' stroke-dasharray="6 4"' if "run B" in name else ""
        run: list[str] = []
        for i, v in enumerate(vals):
            if v is None:
                if len(run) > 1:
                    parts.append(
                        f'<polyline points="{" ".join(run)}" fill="none" stroke="{color}" '
                        f'stroke-width="2.2"{dash}/>'
                    )
                run = []
                continue
            run.append(f"{px(i):.1f},{py(v):.1f}")
            parts.append(
                f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="3.2" fill="{color}"/>'
            )
        if len(run) > 1:
            parts.append(
                f'<polyline points="{" ".join(run)}" fill="none" stroke="{color}" '
                f'stroke-width="2.2"{dash}/>'
            )
    parts.append(
        f'<text class="ts" x="{(x0 + x1) / 2:.0f}" y="{height - 8}" text-anchor="middle">'
        f"{escape(xlabel)}</text>"
    )
    parts.append(_close())
    return "\n".join(parts)


def scatter(
    series, xlabel, ylabel, xr, yr, *, width=760, height=400, yticks=4, xticks=5
):
    """Scatter plot with explicit axis ranges."""
    x0, y0, x1, y1 = 74, 42, width - 14, height - 48
    parts = _open(width, height, f"{ylabel} vs {xlabel}")
    _legend(parts, [(n, c) for n, c, _ in series], x0, 16, gap=(x1 - x0) / 3, cols=3)

    def sx(v):
        return x0 + (x1 - x0) * (v - xr[0]) / (xr[1] - xr[0])

    def sy(v):
        return y1 - (y1 - y0) * (v - yr[0]) / (yr[1] - yr[0])

    for i in range(yticks + 1):
        gy = yr[0] + (yr[1] - yr[0]) * i / yticks
        parts.append(
            f'<line x1="{x0}" y1="{sy(gy):.1f}" x2="{x1}" y2="{sy(gy):.1f}" '
            f'stroke="{AX}" stroke-opacity="0.16"/>'
        )
        parts.append(
            f'<text class="ts" x="{x0 - 8}" y="{sy(gy) + 4:.1f}" text-anchor="end">{gy:.0f}</text>'
        )
    for i in range(xticks + 1):
        gx = xr[0] + (xr[1] - xr[0]) * i / xticks
        parts.append(
            f'<line x1="{sx(gx):.1f}" y1="{y0}" x2="{sx(gx):.1f}" y2="{y1}" '
            f'stroke="{AX}" stroke-opacity="0.16"/>'
        )
        parts.append(
            f'<text class="ts" x="{sx(gx):.1f}" y="{y1 + 18}" text-anchor="middle">{gx:.0f}</text>'
        )
    for _, color, pts in series:
        for px_, py_ in pts:
            parts.append(
                f'<circle cx="{sx(px_):.1f}" cy="{sy(py_):.1f}" r="5.5" fill="{color}" '
                f'fill-opacity="0.85"/>'
            )
    parts.append(
        f'<text class="ts" x="{(x0 + x1) / 2:.0f}" y="{height - 8}" text-anchor="middle">'
        f"{escape(xlabel)}</text>"
    )
    parts.append(
        f'<text class="ts" x="14" y="{(y0 + y1) / 2:.0f}" '
        f'transform="rotate(-90 14 {(y0 + y1) / 2:.0f})" text-anchor="middle">'
        f"{escape(ylabel)}</text>"
    )
    parts.append(_close())
    return "\n".join(parts)


def effect_chart(*, width=760, height=320):
    """Effect sizes against the noise floor."""
    labels = [
        "Table type\n(interactive vs clustered)",
        "Clustering\n(clustered vs unclustered)",
    ]
    vals = [3.4, 18.6]
    colors = [C_INT, C_CLUST]
    x0, y0, x1, y1 = 74, 40, width - 14, height - 52
    vmax = 20.0
    parts = _open(width, height, "Effect size vs noise floor")
    _grid_y(parts, x0, x1, y0, y1, vmax, fmt="{:g}")
    parts.append(
        f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{AX}" stroke-opacity="0.45"/>'
    )
    ny = y1 - (y1 - y0) * 6 / vmax
    parts.append(
        f'<rect x="{x0}" y="{ny:.1f}" width="{x1 - x0}" height="{y1 - ny:.1f}" '
        f'fill="{C_STD}" fill-opacity="0.10"/>'
    )
    parts.append(
        f'<line x1="{x0}" y1="{ny:.1f}" x2="{x1}" y2="{ny:.1f}" stroke="{C_STD}" '
        f'stroke-width="2" stroke-dasharray="6 4"/>'
    )
    parts.append(
        f'<text class="ts" x="{x1 - 6}" y="{ny - 7:.1f}" text-anchor="end" fill="{C_STD}">'
        f"noise floor ~6% CV</text>"
    )
    slot = (x1 - x0) / 2
    for i, lab in enumerate(labels):
        gx = x0 + slot * i + slot / 2
        h = (y1 - y0) * vals[i] / vmax
        parts.append(
            f'<rect x="{gx - 46:.1f}" y="{y1 - h:.1f}" width="92" height="{h:.1f}" fill="{colors[i]}"/>'
        )
        parts.append(
            f'<text class="tb" x="{gx:.1f}" y="{y1 - h - 8:.1f}" text-anchor="middle">'
            f"{vals[i]}%</text>"
        )
        for li, line in enumerate(lab.split("\n")):
            parts.append(
                f'<text class="t" x="{gx:.1f}" y="{y1 + 19 + li * 14}" text-anchor="middle">'
                f"{escape(line)}</text>"
            )
    parts.append(
        f'<text class="ts" x="14" y="{(y0 + y1) / 2:.0f}" '
        f'transform="rotate(-90 14 {(y0 + y1) / 2:.0f})" text-anchor="middle">'
        f"% difference in mean QPS</text>"
    )
    parts.append(_close())
    return "\n".join(parts)


def flow_diagram(*, width=760, height=520):
    """Methodology flow, drawn as inline SVG."""
    boxes = [
        (250, 8, 260, 40, "Probe single query", "USE_CACHED_RESULT = FALSE", C_MUTED),
        (
            250,
            68,
            260,
            40,
            "Ramp to find saturation knee",
            "FIND_MAX_CONCURRENCY",
            C_MUTED,
        ),
        (250, 128, 260, 40, "Fix concurrency past the knee", "45 connections", C_MUTED),
        (250, 188, 260, 40, "Matrix 1 - fixed order", "9 runs", C_INT),
        (566, 264, 180, 44, "Pool and compare medians", "6 trials per config", C_CLUST),
        (
            238,
            356,
            284,
            42,
            "Matrix 2 - rotated order",
            "Latin square, 9 runs",
            C_CLUST,
        ),
        (
            150,
            442,
            460,
            50,
            "Verdict reversed - ordering artifact",
            "report no measurable difference",
            C_STD,
        ),
    ]
    parts = _open(width, height, "Test methodology flow", min_w=640)
    parts.append(
        '<defs><marker id="ar" markerWidth="9" markerHeight="7" refX="8" refY="3.5" '
        'orient="auto"><path d="M0,0 L9,3.5 L0,7 z" fill="currentColor" '
        'fill-opacity="0.6"/></marker></defs>'
    )

    def arrow(x1, y1, x2, y2):
        parts.append(
            f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{AX}" stroke-opacity="0.55" '
            f'stroke-width="1.6" fill="none" marker-end="url(#ar)"/>'
        )

    # decision diamond, centred on (380, 286)
    parts.append(
        '<path d="M380,242 L520,286 L380,330 L240,286 z" fill="none" stroke="currentColor" '
        'stroke-opacity="0.5" stroke-width="1.6"/>'
    )
    parts.append(
        '<text class="t" x="380" y="282" text-anchor="middle">Declining trend</text>'
    )
    parts.append(
        '<text class="t" x="380" y="298" text-anchor="middle">within a config?</text>'
    )

    arrow(380, 48, 380, 66)
    arrow(380, 108, 380, 126)
    arrow(380, 168, 380, 186)
    arrow(380, 228, 380, 240)
    arrow(380, 330, 380, 354)
    parts.append('<text class="ts" x="390" y="346">yes</text>')
    arrow(520, 286, 564, 286)
    parts.append('<text class="ts" x="528" y="278">no</text>')
    arrow(380, 398, 380, 440)

    for x, y, w, h, title, sub, color in boxes:
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{color}" '
            f'fill-opacity="0.15" stroke="{color}" stroke-width="1.6"/>'
        )
        parts.append(
            f'<text class="tb" x="{x + w / 2}" y="{y + 19}" text-anchor="middle">'
            f"{escape(title)}</text>"
        )
        parts.append(
            f'<text class="ts" x="{x + w / 2}" y="{y + 34}" text-anchor="middle">'
            f"{escape(sub)}</text>"
        )
    parts.append(_close())
    return "\n".join(parts)


# ------------------------------------------------------------------- assemble


def build_charts() -> dict[str, str]:
    return {
        "depth": hbars(
            ["Standard unclustered", "Standard clustered", "Interactive table"],
            [54.33, 1.0, 1.0],
            [C_STD, C_CLUST, C_INT],
            "Average clustering depth (lower is better)",
        ),
        "single_query": grouped_bars(
            ["Unclustered\n(cold)", "Unclustered\n(warm)", "Interactive\n(warm)"],
            [
                ("Compile (ms)", C_STD, [649, 129, 32]),
                ("Execution (ms)", C_INT, [342, 28, 10]),
            ],
            "Milliseconds",
            stacked=True,
            height=360,
            legend_cols=2,
        ),
        "prune": grouped_bars(
            ["Standard\nunclustered", "Standard\nclustered", "Interactive\ntable"],
            [
                ("Partitions scanned", C_STD, [53, 1, 1]),
                ("Partitions in table", C_MUTED, [1825, 256, 295]),
            ],
            "Micro-partitions",
            height=340,
            legend_cols=2,
        ),
        "ramp_qps": lines(RAMP_WORKERS, RAMP_QPS, "QPS", "Concurrent workers"),
        "ramp_p95": lines(
            RAMP_WORKERS, RAMP_P95, "p95 latency (ms)", "Concurrent workers"
        ),
        "pooled": grouped_bars(
            NAMES,
            [("Median QPS (6 trials)", C_INT, [499.5, 478.3, 401.3])],
            "QPS",
            height=330,
            value_fmt="{:.1f}",
            legend_cols=1,
        ),
        "range": range_bars(
            NAMES,
            [438.8, 432.9, 367.4],
            [519.7, 517.8, 431.0],
            [499.5, 478.3, 401.3],
            SERIES_COLORS,
            "QPS",
        ),
        "flip": grouped_bars(
            ["Matrix 1 - fixed order", "Matrix 2 - rotated order"],
            [
                (n, c, v)
                for n, c, v in zip(
                    NAMES,
                    SERIES_COLORS,
                    [[503.1, 475.5], [466.8, 490.2], [387.4, 415.2]],
                )
            ],
            "Median QPS",
            height=360,
            value_fmt="{:.1f}",
        ),
        "all_runs": grouped_bars(
            ["M1-1", "M1-2", "M1-3", "M2-1", "M2-2", "M2-3"],
            [(n, c, QPS[n]) for n, c in zip(NAMES, SERIES_COLORS)],
            "QPS",
            height=400,
        ),
        "scatter": scatter(
            [(n, c, list(zip(P50[n], QPS[n]))) for n, c in zip(NAMES, SERIES_COLORS)],
            "p50 latency (ms)",
            "QPS",
            (60, 110),
            (350, 550),
            yticks=4,
            xticks=5,
        ),
        "latency": grouped_bars(
            ["p50", "p95", "p99"],
            [
                (n, c, v)
                for n, c, v in zip(
                    NAMES,
                    SERIES_COLORS,
                    [[72.2, 151.1, 225.3], [70.9, 147.0, 209.7], [101.1, 152.9, 211.5]],
                )
            ],
            "Milliseconds (median of 6 trials)",
            height=360,
            value_fmt="{:.1f}",
        ),
        "effect": effect_chart(),
        "flow": flow_diagram(),
        "srv_exec": grouped_bars(
            ["p50", "p95", "p99"],
            [(n, c, SRV_POOLED[n]) for n, c in zip(NAMES, SERIES_COLORS)],
            "Server SQL execution (ms, pooled over 6.0M queries)",
            height=360,
            value_fmt="{:.0f}",
        ),
        "srv_share": hbars(
            ["Standard unclustered", "Standard clustered", "Interactive table"],
            [
                SRV_SHARE["Standard unclustered"],
                SRV_SHARE["Standard clustered"],
                SRV_SHARE["Interactive table"],
            ],
            [C_STD, C_CLUST, C_INT],
            "Server execution as % of end-to-end median latency",
            value_fmt="{:.1f}",
        ),
        "decomp": grouped_bars(
            ["Interactive\ntable", "Standard\nclustered", "Standard\nunclustered"],
            [
                ("Server SQL execution", C_INT, [DECOMP[n][0] for n in NAMES]),
                ("Compilation", C_CLUST, [DECOMP[n][1] for n in NAMES]),
                ("Client + network", C_MUTED, [DECOMP[n][2] for n in NAMES]),
            ],
            "Milliseconds (component medians)",
            stacked=True,
            height=380,
            value_fmt="{:.1f}",
        ),
        "srv_runs": grouped_bars(
            ["M1-1", "M1-2", "M1-3", "M2-1", "M2-2", "M2-3"],
            [(n, c, SRV_P95_RUNS[n]) for n, c in zip(NAMES, SERIES_COLORS)],
            "Server p95 execution (ms)",
            height=400,
            value_fmt="{:.0f}",
        ),
    }


def main() -> None:
    """Render the report to disk."""
    ch = build_charts()
    template = (Path(__file__).resolve().parent / "_report_body.html").read_text(
        encoding="utf-8"
    )
    for key, svg in ch.items():
        token = "{{" + key + "}}"
        if token not in template:
            raise ValueError(f"template missing placeholder {token}")
        template = template.replace(token, svg)
    OUT.write_text(template, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(ch)} charts)")


if __name__ == "__main__":
    main()
