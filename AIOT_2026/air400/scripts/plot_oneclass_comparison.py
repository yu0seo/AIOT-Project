"""Render a detailed view from saved histories, without training or changing metrics."""
import json
import os
from pathlib import Path

from air400_paths import PROJECT, RUNTIME
os.environ["MPLCONFIGDIR"] = str(RUNTIME/"matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

RUN = PROJECT/"07_이상탐지_모델비교/normal731_80_20_seed42_v1"


def main():
    font = Path("C:/Windows/Fonts/malgun.ttf")
    if font.exists():
        plt.rcParams["font.family"] = FontProperties(fname=str(font)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    comparison = json.loads((RUN/"comparison.json").read_text(encoding="utf-8"))
    models = comparison["models"]
    colors = {"autoencoder": "#d97706", "deep_svdd": "#2563eb"}
    names = {"autoencoder": "오토인코더", "deep_svdd": "Deep SVDD"}
    histories = {k: json.loads((RUN/k/"history.json").read_text(encoding="utf-8"))["epochs"] for k in colors}
    fig = plt.figure(figsize=(14, 8.5), constrained_layout=True)
    grid = fig.add_gridspec(2, 2)
    for col, name in enumerate(colors):
        ax = fig.add_subplot(grid[0, col])
        history, best = histories[name], models[name]["best_checkpoint_metrics"]
        epochs = [r["epoch"] for r in history]
        ax.plot(epochs, [r["train_loss"] for r in history], color="#64748b", ls="--", label="학습 loss")
        ax.plot(epochs, [r["valid_loss"] for r in history], color=colors[name], lw=2, label="검증 loss")
        ax.scatter([best["epoch"]], [best["valid_loss"]], color=colors[name], s=70, edgecolor="white", zorder=4)
        label = "파형 MAE + 특성 MAE" if name == "autoencoder" else "정상 중심까지의 제곱거리"
        ax.set_title(f"{names[name]} · {label}\n선택 epoch {best['epoch']} / valid loss {best['valid_loss']:.6f}")
        ax.set_xlabel("본학습 epoch"); ax.set_ylabel("Loss (모델별 척도)")
        ax.grid(alpha=.2); ax.legend(loc="upper right", fontsize=9)
    ax = fig.add_subplot(grid[1, :])
    for name, history in histories.items():
        best = models[name]["best_checkpoint_metrics"]
        ax.plot([r["epoch"] for r in history], [100*r["valid_accuracy_normal_only"] for r in history], color=colors[name], lw=2, label=names[name])
        x, y = best["epoch"], 100*best["valid_accuracy_normal_only"]
        ax.scatter([x], [y], color=colors[name], s=70, edgecolor="white", zorder=5)
        offset = (-95, 28) if name == "autoencoder" else (-12, 33)
        ax.annotate(f"{names[name]} 선택 모델\n{y:.2f}% ({best['valid_normal_accepted']}/147)",
                    xy=(x, y), xytext=offset, textcoords="offset points", fontsize=9,
                    color=colors[name], arrowprops={"arrowstyle": "-", "color": colors[name]},
                    bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": colors[name], "alpha": .95})
    ax.set_ylim(90, 100.5)
    ax.set_yticks([90, 92, 94, 96, 98, 100])
    ax.set_title("정상 검증 정확도 = 정상으로 가정한 147개 중 정상 판정 비율 (Y축 90–100.5% 확대)")
    ax.set_ylabel("정상 검증 정확도 (%)")
    ax.set_xlabel("각 모델 본학습 epoch · 기준값은 매 epoch 학습 점수의 99백분위로 갱신 · 점은 검증 loss 최저 모델")
    ax.grid(alpha=.2); ax.legend(loc="lower left")
    fig.suptitle("동일 8:2 분할 · 학습 584개 / 검증 147개 · 파형 + 호흡 간격 특성\n정상 데이터만 평가: 정확도는 정상 통과율이며 이상 검출률이 아님 / 두 모델의 loss 숫자는 직접 비교 불가", fontsize=12)
    out = RUN/"graphs"
    fig.savefig(out/"validation_curves_detail.png", dpi=160)
    fig.savefig(out/"validation_curves_detail.svg")
    plt.close(fig)
    print(out/"validation_curves_detail.png")


if __name__ == "__main__":
    main()
