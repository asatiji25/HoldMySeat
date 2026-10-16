"""
Lightweight contract checks. Full integration tests require a running PostgreSQL database.
Run: pytest -q
"""
from pathlib import Path

def test_required_endpoints_are_documented_in_source():
    source = Path("app/main.py").read_text(encoding="utf-8")
    for route in [
        '"/seats"', '"/queue/join"', '"/reservations"',
        '"/metrics/contention"', '"/bookings/history/{user_id}"'
    ]:
        assert route in source

def test_docker_and_readme_exist():
    assert Path("Dockerfile").exists()
    assert Path("docker-compose.yml").exists()
    assert Path("README.md").exists()
