from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.tasks._utils import run_async


class TestRunAsync:
    def test_executes_coroutine_and_returns_result(self):
        async def dummy() -> int:
            return 42

        result = run_async(dummy())
        assert result == 42

    def test_handles_string_return(self):
        async def dummy() -> str:
            return "hello"

        result = run_async(dummy())
        assert result == "hello"

    def test_handles_none_return(self):
        async def dummy() -> None:
            return None

        result = run_async(dummy())
        assert result is None

    def test_handles_exception(self):
        async def dummy() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            run_async(dummy())

    def test_handles_list_return(self):
        async def dummy() -> list[int]:
            return [1, 2, 3]

        result = run_async(dummy())
        assert result == [1, 2, 3]


class TestTaskRegistration:
    def test_app_has_expected_tasks(self):
        import src.tasks.scheduler_tasks  # noqa: F401
        import src.tasks.ml_tasks  # noqa: F401
        from src.tasks import app

        expected_tasks = {
            "run_daily_update",
            "run_weekly_update",
            "run_daily_report",
            "run_weekly_report",
            "run_monthly_report",
            "take_daily_snapshot",
            "take_weekly_snapshot",
            "take_monthly_snapshot",
            "check_smart_rules",
            "retry_failed_receipts",
            "clear_stale_feature_cache",
            "train_model",
            "train_all_models",
            "generate_signals",
            "collect_prices",
        }
        registered = set(app.tasks.keys())
        for task_name in expected_tasks:
            assert task_name in registered, f"Task {task_name} not registered"

    def test_beat_schedule_has_expected_entries(self):
        from src.tasks import app

        expected_schedule = {
            "recurring-update-every-5min",
            "smart-rules-every-30min",
            "retry-receipts-every-30min",
            "collect-prices-every-6h",
            "generate-signals-every-4h",
            "train-models-daily",
            "daily-snapshot-at-2350-msk",
            "weekly-update-on-friday",
            "weekly-snapshot-on-friday",
            "monthly-snapshot-on-1st",
            "clear-stale-cache-daily",
            "daily-report-at-2350-msk",
            "weekly-report-on-friday",
            "monthly-report-on-1st",
        }
        assert set(app.conf.beat_schedule.keys()) == expected_schedule

    def test_task_routes_are_configured(self):
        from src.tasks import app

        assert app.conf.task_routes["run_daily_update"] == {"queue": "default"}
        assert app.conf.task_routes["run_weekly_update"] == {"queue": "default"}
        assert app.conf.task_routes["generate_signals_background"] == {"queue": "ml"}
        assert app.conf.task_routes["train_model"] == {"queue": "ml"}
        assert app.conf.task_routes["train_all_models"] == {"queue": "ml"}
        assert app.conf.task_routes["collect_prices"] == {"queue": "data"}


class TestRunDailyUpdateTask:
    @patch("src.tasks.scheduler_tasks._run_async")
    def test_returns_ok_on_success(self, mock_run_async):
        from src.tasks.scheduler_tasks import run_daily_update

        result = run_daily_update.run()
        assert result == {"status": "ok"}

    @patch("src.tasks.scheduler_tasks._run_async", side_effect=ValueError("fail"))
    def test_returns_error_on_exception(self, mock_run_async):
        from src.tasks.scheduler_tasks import run_daily_update

        self_mock = MagicMock()
        self_mock.retry.side_effect = RuntimeError("retry exhausted")
        result = run_daily_update.run()
        assert result["status"] == "error"
        assert "fail" in result["error"]


class TestRunWeeklyUpdateTask:
    @patch("src.tasks.scheduler_tasks._run_async")
    def test_returns_ok_on_success(self, mock_run_async):
        from src.tasks.scheduler_tasks import run_weekly_update

        result = run_weekly_update.run()
        assert result == {"status": "ok"}

    @patch("src.tasks.scheduler_tasks._run_async", side_effect=RuntimeError("fail"))
    def test_returns_error_on_exception(self, mock_run_async):
        from src.tasks.scheduler_tasks import run_weekly_update

        self_mock = MagicMock()
        self_mock.retry.side_effect = RuntimeError("retry exhausted")
        result = run_weekly_update.run()
        assert result["status"] == "error"
        assert "fail" in result["error"]


class TestCheckSmartRulesTask:
    @patch("src.alerts.smart.SmartAlertEngine")
    @patch("src.db.connection.get_session")
    def test_returns_ok_when_no_triggers(self, mock_get_session, mock_engine_cls):
        mock_db = MagicMock()
        mock_get_session.return_value = mock_db
        mock_engine = MagicMock()
        mock_engine.evaluate_rules.return_value = []
        mock_engine_cls.return_value = mock_engine

        from src.tasks.scheduler_tasks import check_smart_rules

        result = check_smart_rules.run()
        assert result == {"status": "ok", "triggered": 0}

    @patch("src.alerts.smart.SmartAlertEngine")
    @patch("src.db.connection.get_session")
    def test_logs_triggered_alerts(self, mock_get_session, mock_engine_cls):
        mock_db = MagicMock()
        mock_get_session.return_value = mock_db
        mock_engine = MagicMock()
        mock_engine.evaluate_rules.return_value = [MagicMock(), MagicMock()]
        mock_engine_cls.return_value = mock_engine

        from src.tasks.scheduler_tasks import check_smart_rules

        result = check_smart_rules.run()
        assert result == {"status": "ok", "triggered": 2}

    @patch("src.db.connection.get_session")
    def test_raises_when_db_unavailable(self, mock_get_session):
        mock_get_session.side_effect = RuntimeError("db error")

        from src.tasks.scheduler_tasks import check_smart_rules

        with pytest.raises(RuntimeError, match="db error"):
            check_smart_rules.run()


