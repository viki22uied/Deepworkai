"""
Tiny, dependency-free text classifier: TF-IDF (word 1–2 grams, sublinear tf,
L2-normalised) + class-balanced multinomial logistic regression.

Same model family the classifier used from scikit-learn, but scikit-learn +
numpy + scipy cost ~130 MB of RAM in the background service just to score
short notification texts. This trains on a few hundred samples in well under
a second and uses kilobytes.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

_TOKEN = re.compile(r"(?u)\b\w\w+\b")


def _features(text: str) -> list[str]:
    words = _TOKEN.findall(text.lower())
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]


class TinyTextClassifier:
    def __init__(self, max_features: int = 2000, c: float = 1.5, epochs: int = 300, lr: float = 0.5):
        self.max_features, self.c, self.epochs, self.lr = max_features, c, epochs, lr
        self.vocab: dict[str, int] = {}
        self.idf: list[float] = []
        self.classes_: list[str] = []
        self.w: list[list[float]] = []      # [class][feature]
        self.b: list[float] = []

    # ── vectoriser ────────────────────────────────────────────────────────────
    def _vec(self, text: str) -> dict[int, float]:
        tf = Counter(f for f in _features(text) if f in self.vocab)
        v = {self.vocab[f]: (1 + math.log(n)) * self.idf[self.vocab[f]] for f, n in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {i: x / norm for i, x in v.items()}

    def fit(self, texts: list[str], labels: list[str]) -> "TinyTextClassifier":
        docs = [set(_features(t)) for t in texts]
        df = Counter(f for d in docs for f in d)
        keep = [f for f, _ in df.most_common(self.max_features)]
        self.vocab = {f: i for i, f in enumerate(sorted(keep))}
        n = len(texts)
        self.idf = [0.0] * len(self.vocab)
        for f, i in self.vocab.items():
            self.idf[i] = math.log((1 + n) / (1 + df[f])) + 1
        X = [self._vec(t) for t in texts]
        self.classes_ = sorted(set(labels))
        k, d = len(self.classes_), len(self.vocab)
        y = [self.classes_.index(l) for l in labels]
        counts = Counter(y)
        cw = {j: n / (k * counts[j]) for j in counts}                  # class_weight="balanced"
        self.w = [[0.0] * d for _ in range(k)]
        self.b = [0.0] * k
        reg = 1.0 / (self.c * n)
        for _ in range(self.epochs):                                    # full-batch gradient descent
            gw = [defaultdict(float) for _ in range(k)]
            gb = [0.0] * k
            for xi, yi in zip(X, y):
                p = self._proba_vec(xi)
                s = cw[yi] / n
                for j in range(k):
                    g = (p[j] - (1.0 if j == yi else 0.0)) * s
                    gb[j] += g
                    for f, v in xi.items():
                        gw[j][f] += g * v
            for j in range(k):
                row = self.w[j]
                for f in range(d):
                    row[f] -= self.lr * (gw[j].get(f, 0.0) + reg * row[f])
                self.b[j] -= self.lr * gb[j]
        return self

    def _proba_vec(self, x: dict[int, float]) -> list[float]:
        z = [self.b[j] + sum(self.w[j][f] * v for f, v in x.items()) for j in range(len(self.classes_))]
        m = max(z)
        e = [math.exp(v - m) for v in z]
        s = sum(e)
        return [v / s for v in e]

    def predict_proba(self, text: str) -> list[float]:
        return self._proba_vec(self._vec(text))

    def predict(self, text: str) -> tuple[str, float]:
        p = self.predict_proba(text)
        j = max(range(len(p)), key=p.__getitem__)
        return self.classes_[j], p[j]
