import logging
from typing import Any

import xgboost as xgb

from src.analysis.ml._base import BaseMLClassifier

logger = logging.getLogger(__name__)


class XGBoostClassifier(BaseMLClassifier):
    @property
    def _model_prefix(self) -> str:
        return "xgb"

    def _create_model(self) -> Any:
        return xgb.XGBClassifier(
            **self._common_model_params,
            eval_metric="logloss",
            verbosity=0,
        )