class TestTrainModelTask:
    @patch("src.db.connection.get_session")
    def test_instrument_not_found(self, mock_get_session):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        mock_get_session.return_value = mock_db

        from src.tasks.ml_tasks import train_model

        result = train_model.run(instrument_id=999, ticker="UNKNOWN")
        assert result == {"ticker": "UNKNOWN", "status": "error", "error": "Instrument not found"}

    @patch("src.db.connection.get_session")
    def test_retry_on_exception(self, mock_get_session):
        mock_get_session.side_effect = RuntimeError("crash")

        from src.tasks.ml_tasks import train_model

        self_mock = MagicMock()
        self_mock.retry.side_effect = RuntimeError("retry exhausted")
        with pytest.raises(RuntimeError, match="crash"):
            train_model.run(instrument_id=1, ticker="SBER")


class TestTrainAllModelsTask:
    @patch("src.tasks.ml_tasks.train_model")
    @patch("src.db.connection.get_session")
    def test_queues_training_for_each_instrument(self, mock_get_session, mock_train_model):
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.group_by.return_value.having.return_value.all.return_value = [
            (1, "SBER"),
            (2, "GAZP"),
        ]
        mock_get_session.return_value = mock_db
        mock_result = MagicMock()
        mock_result.id = "abc-123"
        mock_train_model.delay.return_value = mock_result

        from src.tasks.ml_tasks import train_all_models

        result = train_all_models.run()
        assert result["instruments"] == 2
        assert result["results"]["SBER"]["status"] == "queued"
        assert result["results"]["GAZP"]["status"] == "queued"

    @patch("src.db.connection.get_session")
    def test_empty_instrument_list(self, mock_get_session):
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.group_by.return_value.having.return_value.all.return_value = []
        mock_get_session.return_value = mock_db

        from src.tasks.ml_tasks import train_all_models

        result = train_all_models.run()
        assert result["instruments"] == 0
        assert result["results"] == {}


class TestGenerateSignalsTask:
    @patch("src.scheduler.collectors.generate_signals")
    @patch("src.tasks._utils.run_async")
    def test_returns_ok_with_count(self, mock_run_async, mock_generate_signals):
        mock_run_async.return_value = 5

        from src.tasks.ml_tasks import generate_signals_background

        result = generate_signals_background.run(instrument_ids=[1, 2])
        assert result == {"status": "ok", "signals_generated": 5}

    @patch("src.scheduler.collectors.generate_signals")
    @patch("src.tasks._utils.run_async", side_effect=RuntimeError("signal fail"))
    def test_returns_error_on_exception(self, mock_run_async, mock_generate_signals):
        from src.tasks.ml_tasks import generate_signals_background

        result = generate_signals_background.run(instrument_ids=None)
        assert result["status"] == "error"
        assert "signal fail" in result["error"]


class TestClearStaleFeatureCache:
    @patch("src.analysis.feature_store.clear_stale")
    def test_returns_cleared_count(self, mock_clear_stale):
        mock_clear_stale.return_value = 10

        from src.tasks.scheduler_tasks import clear_stale_feature_cache

        result = clear_stale_feature_cache.run()
        assert result == {"status": "ok", "cleared": 10}

    @patch("src.analysis.feature_store.clear_stale")
    def test_returns_zero_when_nothing_cleared(self, mock_clear_stale):
        mock_clear_stale.return_value = 0

        from src.tasks.scheduler_tasks import clear_stale_feature_cache

        result = clear_stale_feature_cache.run()
        assert result == {"status": "ok", "cleared": 0}


class TestCollectPricesTask:
    @patch("src.scheduler.collectors.collect_prices")
    @patch("src.tasks._utils.run_async")
    @patch("src.db.connection.get_session")
    def test_returns_updated_count(self, mock_get_session, mock_run_async, mock_collect_prices):
        mock_db = MagicMock()
        mock_get_session.return_value = mock_db
        mock_run_async.return_value = 3

        from src.tasks.ml_tasks import collect_prices_background

        result = collect_prices_background.run()
        assert result == {"status": "ok", "updated_instruments": 3}

    @patch("src.scheduler.collectors.collect_prices")
    @patch("src.tasks._utils.run_async", side_effect=RuntimeError("collect fail"))
    @patch("src.db.connection.get_session")
    def test_returns_error_on_exception(self, mock_get_session, mock_run_async, mock_collect_prices):
        mock_db = MagicMock()
        mock_get_session.return_value = mock_db

        from src.tasks.ml_tasks import collect_prices_background

        result = collect_prices_background.run()
        assert result["status"] == "error"
        assert "collect fail" in result["error"]
