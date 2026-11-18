"""
Automated End-to-End Test Script for Smart Waste Sorting Digital Twin.

Starts the FastAPI server in a background subprocess, verifies health,
REST endpoints, simulation lifecycle, and reset behavior, then shuts down
the server cleanly and prints a PASS/FAIL summary.

Run:
    python tests/test_e2e.py
"""

import os
import sys
import time
import socket
import subprocess
import httpx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)


def find_available_port(preferred_port: int = 8000) -> int:
    """Return preferred_port if free, otherwise find an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", preferred_port)) != 0:
            return preferred_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(base_url: str, proc: subprocess.Popen, timeout: float = 45.0) -> bool:
    """Poll /api/health until the server responds 200 OK or timeout expires."""
    deadline = time.time() + timeout
    with httpx.Client(timeout=2.0) as client:
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            try:
                resp = client.get(f"{base_url}/api/health")
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
    return False


def stop_server(proc: subprocess.Popen) -> None:
    """Cleanly terminate the background server process with kill fallback."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_e2e_tests() -> bool:
    """Run the full end-to-end test suite and return True if all checks pass."""
    port = find_available_port(8000)
    base_url = f"http://127.0.0.1:{port}"
    results: list[tuple[str, bool, str]] = []

    def record(name: str, passed: bool, detail: str = "") -> None:
        results.append((name, passed, detail))
        status = "PASS" if passed else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"  [{status}] {name}{suffix}")

    print("=" * 60)
    print("Smart Waste Sorting Digital Twin — End-to-End Test")
    print("=" * 60)
    print(f"Starting FastAPI server on {base_url} ...")

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        ready = wait_for_server(base_url, proc, timeout=45.0)
        record("Server startup & /api/health ready", ready, base_url if ready else "Timed out or exited")
        if not ready:
            if proc.poll() is not None:
                _, stderr_out = proc.communicate(timeout=3)
                print("Server stderr:\n", stderr_out[-1000:])
            return False

        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            # 1. GET /api/health
            r = client.get("/api/health")
            health_ok = r.status_code == 200 and r.json().get("status") == "ok"
            record("GET /api/health -> 200", health_ok, str(r.json()))

            # 2. GET /api/bins
            r = client.get("/api/bins")
            bins_data = r.json() if r.status_code == 200 else []
            bins_ok = r.status_code == 200 and isinstance(bins_data, list) and len(bins_data) == 6
            record("GET /api/bins -> 200 (6 bins)", bins_ok, f"count={len(bins_data)}")

            # 3. GET /api/stats
            r = client.get("/api/stats")
            stats_ok = r.status_code == 200 and "total_sorted" in r.json()
            record("GET /api/stats -> 200", stats_ok, f"total_sorted={r.json().get('total_sorted')}")

            # Ensure clean baseline before simulation
            r = client.post("/api/reset")
            assert r.status_code == 200

            # 4. POST /api/simulate/start
            r = client.post("/api/simulate/start")
            start_ok = r.status_code == 200 and r.json().get("status") == "started"
            record("POST /api/simulate/start -> 200", start_ok, str(r.json()))

            # 5. Wait 10 seconds for simulated events
            print("  ... waiting 10 seconds for simulated sorting events ...")
            time.sleep(10)

            # 6. GET /api/stats -> total_sorted > 0
            r = client.get("/api/stats")
            stats_after = r.json() if r.status_code == 200 else {}
            total_after = stats_after.get("total_sorted", 0)
            sim_events_ok = r.status_code == 200 and total_after > 0
            record("GET /api/stats -> total_sorted > 0", sim_events_ok, f"total_sorted={total_after}")

            # 7. POST /api/simulate/stop
            r = client.post("/api/simulate/stop")
            stop_ok = r.status_code == 200 and r.json().get("status") == "stopped"
            record("POST /api/simulate/stop -> 200", stop_ok, str(r.json()))

            # 8. POST /api/reset
            r = client.post("/api/reset")
            reset_ok = r.status_code == 200 and r.json().get("status") == "reset"
            record("POST /api/reset -> 200", reset_ok, str(r.json()))

            # 9. GET /api/stats -> total_sorted == 0
            r = client.get("/api/stats")
            total_reset = r.json().get("total_sorted") if r.status_code == 200 else -1
            reset_verify_ok = r.status_code == 200 and total_reset == 0
            record("GET /api/stats -> total_sorted == 0", reset_verify_ok, f"total_sorted={total_reset}")

    finally:
        print("Stopping server subprocess ...")
        stop_server(proc)
        print("Server stopped cleanly.")

    # Print PASS/FAIL summary
    passed_count = sum(1 for _, ok, _ in results if ok)
    total_count = len(results)
    all_passed = passed_count == total_count

    print("=" * 60)
    print(f"SUMMARY: {passed_count}/{total_count} checks passed — {'PASS' if all_passed else 'FAIL'}")
    print("=" * 60)
    return all_passed


def test_e2e_workflow():
    """Pytest entry point for end-to-end verification."""
    assert run_e2e_tests(), "One or more end-to-end checks failed"


if __name__ == "__main__":
    success = run_e2e_tests()
    sys.exit(0 if success else 1)
