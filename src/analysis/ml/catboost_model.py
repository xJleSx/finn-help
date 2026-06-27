import logging
from typing import Any

from catboost import CatBoostClassifier

from src.analysis.ml._base import BaseMLClassifier

logger = logging.getLogger(__name__)


class CatBoostClassifierModel(BaseMLClassifier):
    @property
    def _model_prefix(self) -> str:
        return "cat"

    def _create_model(self) -> Any:
        return CatBoostClassifier(
            iterations=self._common_model_params["n_estimators"],
            max_depth=self._common_model_params["max_depth"],
            learning_rate=self._common_model_params["learning_rate"],
            verbose=0,
            allow_writing_files=False,
        )
