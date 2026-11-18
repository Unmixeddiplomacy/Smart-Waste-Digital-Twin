import asyncio
import os
import sys
import tempfile
import unittest
import httpx
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# Add project root to sys.path so we can import backend modules cleanly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend import models, database
from backend.server import app


class TestDatabaseCRUD(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary SQLite database file
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = tmp.name
        tmp.close()

        # Save original module bindings
        self._orig_db_path = models.DB_PATH
        self._orig_engine = models.engine
        self._orig_models_session = models.SessionLocal
        self._orig_db_session = database.SessionLocal

        # Bind models and database to the temporary test database
        self.test_engine = create_engine(
            f"sqlite:///{self.temp_db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        self.TestSessionLocal = sessionmaker(bind=self.test_engine)

        models.DB_PATH = self.temp_db_path
        models.engine = self.test_engine
        models.SessionLocal = self.TestSessionLocal
        database.SessionLocal = self.TestSessionLocal

        models.init_db()

    def tearDown(self):
        # Dispose engine first to release Windows SQLite file locks
        self.test_engine.dispose()

        # Restore original module bindings
        models.DB_PATH = self._orig_db_path
        models.engine = self._orig_engine
        models.SessionLocal = self._orig_models_session
        database.SessionLocal = self._orig_db_session

        # Remove temporary database file
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def test_init_creates_tables(self):
        inspector = inspect(self.test_engine)
        tables = sorted(inspector.get_table_names())
        self.assertEqual(tables, ["bin_status", "sort_events", "system_logs"])

    def test_init_creates_default_bins(self):
        bins = database.get_bin_statuses()
        self.assertEqual(len(bins), 6)
        bin_names = {b["bin_name"] for b in bins}
        self.assertEqual(
            bin_names,
            {"cardboard", "glass", "metal", "paper", "plastic", "trash"},
        )

    def test_add_sort_event(self):
        event_id = database.add_sort_event("glass", 0.94, "glass", success=True)
        self.assertIsNotNone(event_id)

        events = database.get_recent_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], event_id)
        self.assertEqual(events[0]["detected_class"], "glass")
        self.assertAlmostEqual(events[0]["confidence"], 0.94, places=4)
        self.assertEqual(events[0]["assigned_bin"], "glass")
        self.assertTrue(events[0]["success"])
        self.assertIsInstance(events[0]["timestamp"], str)

    def test_add_sort_event_updates_bin(self):
        database.add_sort_event("plastic", 0.88, "plastic", success=True)
        bins = {b["bin_name"]: b for b in database.get_bin_statuses()}

        self.assertEqual(bins["plastic"]["item_count"], 1)
        self.assertAlmostEqual(bins["plastic"]["fill_percentage"], 2.0, places=2)
        self.assertEqual(bins["glass"]["item_count"], 0)

    def test_get_recent_events_ordering(self):
        database.add_sort_event("cardboard", 0.91, "cardboard")
        database.add_sort_event("glass", 0.92, "glass")
        database.add_sort_event("metal", 0.93, "metal")

        events = database.get_recent_events(limit=10)
        self.assertEqual(len(events), 3)
        self.assertEqual(
            [e["detected_class"] for e in events],
            ["metal", "glass", "cardboard"],
        )

    def test_get_statistics(self):
        classes = [
            ("paper", True),
            ("paper", True),
            ("plastic", True),
            ("plastic", False),
            ("glass", True),
            ("metal", True),
            ("metal", True),
            ("cardboard", True),
            ("cardboard", False),
            ("trash", True),
        ]
        for cls, ok in classes:
            database.add_sort_event(cls, 0.90, cls, success=ok)

        stats = database.get_statistics()
        self.assertEqual(stats["total_sorted"], 10)
        self.assertAlmostEqual(stats["accuracy"], 0.8, places=4)
        self.assertEqual(stats["per_class"]["paper"], 2)
        self.assertEqual(stats["per_class"]["plastic"], 2)
        self.assertEqual(stats["per_class"]["metal"], 2)
        self.assertEqual(stats["per_class"]["cardboard"], 2)
        self.assertEqual(stats["per_class"]["glass"], 1)
        self.assertEqual(stats["per_class"]["trash"], 1)
        self.assertEqual(len(stats["recent_trend"]), 30)

    def test_reset_all(self):
        database.add_sort_event("paper", 0.95, "paper")
        database.add_sort_event("metal", 0.85, "metal")
        self.assertEqual(database.get_statistics()["total_sorted"], 2)

        result = database.reset_all()
        self.assertTrue(result)
        self.assertEqual(database.get_statistics()["total_sorted"], 0)
        self.assertEqual(database.get_recent_events(10), [])

        for b in database.get_bin_statuses():
            self.assertEqual(b["item_count"], 0)
            self.assertEqual(b["fill_percentage"], 0.0)

        with database.get_db_session() as session:
            logs = session.query(models.SystemLog).all()
            self.assertTrue(any("System reset" in l.message for l in logs))

    def test_bin_fill_alert(self):
        # Default bin capacity is 50; 46 items = 92% >= 90% alert threshold
        for _ in range(46):
            database.add_sort_event("metal", 0.96, "metal", success=True)

        bins = {b["bin_name"]: b for b in database.get_bin_statuses()}
        self.assertEqual(bins["metal"]["item_count"], 46)
        self.assertAlmostEqual(bins["metal"]["fill_percentage"], 92.0, places=2)

        with database.get_db_session() as session:
            alerts = (
                session.query(models.SystemLog)
                .filter(models.SystemLog.event_type == "alert")
                .all()
            )
            self.assertGreaterEqual(len(alerts), 1)
            self.assertTrue(
                any("metal" in a.message and "almost full" in a.message for a in alerts)
            )


