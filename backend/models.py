import os
import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "waste_sorting.db")

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

DEFAULT_BINS = ["cardboard", "glass", "metal", "paper", "plastic", "trash"]


class SortEvent(Base):
    __tablename__ = "sort_events"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    detected_class = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    assigned_bin = Column(String(50), nullable=False)
    success = Column(Boolean, default=True)
    image_path = Column(String(500), nullable=True)


class BinStatus(Base):
    __tablename__ = "bin_status"

    id = Column(Integer, primary_key=True)
    bin_name = Column(String(50), unique=True, nullable=False)
    item_count = Column(Integer, default=0)
    capacity = Column(Integer, default=50)
    fill_percentage = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=func.now())
    event_type = Column(String(50))  # 'detection', 'sort', 'alert', 'error', 'system'
    message = Column(String(500))
    severity = Column(String(20), default="info")  # 'info', 'warning', 'error', 'critical'


def init_db():
    """Create database tables and seed default waste bins idempotently."""
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        for bin_name in DEFAULT_BINS:
            existing = (
                session.query(BinStatus)
                .filter(BinStatus.bin_name == bin_name)
                .first()
            )
            if existing is None:
                session.merge(BinStatus(bin_name=bin_name))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print("Database initialized")


if __name__ == "__main__":
    init_db()
