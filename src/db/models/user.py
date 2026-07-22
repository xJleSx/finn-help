from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from .base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="user")
    is_active = Column(Boolean, default=True)
    risk_profile = Column(String(20), default="balanced")
    totp_secret = Column(String(32), nullable=True)
    totp_enabled = Column(Boolean, default=False)
    recovery_codes = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserSetting(Base):
    __tablename__ = "user_settings"

    # TODO: EAV anti-pattern — migrate to typed columns per setting
    key = Column(String(100), primary_key=True)
    value = Column(Text)


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "ticker", name="uq_user_favorite_ticker"),)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    notify_signal = Column(Boolean, default=True)
    notify_daily = Column(Boolean, default=True)
    notify_geo = Column(Boolean, default=False)
    notify_dividend = Column(Boolean, default=False)
    notify_trade = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("user_id", name="uq_subscription_user"),)


class AuthorSubscription(Base):
    __tablename__ = "author_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False)
    author_nick = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "author_nick", name="uq_user_author_sub"),
        Index("ix_author_sub_author", "author_nick"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    type = Column(String(20), nullable=False)
    title = Column(String(200))
    message = Column(Text, nullable=False)
    data_json = Column(JSON)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "read"),
        Index("ix_notifications_created", "created_at"),
    )


class ChannelPreference(Base):
    __tablename__ = "channel_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    enabled = Column(Boolean, default=True)
    min_severity = Column(String(20), default="LOW")
    quiet_hours_start = Column(String(5), nullable=True)
    quiet_hours_end = Column(String(5), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("user_id", "channel", name="uq_user_channel"),)


class MutedAlert(Base):
    __tablename__ = "muted_alerts"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    alert_type = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "ticker", "alert_type", name="uq_user_muted_alert"),)


class BrokerCredential(Base):
    __tablename__ = "broker_credentials"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    broker_name = Column(String(20), nullable=False)
    token_encrypted = Column(Text, nullable=False)
    token_type = Column(String(20), default="access")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("user_id", "broker_name", "token_type", name="uq_user_broker_token"),)

    def set_token(self, plaintext: str) -> None:
        from src.core.crypto import encrypt
        self.token_encrypted = encrypt(plaintext)

    def get_token(self) -> str:
        from src.core.crypto import decrypt
        return decrypt(self.token_encrypted)


class UserProfileModel(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, unique=True, index=True)
    risk_profile = Column(String(20), default="balanced")
    investment_horizon = Column(String(20), default="medium")
    capital = Column(Float, default=100_000.0)
    preferences = Column(JSON, default=dict)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class SmartAlertRule(Base):
    __tablename__ = "smart_alert_rules"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    name = Column(String(100), nullable=True)
    rule_type = Column(String(20), nullable=False)
    ticker = Column(String(20), nullable=False)
    condition = Column(String(10), nullable=False)
    threshold = Column(Float, nullable=False)
    schedule = Column(String(50), nullable=True)
    enabled = Column(Boolean, default=True)
    last_triggered = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())


class NotificationReceipt(Base):
    __tablename__ = "notification_receipts"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    notification_type = Column(String(50), nullable=True)
    title = Column(String(200), nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    last_error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    delivered_at = Column(DateTime, nullable=True)


class AlertLog(Base):
    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False, index=True)
    severity = Column(Float, nullable=False, default=0.0)
    title = Column(String(512), nullable=False)
    message = Column(Text)
    created_at = Column(DateTime, default=func.now(), index=True)
    read = Column(Boolean, default=False)
    user_id = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_alert_log_ticker_created", "ticker", "created_at"),
        Index("ix_alert_log_type_created", "alert_type", "created_at"),
    )
