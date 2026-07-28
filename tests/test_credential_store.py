from unittest.mock import MagicMock, patch

from src.core.credential_store import (
    delete_broker_token,
    get_broker_token,
    list_broker_tokens,
    set_broker_token,
)


class TestGetBrokerToken:
    def test_db_token_returned(self):
        mock_db = MagicMock()
        mock_cred = MagicMock()
        mock_cred.get_token.return_value = "db_token_123"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_cred
        result = get_broker_token(1, "tbank", mock_db)
        assert result == "db_token_123"

    def test_fallback_to_env_when_no_db(self):
        with patch("src.config.settings") as mock_settings:
            mock_settings.tinkoff_token = "env_token"
            result = get_broker_token(0, "tbank", None)
            assert result == "env_token"

    def test_fallback_on_exception(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB error")
        with patch("src.config.settings") as mock_settings:
            mock_settings.tinkoff_token = "fallback"
            result = get_broker_token(1, "tbank", mock_db)
            assert result == "fallback"

    def test_unknown_broker_fallsback_settings(self):
        with patch("src.config.settings") as mock_settings:
            mock_settings.tinkoff_token = "default_token"
            result = get_broker_token(0, "unknown_broker", None)
            assert result is None


class TestSetBrokerToken:
    def test_new_credential_created(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("src.core.crypto.encrypt", return_value="gAAAAAencrypted"):
            set_broker_token(1, "tbank", "new_token", mock_db)
        assert mock_db.add.called
        mock_db.commit.assert_called_once()

    def test_existing_credential_updated(self):
        mock_db = MagicMock()
        mock_cred = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_cred
        set_broker_token(1, "tbank", "updated_token", mock_db)
        mock_cred.set_token.assert_called_with("updated_token")
        mock_db.commit.assert_called_once()


class TestDeleteBrokerToken:
    def test_delete_existing(self):
        mock_db = MagicMock()
        mock_cred = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_cred
        result = delete_broker_token(1, "tbank", mock_db)
        assert result is True
        mock_db.delete.assert_called_with(mock_cred)

    def test_delete_nonexistent(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = delete_broker_token(1, "tbank", mock_db)
        assert result is False


class TestListBrokerTokens:
    def test_empty_list(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        result = list_broker_tokens(1, mock_db)
        assert result == []

    def test_returns_credentials(self):
        mock_db = MagicMock()
        mock_cred = MagicMock()
        mock_cred.broker_name = "tbank"
        mock_cred.token_type = "access"
        mock_cred.is_active = True
        mock_cred.created_at = None
        mock_cred.updated_at = None
        mock_cred.token_encrypted = "gAAAAAencrypted"
        mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_cred]
        result = list_broker_tokens(1, mock_db)
        assert len(result) == 1
        assert result[0]["broker_name"] == "tbank"
        assert result[0]["has_token"] is True
