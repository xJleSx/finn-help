from __future__ import annotations

import logging
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from src.analysis.ml.news_impact_features import ALL_FEATURE_COLS, build_training_data
from src.config import settings

logger = logging.getLogger(__name__)


class _Autoencoder(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 8) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, input_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        encoded = self.encoder(x)
        decoded = self.decoder(encoded)
        return decoded


class AutoencoderAnomalyDetector:
    def __init__(self, input_dim: int | None = None) -> None:
        self.input_dim = input_dim or len(ALL_FEATURE_COLS)
        self._model: _Autoencoder | None = None
        self._threshold: float = 0.0
        self._trained = False
        self._losses: list[float] = []

    def train(self, db: Any, ticker: str | None = None) -> dict[str, Any]:
        if not ticker:
            return {"trained": False, "reason": "no ticker"}
        df = build_training_data(db, ticker)
        if df.empty or len(df) < settings.ml_anomaly_min_samples:
            return {"trained": False, "reason": "insufficient data"}
        present = [c for c in ALL_FEATURE_COLS if c in df.columns]
        x = df[present].values.astype(np.float32)
        self.input_dim = len(present)

        self._model = _Autoencoder(self.input_dim, settings.ml_anomaly_autoencoder_hidden_dim)
        tensor_x = torch.from_numpy(x)
        loader = torch.utils.data.DataLoader(tensor_x, batch_size=32, shuffle=True)

        optimizer = optim.Adam(
            self._model.parameters(), lr=settings.ml_anomaly_autoencoder_lr
        )
        criterion = nn.MSELoss()

        self._model.train()
        epochs = settings.ml_anomaly_autoencoder_epochs
        for _ in range(epochs):
            epoch_loss = 0.0
            for batch in loader:
                optimizer.zero_grad()
                output = self._model(batch)
                loss = criterion(output, batch)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item()
            self._losses.append(epoch_loss / max(len(loader), 1))

        self._model.eval()
        with torch.no_grad():
            recon = self._model(tensor_x)
            errors = torch.mean((recon - tensor_x) ** 2, dim=1).numpy()
        self._threshold = float(
            np.percentile(errors, (1 - settings.ml_anomaly_autoencoder_contamination) * 100)
        )
        self._trained = True
        return {
            "trained": True,
            "samples": len(x),
            "features": self.input_dim,
            "threshold": self._threshold,
            "final_loss": self._losses[-1] if self._losses else 0.0,
        }

    def predict(self, features: np.ndarray) -> float:
        if self._model is None:
            return 0.0
        tensor_x = torch.from_numpy(features.reshape(1, -1).astype(np.float32))
        self._model.eval()
        with torch.no_grad():
            recon = self._model(tensor_x)
            error = float(torch.mean((recon - tensor_x) ** 2).item())
        if self._threshold > 0:
            return float(min(error / self._threshold, 1.0))
        return float(min(error, 1.0))

    def predict_article(self, db: Any, news_article: Any) -> float:
        from src.analysis.anomaly.features import build_anomaly_feature_vector

        vec = build_anomaly_feature_vector(db, news_article)
        if len(vec) != self.input_dim:
            if len(vec) > self.input_dim:
                vec = vec[: self.input_dim]
            else:
                padded = np.zeros(self.input_dim, dtype=np.float32)
                padded[: len(vec)] = vec
                vec = padded
        return self.predict(vec)

    @property
    def trained(self) -> bool:
        return self._trained
