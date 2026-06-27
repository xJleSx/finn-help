import logging
import warnings
from typing import Any

import lightgbm as lgb

from src.analysis.ml._base import BaseMLClassifier

warnings.filterwarnings("ignore", message="X does not have valid feature names", category=UserWarning, module="sklearn")

logger = logging.getLogger(__name__)


class LightGBMClassifier(BaseMLClassifier):
    @property
    def _model_prefix(self) -> str:
        return "lgb"

    def _create_model(self) -> Any:
        return lgb.LGBMClassifier(
            **self._common_model_params,
            verbosity=-1,
            deterministic=True,
            predict_disable_shape_check=True,
        )

    def _post_load(self, model: Any) -> Any:
        if model is not None and hasattr(model, "set_params"):
            model.set_params(predict_disable_shape_check=True)
        return model

    def _predict_latest(self, features: Any) -> float:
        if hasattr(self._model, "set_params"):
            self._model.set_params(predict_disable_shape_check=True)
        return super()._predict_latest(features)
