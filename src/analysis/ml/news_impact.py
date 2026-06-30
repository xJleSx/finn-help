from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import torch
import torch.nn as nn

from src.analysis.ml._base import BaseRegressor, log_feature_importance
from src.analysis.ml.news_impact_features import (
    ALL_FEATURE_COLS,
    build_training_data,
    extract_features,
)
from src.config import settings
from src.model_registry import load_model as load_from_registry

logger = logging.getLogger(__name__)

LSTM_HIDDEN = 64
LSTM_LAYERS = 2
LSTM_DROPOUT = 0.2
LSTM_EPOCHS = 100
LSTM_LR = 0.001
LSTM_SEQ_LEN = 10


class LSTMPredictor(nn.Module):
    def __init__(
        self, input_dim: int, hidden: int = LSTM_HIDDEN,
        layers: int = LSTM_LAYERS, dropout: float = LSTM_DROPOUT,
    ):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden, layers, batch_first=True, dropout=dropout if layers > 1 else 0)
        self.fc = nn.Linear(hidden, 1)
        self.layers = layers

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        out = self.fc(out[:, -1, :])
        return out.squeeze(-1)


def _build_sequences(features: np.ndarray, targets: np.ndarray, seq_len: int = LSTM_SEQ_LEN):
    xs, ys = [], []
    for i in range(len(features) - seq_len):
        xs.append(features[i : i + seq_len])
        ys.append(targets[i + seq_len])
    if not xs:
        return np.empty((0, seq_len, features.shape[1])), np.empty(0)
    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)


