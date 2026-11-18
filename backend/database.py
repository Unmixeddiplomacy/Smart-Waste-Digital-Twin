import datetime
from collections import Counter

try:
    from backend.models import (
        SessionLocal,
        SortEvent,
        BinStatus,
        SystemLog,
        init_db,
        DEFAULT_BINS,
    )
except ImportError:
    from models import (
        SessionLocal,
        SortEvent,
        BinStatus,
        SystemLog,
        init_db,
        DEFAULT_BINS,
    )


def get_db_session():
    """Return a new SQLAlchemy session (supports context-manager `with` usage)."""
    return SessionLocal()


def add_sort_event(
    detected_class,
    confidence,
    assigned_bin,
    success=True,
    image_path=None,
):
    """Record a sorting event, update bin status, and log an alert if bin >= 90% full."""
    session = get_db_session()
    try:
        event = SortEvent(
            detected_class=detected_class,
            confidence=float(confidence),
            assigned_bin=assigned_bin,
            success=bool(success),
            image_path=image_path,
        )
        session.add(event)

        bin_row = (
            session.query(BinStatus)
            .filter(BinStatus.bin_name == assigned_bin)
            .first()
        )
        if bin_row is not None:
            bin_row.item_count = (bin_row.item_count or 0) + 1
            capacity = bin_row.capacity or 50
            raw_pct = (bin_row.item_count / capacity) * 100.0
            bin_row.fill_percentage = round(min(raw_pct, 100.0), 2)

            if bin_row.fill_percentage >= 90.0:
                alert = SystemLog(
                    event_type="alert",
                    message=f"Bin {assigned_bin} almost full ({bin_row.fill_percentage:.1f}%)",
                    severity="warning",
                )
                session.add(alert)

        session.commit()
        session.refresh(event)
        return event.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_recent_events(limit=50):
    """Return the most recent sort events ordered newest-first as plain JSON-safe dicts."""
    session = get_db_session()
    try:
        events = (
            session.query(SortEvent)
            .order_by(SortEvent.timestamp.desc(), SortEvent.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "detected_class": e.detected_class,
                "confidence": e.confidence,
                "assigned_bin": e.assigned_bin,
                "success": e.success,
                "image_path": e.image_path,
            }
            for e in events
        ]
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_bin_statuses():
    """Return all bin statuses as plain JSON-safe dicts."""
    session = get_db_session()
    try:
        bins = session.query(BinStatus).order_by(BinStatus.id.asc()).all()
        return [
            {
                "bin_name": b.bin_name,
                "item_count": b.item_count,
                "capacity": b.capacity,
                "fill_percentage": round(min(float(b.fill_percentage or 0.0), 100.0), 2),
                "last_updated": b.last_updated.isoformat() if b.last_updated else None,
            }
            for b in bins
        ]
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_statistics():
    """Compute overall sorting statistics, per-class counts, 10-min rate, and 30-min trend."""
    session = get_db_session()
    try:
        events = session.query(SortEvent).all()
        total_sorted = len(events)

        per_class = {cls: 0 for cls in DEFAULT_BINS}
        success_count = 0

        # SQLite CURRENT_TIMESTAMP stores naive UTC timestamps
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        ten_min_ago = now_utc - datetime.timedelta(minutes=10)
        thirty_min_ago = now_utc - datetime.timedelta(minutes=30)

        recent_10_count = 0
        minute_buckets = Counter()

        for e in events:
            per_class[e.detected_class] = per_class.get(e.detected_class, 0) + 1
            if e.success:
                success_count += 1
            if e.timestamp is not None:
                if e.timestamp >= ten_min_ago:
                    recent_10_count += 1
                if e.timestamp >= thirty_min_ago:
                    minute_key = e.timestamp.strftime("%H:%M")
                    minute_buckets[minute_key] += 1

        accuracy = round(success_count / total_sorted, 4) if total_sorted > 0 else 0.0
        sorting_rate = round(recent_10_count / 10.0, 2)

        recent_trend = []
        for offset in range(29, -1, -1):
            t = now_utc - datetime.timedelta(minutes=offset)
            label = t.strftime("%H:%M")
            recent_trend.append({label: minute_buckets.get(label, 0)})

        return {
            "total_sorted": total_sorted,
            "per_class": per_class,
            "accuracy": accuracy,
            "sorting_rate": sorting_rate,
            "recent_trend": recent_trend,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_all():
    """Clear all sort events, reset bin statuses to zero, and log the system reset."""
    session = get_db_session()
    try:
        session.query(SortEvent).delete()
        bins = session.query(BinStatus).all()
        for b in bins:
            b.item_count = 0
            b.fill_percentage = 0.0

        log_entry = SystemLog(
            event_type="system",
            message="System reset",
            severity="info",
        )
        session.add(log_entry)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def add_system_log(event_type, message, severity="info"):
    """Insert a system log record."""
    session = get_db_session()
    try:
        log_entry = SystemLog(
            event_type=event_type,
            message=message,
            severity=severity,
        )
        session.add(log_entry)
        session.commit()
        session.refresh(log_entry)
        return log_entry.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    init_db()
