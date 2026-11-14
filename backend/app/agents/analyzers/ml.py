"""A small logistic regression in pure Python for AI02 (no numpy/sklearn needed).

Fitted at the analysis instant on visible bars only, split chronologically:
the first 70% trains, the last 30% is scored out-of-sample (Brier, log loss,
accuracy) against the base rate of the training slice. Deterministic.
"""

from __future__ import annotations

import math

from app.agents.analyzers.bars import Candle

FEATURES = ("ret1_atr", "ret3_atr", "ret5_atr", "z20", "close_loc", "range_atr", "ema_gap_atr")


def _atr(bars: list[Candle], i: int, n: int = 14) -> float:
    trs = []
    for j in range(max(1, i - n + 1), i + 1):
        b, p = bars[j], bars[j - 1]
        trs.append(max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close)))
    return sum(trs) / len(trs) if trs else 0.0


def features(bars: list[Candle], i: int) -> list[float] | None:
    """Features of bar i, from bars[0..i] only."""
    if i < 25:
        return None
    a = _atr(bars, i)
    if a <= 0:
        return None
    c = [b.close for b in bars[: i + 1]]
    window = c[-20:]
    mean = sum(window) / 20
    sd = math.sqrt(sum((x - mean) ** 2 for x in window) / 20) or 1e-12
    k = 2 / 21
    e = c[-20]
    for x in c[-19:]:
        e = x * k + e * (1 - k)
    b = bars[i]
    rng = b.high - b.low
    return [(c[-1] - c[-2]) / a, (c[-1] - c[-4]) / a, (c[-1] - c[-6]) / a, (c[-1] - mean) / sd,
            ((b.close - b.low) / rng * 2 - 1) if rng > 0 else 0.0, rng / a, (c[-1] - e) / a]


def _sigmoid(z: float) -> float:
    z = max(-30.0, min(30.0, z))
    return 1 / (1 + math.exp(-z))


def fit(x: list[list[float]], y: list[int], *, l2: float = 0.01, lr: float = 0.1,
        epochs: int = 300) -> list[float]:
    """Batch gradient descent; returns [bias, w...]. Features are z-scored first."""
    n, d = len(x), len(x[0])
    w = [0.0] * (d + 1)
    for _ in range(epochs):
        grad = [0.0] * (d + 1)
        for xi, yi in zip(x, y, strict=True):
            err = _sigmoid(w[0] + sum(wj * xj for wj, xj in zip(w[1:], xi, strict=True))) - yi
            grad[0] += err
            for j in range(d):
                grad[j + 1] += err * xi[j]
        w[0] -= lr * grad[0] / n
        for j in range(d):
            w[j + 1] -= lr * (grad[j + 1] / n + l2 * w[j + 1])
    return w


def predict(w: list[float], xi: list[float]) -> float:
    return _sigmoid(w[0] + sum(wj * xj for wj, xj in zip(w[1:], xi, strict=True)))


def train_eval(bars: list[Candle], *, min_rows: int = 250) -> dict | None:
    rows = []
    for i in range(25, len(bars) - 1):
        f = features(bars, i)
        if f is not None:
            rows.append((f, 1 if bars[i + 1].close > bars[i].close else 0))
    last = features(bars, len(bars) - 1)
    if len(rows) < min_rows or last is None:
        return None
    cut = int(len(rows) * 0.7)
    train, test = rows[:cut], rows[cut:]
    d = len(FEATURES)
    mu = [sum(r[0][j] for r in train) / len(train) for j in range(d)]
    sd = [math.sqrt(sum((r[0][j] - mu[j]) ** 2 for r in train) / len(train)) or 1.0
          for j in range(d)]

    def z(f: list[float]) -> list[float]:
        return [(f[j] - mu[j]) / sd[j] for j in range(d)]

    w = fit([z(r[0]) for r in train], [r[1] for r in train])
    base = sum(r[1] for r in train) / len(train)
    probs = [predict(w, z(r[0])) for r in test]
    ys = [r[1] for r in test]
    brier = sum((p - yv) ** 2 for p, yv in zip(probs, ys, strict=True)) / len(ys)
    brier_base = sum((base - yv) ** 2 for yv in ys) / len(ys)
    acc = sum(1 for p, yv in zip(probs, ys, strict=True) if (p > 0.5) == (yv == 1)) / len(ys)
    eps = 1e-9
    logloss = -sum(yv * math.log(p + eps) + (1 - yv) * math.log(1 - p + eps)
                   for p, yv in zip(probs, ys, strict=True)) / len(ys)
    return {"p_up": predict(w, z(last)), "brier_oos": brier, "brier_base_oos": brier_base,
            "accuracy_oos": acc, "logloss_oos": logloss, "base_rate": base,
            "n_train": len(train), "n_test": len(test),
            "weights": dict(zip(("bias", *FEATURES), (round(v, 4) for v in w), strict=True))}