class NewsImpactModel(BaseRegressor):
    def __init__(self, ticker: str = ""):
        super().__init__(ticker)
        self._models: dict[int, Any] = {}
        self._lstm_models: dict[int, Any] = {}
        self._feature_names: list[str] = list(ALL_FEATURE_COLS)

    @property
    def _model_prefix(self) -> str:
        return "news_impact"

    def _model_name(self, horizon_days: int) -> str:
        return f"{self.model_name}_{horizon_days}d"

    def _lstm_model_name(self, horizon_days: int) -> str:
        return f"{self.model_name}_{horizon_days}d_lstm"

    @property
    def horizons(self) -> list[int]:
        return sorted(int(h) for h in settings.ml_impact_horizons.split(","))

    def _create_model(self) -> Any:
        import xgboost as xgb
        return xgb.XGBRegressor(
            n_estimators=settings.ml_impact_n_estimators,
            max_depth=settings.ml_impact_max_depth,
            learning_rate=settings.ml_impact_learning_rate,
            objective="reg:squarederror",
            verbosity=0,
        )

    def _train_lstm(
        self, x_train: np.ndarray, y_train: np.ndarray, input_dim: int
    ) -> LSTMPredictor:
        model = LSTMPredictor(input_dim=input_dim)
        optimizer = torch.optim.Adam(model.parameters(), lr=LSTM_LR)
        loss_fn = nn.MSELoss()

        x_t = torch.from_numpy(x_train)
        y_t = torch.from_numpy(y_train)

        model.train()
        for epoch in range(LSTM_EPOCHS):
            optimizer.zero_grad()
            pred = model(x_t)
            loss = loss_fn(pred, y_t)
            loss.backward()
            optimizer.step()

        return model

    def _predict_lstm(self, model: LSTMPredictor, features_seq: np.ndarray) -> float:
        model.eval()
        with torch.no_grad():
            x_t = torch.from_numpy(features_seq)
            pred = model(x_t)
            return float(pred.item())

    def train(self, db: Any, ticker: Optional[str] = None) -> dict[str, Any]:
        ticker = (ticker or self._ticker).upper()
        df = build_training_data(db, ticker)
        if df.empty or len(df) < settings.ml_impact_min_train_samples:
            logger.warning("Not enough samples for %s: %d", ticker, len(df))
            return {"ticker": ticker, "trained": False, "samples": len(df)}

        results: dict[str, Any] = {"ticker": ticker, "trained": True, "horizons": {}}
        for h in self.horizons:
            target = f"return_{h}d"
            if target not in df.columns:
                continue
            clean = df[self._feature_names + [target]].dropna()
            if len(clean) < settings.ml_impact_min_train_samples:
                continue

            x = clean[self._feature_names].values.astype(np.float32)
            y = clean[target].values.astype(np.float32)

            split = int(len(x) * 0.8)
            x_train, x_val = x[:split], x[split:]
            y_train, y_val = y[:split], y[split:]

            xgb_model = self._create_model()
            xgb_model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
            xgb_preds = xgb_model.predict(x_val)
            self._models[h] = xgb_model

            rmse_xgb = float(np.sqrt(np.mean((xgb_preds - y_val) ** 2)))
            mae_xgb = float(np.mean(np.abs(xgb_preds - y_val)))
            dir_acc_xgb = float(np.mean((np.sign(xgb_preds) == np.sign(y_val)) | (np.abs(y_val) < 0.001)))

            fi = log_feature_importance(xgb_model, self._feature_names)

            has_lstm = False
            lstm_rmse = 0.0
            lstm_dir_acc = 0.0
            xs, ys = _build_sequences(x, y, LSTM_SEQ_LEN)
            if len(xs) >= settings.ml_impact_min_train_samples:
                seq_split = int(len(xs) * 0.8)
                xs_train, xs_val = xs[:seq_split], xs[seq_split:]
                ys_train, ys_val = ys[:seq_split], ys[seq_split:]

                lstm_model = self._train_lstm(xs_train, ys_train, x.shape[1])

                lstm_model.eval()
                with torch.no_grad():
                    lstm_preds = lstm_model(torch.from_numpy(xs_val)).numpy()

                lstm_rmse = float(np.sqrt(np.mean((lstm_preds - ys_val) ** 2)))
                lstm_dir_acc = float(np.mean((np.sign(lstm_preds) == np.sign(ys_val)) | (np.abs(ys_val) < 0.001)))

                self._lstm_models[h] = lstm_model
                torch.save(lstm_model.state_dict(), f"{self._lstm_model_name(h)}.pt")
                has_lstm = True

            if has_lstm and len(xs_val) == len(x_val[LSTM_SEQ_LEN:]):
                xgb_ens = xgb_preds
                lstm_ens = lstm_preds[:len(xgb_ens)]
                ens_preds = (xgb_ens + lstm_ens) / 2.0
                ens_rmse = float(np.sqrt(np.mean((ens_preds - y_val[LSTM_SEQ_LEN:]) ** 2)))
                y_val_trim = y_val[LSTM_SEQ_LEN:]
                ens_dir_acc = float(
                    np.mean(
                        (np.sign(ens_preds) == np.sign(y_val_trim))
                        | (np.abs(y_val_trim) < 0.001)
                    )
                )
            else:
                ens_rmse = rmse_xgb
                ens_dir_acc = dir_acc_xgb

            metrics = {
                "rmse": round(rmse_xgb, 4),
                "mae": round(mae_xgb, 4),
                "direction_accuracy": round(dir_acc_xgb, 4),
                "ensemble_rmse": round(ens_rmse, 4),
                "ensemble_direction_accuracy": round(ens_dir_acc, 4),
                "lstm_available": has_lstm,
            }
            if has_lstm:
                metrics["lstm_rmse"] = round(lstm_rmse, 4)
                metrics["lstm_direction_accuracy"] = round(lstm_dir_acc, 4)
            if fi:
                metrics["top_features"] = fi[:5]

            from src.model_registry import save_model
            save_model(xgb_model, self._model_name(h), metrics=metrics)
            logger.info(
                "%s %dd — RMSE=%.4f LSTM=%.4f Ens=%.4f DirAcc=%.2f (n=%d)",
                ticker, h, rmse_xgb, lstm_rmse if has_lstm else 0, ens_rmse, ens_dir_acc, len(y_val),
            )
            results["horizons"][h] = metrics

        return results

    def predict(self, db: Any, news_article: Any, horizon_days: int = 1) -> dict[str, Any]:
        model = self._models.get(horizon_days)
        if model is None:
            try:
                model = load_from_registry(self._model_name(horizon_days))
                self._models[horizon_days] = model
            except (ValueError, FileNotFoundError):
                return {"predicted_return": 0.0, "confidence": 0.0, "model_loaded": False}

        features = extract_features(db, news_article)
        vec = np.array([features.get(c, 0.0) for c in self._feature_names], dtype=np.float32).reshape(1, -1)

        xgb_pred = float(model.predict(vec)[0])

        lstm_pred = 0.0
        lstm_model = self._lstm_models.get(horizon_days)
        if lstm_model is None:
            try:
                lstm_path = f"{self._lstm_model_name(horizon_days)}.pt"
                import os
                if os.path.exists(lstm_path):
                    lstm_model = LSTMPredictor(input_dim=len(self._feature_names))
                    lstm_model.load_state_dict(torch.load(lstm_path))
                    self._lstm_models[horizon_days] = lstm_model
            except Exception:
                pass

        if lstm_model is not None:
            with torch.no_grad():
                lstm_pred = float(lstm_model(torch.from_numpy(vec.reshape(1, 1, -1))).item())

        if lstm_model is not None:
            final_pred = (xgb_pred + lstm_pred) / 2.0
        else:
            final_pred = xgb_pred

        confidence = min(1.0, abs(final_pred) * 10.0)
        if lstm_model is not None:
            agreement = 1.0 - min(1.0, abs(xgb_pred - lstm_pred) / (abs(final_pred) + 1e-8))
            confidence = confidence * 0.5 + agreement * 0.5

        return {
            "predicted_return": round(final_pred, 4),
            "xgb_prediction": round(xgb_pred, 4),
            "lstm_prediction": round(lstm_pred, 4) if lstm_model is not None else None,
            "confidence": round(confidence, 4),
            "model_loaded": True,
        }

    def evaluate(self, db: Any, ticker: Optional[str] = None) -> dict[str, Any]:
        ticker = (ticker or self._ticker).upper()
        df = build_training_data(db, ticker)
        if df.empty:
            return {}

        results: dict[str, Any] = {}
        for h in self.horizons:
            model = self._models.get(h)
            if model is None:
                try:
                    model = load_from_registry(self._model_name(h))
                except (ValueError, FileNotFoundError):
                    continue
                self._models[h] = model

            target = f"return_{h}d"
            clean = df[self._feature_names + [target]].dropna()
            if clean.empty:
                continue

            x = clean[self._feature_names].values.astype(np.float32)
            y = clean[target].values.astype(np.float32)
            preds = model.predict(x)

            rmse = float(np.sqrt(np.mean((preds - y) ** 2)))
            mae = float(np.mean(np.abs(preds - y)))
            dir_acc = float(np.mean((np.sign(preds) == np.sign(y)) | (np.abs(y) < 0.001)))

            results[f"{h}d"] = {
                "rmse": round(rmse, 4),
                "mae": round(mae, 4),
                "direction_accuracy": round(dir_acc, 4),
                "samples": len(y),
            }
        return results

    def _feature_importance(self, model: Any) -> list[dict[str, Any]]:
        return log_feature_importance(model, self._feature_names)

    def load(self, horizon_days: int) -> Any:
        model = load_from_registry(self._model_name(horizon_days))
        self._models[horizon_days] = model
        return model
