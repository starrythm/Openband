"""Render the README illustration with hand-authored, simulated health data."""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]

# These values were made for the illustration. This tool has no data input.
DAYS = tuple(range(1, 15))
HEART = (71, 68, 70, 73, 76, 73, 69, 68, 72, 77, 74, 70, 71, 69)
STRESS = (31, 28, 30, 39, 45, 40, 32, 29, 33, 43, 38, 31, 34, 30)
LIGHT = (282, 293, 264, 262, 233, 259, 289, 309, 273, 236, 265, 284, 276, 298)
DEEP = (96, 108, 94, 89, 77, 91, 113, 109, 106, 81, 92, 110, 105, 114)
STEPS = (6490, 7780, 7120, 9030, 10550, 8240, 6020, 7270, 8390, 9750, 8900, 6720, 7880, 8400)

BACKGROUND = "#f7f9fc"
TEXT = "#182438"
SECONDARY = "#4b5d75"
GRID = "#dce4ef"


def panel(ax, title, unit, ticks):
    ax.set_title(title, loc="left", pad=13, fontsize=16, fontweight="bold", color=TEXT)
    ax.set_ylabel(unit, labelpad=8, color=SECONDARY, fontsize=10)
    ax.set_axisbelow(True)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(axis="both", length=0, labelsize=9, colors=SECONDARY, pad=7)
    ax.set_xlim(0.45, 14.55)
    ax.set_xticks([1, 4, 7, 10, 14], ["6/1", "6/4", "6/7", "6/10", "6/14"])
    ax.set_yticks(ticks)
    for edge in ("left", "top", "right"):
        ax.spines[edge].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def trend(ax, values, color, bottom):
    ax.fill_between(DAYS, bottom, values, color=color, alpha=.10, linewidth=0)
    ax.plot(DAYS, values, color=color, linewidth=2.3, marker="o", markersize=3.2)


def render(target, font_path):
    if font_path.is_file():
        font_manager.fontManager.addfont(str(font_path))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=font_path).get_name()
    else:
        plt.rcParams["font.family"] = ["Noto Sans CJK SC", "Microsoft YaHei", "sans-serif"]

    figure, ((heart, stress), (sleep, steps)) = plt.subplots(
        2, 2, figsize=(12, 8.0), facecolor=BACKGROUND,
        gridspec_kw={"wspace": .24, "hspace": .46},
    )
    figure.subplots_adjust(left=.087, right=.949, bottom=.11, top=.78)
    figure.text(.087, .928, "Openband  健康趋势", fontsize=28, fontweight="bold", color=TEXT)
    figure.text(.089, .874, "模拟数据  /  6 月 1–14 日", fontsize=12, color=SECONDARY)
    figure.text(.087, .041, "示例展示心率、压力、睡眠分期与每日步数。", fontsize=10, color=SECONDARY)

    for ax in (heart, stress, sleep, steps):
        ax.set_facecolor(BACKGROUND)
    panel(heart, "每日平均心率", "次 / 分钟", [60, 65, 70, 75, 80])
    heart.set_ylim(60, 82)
    trend(heart, HEART, "#c85264", 60)
    panel(stress, "每日平均压力", "设备读数", [0, 15, 30, 45, 60])
    stress.set_ylim(0, 63)
    trend(stress, STRESS, "#a2571c", 0)
    panel(sleep, "睡眠分期", "分钟", [0, 120, 240, 360, 480])
    sleep.set_ylim(0, 480)
    sleep.bar(DAYS, DEEP, width=.64, color="#5b46a8", label="深睡")
    sleep.bar(DAYS, LIGHT, bottom=DEEP, width=.64, color="#b9a6e9", label="浅睡")
    sleep.legend(loc="upper right", ncols=2, frameon=False, fontsize=9, labelcolor=SECONDARY)
    panel(steps, "每日步数", "步", [0, 3000, 6000, 9000, 12000])
    steps.set_ylim(0, 12000)
    steps.bar(DAYS, STEPS, width=.64, color="#178677")
    steps.yaxis.set_major_formatter(lambda value, _: f"{value:,.0f}")

    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=145, facecolor=BACKGROUND, metadata={"Software": None})
    plt.close(figure)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--out", type=Path, default=ROOT / "docs" / "images" / "health-example.png")
    cli.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msyh.ttc"))
    args = cli.parse_args()
    render(args.out, args.font)
