from app.main import app


def test_app_import():
    assert app.title == "AI Leads Tracker"


def test_dashboard_route_exists():
    assert "/dashboard" in [route.path for route in app.routes]
