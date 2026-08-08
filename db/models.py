from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import DB_URL

DEFAULT_NOTIFY_OFFSETS = (60, 15, 5)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Calendar(Base):
    __tablename__ = "calendars"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    server_url: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Contest(Base):
    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(primary_key=True)
    cf_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(16), default="")
    phase: Mapped[str] = mapped_column(String(32), default="")
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    announced: Mapped[bool] = mapped_column(Boolean, default=False)


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (UniqueConstraint("user_id", "contest_id", name="uq_registration_user_contest"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotifySetting(Base):
    __tablename__ = "notify_settings"
    __table_args__ = (UniqueConstraint("user_id", "offset_minutes", name="uq_notify_user_offset"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    offset_minutes: Mapped[int] = mapped_column(Integer)


class NotificationLog(Base):
    __tablename__ = "notification_log"
    __table_args__ = (
        UniqueConstraint("user_id", "contest_id", "offset_minutes", name="uq_notiflog_user_contest_offset"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id"), index=True)
    offset_minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


engine = create_async_engine(DB_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_user_id(tg_id: int) -> int | None:
    async with async_session() as session:
        return await session.scalar(select(User.id).where(User.tg_id == tg_id))


async def get_or_create_user(tg_id: int) -> tuple[User, bool]:
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if user is not None:
            return user, False
        user = User(tg_id=tg_id)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if user is not None:
                return user, False
            raise
        for offset in DEFAULT_NOTIFY_OFFSETS:
            session.add(NotifySetting(user_id=user.id, offset_minutes=offset))
        await session.commit()
        return user, True


async def ensure_user_id(tg_id: int) -> int:
    user, _ = await get_or_create_user(tg_id)
    return user.id
