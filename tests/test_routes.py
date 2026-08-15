import json


def test_public_health_endpoint(project):
    client = project.app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_login_and_persistent_session(project, helpers):
    user = helpers["make_user"]("alice")
    client = project.app.test_client()
    response = client.post("/login", data={"username": "alice", "password": "pw"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"freshmanPumpAndDump" in response.data

    with client.session_transaction() as session:
        assert session.get("user_id") == user.id
        assert session.get("_permanent") is True


def test_bad_login_rejected(project, helpers):
    helpers["make_user"]("alice")
    client = project.app.test_client()
    response = client.post("/login", data={"username": "alice", "password": "wrong"})
    assert b"Invalid username or password" in response.data


def test_unauthenticated_routes_redirect(project):
    client = project.app.test_client()
    for path in ["/", "/portfolio", "/leaderboard", "/ipo", "/stock/ROB"]:
        response = client.get(path)
        assert response.status_code == 302
        assert "/login" in response.location


def test_ipo_order_json_endpoint(project, helpers, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from tests.conftest import set_ipo_clock

    user = helpers["make_user"]("alice")
    client = project.app.test_client()
    helpers["login"](client, user)
    set_ipo_clock(monkeypatch, project, datetime(2026, 8, 16, 15, 0, tzinfo=ZoneInfo("America/Denver")))

    response = client.post(
        "/ipo/order",
        data={"ticker": "ROB", "shares": "10"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["shares"] == 10


def test_trade_json_response_has_confirmation_data(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=15)
    helpers["open_market"](market_cash=100)
    client = project.app.test_client()
    helpers["login"](client, user)
    response = client.post(
        "/trade",
        data={"ticker": "ROB", "side": "BUY", "shares": "10"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["trade"]["ticker"] == "ROB"
    assert payload["trade"]["shares"] == 10
    assert payload["trade"]["total"] > 0
    assert payload["trade"]["market_price"] > 0.1


def test_trade_error_json_response(project, helpers):
    user = helpers["make_user"]("alice", cash=0)
    helpers["open_market"](market_cash=100)
    client = project.app.test_client()
    helpers["login"](client, user)
    response = client.post(
        "/trade",
        data={"ticker": "ROB", "side": "BUY", "shares": "10"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    assert response.status_code == 400
    assert response.json["ok"] is False
    assert response.json["error"]


def test_market_api_requires_login_and_returns_expected_shape(project, helpers):
    client = project.app.test_client()
    assert client.get("/api/market").status_code == 302

    user = helpers["make_user"]("alice")
    helpers["open_market"](market_cash=100)
    helpers["login"](client, user)
    response = client.get("/api/market")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["market_phase"] == "OPEN"
    assert len(payload["stocks"]) == 6
    assert {s["ticker"] for s in payload["stocks"]} == {"ROB", "WIK", "ZROD", "IVAS", "DWIL", "HAL"}
    assert "leaderboard" in payload
    assert "recent_trades" in payload
    assert "account" in payload


def test_stock_profile_and_leaderboard_routes(project, helpers):
    user = helpers["make_user"]("alice")
    client = project.app.test_client()
    helpers["login"](client, user)
    assert client.get("/stock/ROB").status_code == 200
    assert client.get("/portfolio").status_code == 200
    assert client.get("/leaderboard").status_code == 200
    assert client.get("/user/alice").status_code == 200


def test_unknown_stock_is_404(project, helpers):
    user = helpers["make_user"]("alice")
    client = project.app.test_client()
    helpers["login"](client, user)
    response = client.get("/stock/NOPE")
    assert response.status_code == 404


def test_ipo_page_keeps_other_users_private(project, helpers):
    alice = helpers["make_user"]("alice")
    bob = helpers["make_user"]("bob")
    client = project.app.test_client()
    helpers["login"](client, alice)
    response = client.get("/ipo")
    assert response.status_code == 200
    assert b"your requests are private" in response.data.lower()
    assert b"bob" not in response.data


def test_moderator_can_toggle_market_and_add_closed_date(project, helpers):
    from models import ClosedDate, MarketSetting

    mod = helpers["User"].query.filter_by(is_moderator=True).one()
    client = project.app.test_client()
    helpers["login"](client, mod)

    response = client.post("/moderator", data={"action": "toggle_market"}, follow_redirects=True)
    assert response.status_code == 200
    assert MarketSetting.query.first().market_enabled is False

    response = client.post(
        "/moderator",
        data={"action": "add_closed_date", "closed_date": "2026-08-20", "note": "party"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    item = ClosedDate.query.filter_by(day=__import__("datetime").date(2026, 8, 20)).one()
    assert item.note == "party"


def test_moderator_cannot_set_invalid_starting_cash(project, helpers):
    pending = helpers["make_user"]("alice", cash=0, approved=False)
    mod = helpers["User"].query.filter_by(is_moderator=True).one()
    client = project.app.test_client()
    helpers["login"](client, mod)

    response = client.post(
        "/moderator",
        data={"action": "approve", "user_id": pending.id, "starting_cash": "25"},
        follow_redirects=True,
    )
    assert b"Starting cash must be between $5 and $20" in response.data
    assert helpers["User"].query.get(pending.id).is_approved is False


def test_moderator_can_close_ipo_only_after_submissions(project, helpers):
    import market
    from models import IPOOrder, MarketState

    alice = helpers["make_user"]("alice", cash=15)
    bob = helpers["make_user"]("bob", cash=15)
    stock = helpers["get_stock"]("ROB")
    helpers["db"].session.add(IPOOrder(user_id=alice.id, stock_id=stock.id, shares=10))
    helpers["db"].session.add(IPOOrder(user_id=bob.id, stock_id=stock.id, shares=10))
    helpers["db"].session.commit()
    state = MarketState.query.first()
    state.phase = "IPO"
    helpers["db"].session.commit()

    mod = helpers["User"].query.filter_by(is_moderator=True).one()
    client = project.app.test_client()
    helpers["login"](client, mod)
    response = client.post("/moderator", data={"action": "close_ipo"}, follow_redirects=True)
    assert response.status_code == 200
    assert MarketState.query.first().phase == "OPEN"


def test_health_route_does_not_require_auth(project):
    client = project.app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