class TestFastAPIBackend(unittest.TestCase):
    """Integration tests for FastAPI REST endpoints using httpx.AsyncClient."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = tmp.name
        tmp.close()

        self._orig_db_path = models.DB_PATH
        self._orig_engine = models.engine
        self._orig_models_session = models.SessionLocal
        self._orig_db_session = database.SessionLocal

        self.test_engine = create_engine(
            f"sqlite:///{self.temp_db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        self.TestSessionLocal = sessionmaker(bind=self.test_engine)

        models.DB_PATH = self.temp_db_path
        models.engine = self.test_engine
        models.SessionLocal = self.TestSessionLocal
        database.SessionLocal = self.TestSessionLocal

        models.init_db()

    def tearDown(self):
        self.test_engine.dispose()

        models.DB_PATH = self._orig_db_path
        models.engine = self._orig_engine
        models.SessionLocal = self._orig_models_session
        database.SessionLocal = self._orig_db_session

        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def _run(self, coro):
        return asyncio.run(coro)

    def test_health_endpoint(self):
        async def _call():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/health")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("status", data)
                self.assertEqual(data["status"], "ok")

        self._run(_call())

    def test_bins_endpoint(self):
        async def _call():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/bins")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIsInstance(data, list)
                self.assertEqual(len(data), 6)

        self._run(_call())

    def test_stats_endpoint(self):
        async def _call():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/stats")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("total_sorted", data)

        self._run(_call())

    def test_events_endpoint(self):
        async def _call():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/events")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIsInstance(data, list)

        self._run(_call())

    def test_simulate_start_stop(self):
        async def _call():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                start_resp = await client.post("/api/simulate/start")
                self.assertEqual(start_resp.status_code, 200)
                self.assertEqual(start_resp.json()["status"], "started")

                await asyncio.sleep(0.1)

                stop_resp = await client.post("/api/simulate/stop")
                self.assertEqual(stop_resp.status_code, 200)
                self.assertEqual(stop_resp.json()["status"], "stopped")

        self._run(_call())

    def test_reset(self):
        async def _call():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/reset")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["status"], "reset")

        self._run(_call())


if __name__ == "__main__":
    unittest.main()
