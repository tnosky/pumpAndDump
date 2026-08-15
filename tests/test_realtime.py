def test_realtime_market_payload_contains_core_live_data(project, helpers):
    from realtime import market_payload
    user = helpers["make_user"]("alice")
    client = project.app.test_client()
    helpers["login"](client, user)
    with client.session_transaction() as saved:
        user_id = saved.get("user_id")
    with project.app.test_request_context("/api/market"):
        from flask import session
        session["user_id"] = user_id
        payload = market_payload()
    assert payload["market_phase"] == "IPO"
    assert len(payload["stocks"]) == 6
    assert "leaderboard" in payload
    assert "recent_trades" in payload
    assert payload["account"]["cash"] == 15.0


def test_socketio_broadcast_after_trade(project, helpers):
    from extensions import socketio
    import market

    user = helpers["make_user"]("alice", cash=15)
    helpers["open_market"](market_cash=100)
    client = project.app.test_client()
    helpers["login"](client, user)
    ws = socketio.test_client(project.app, flask_test_client=client)
    assert ws.is_connected()

    response = client.post(
        "/trade",
        data={"ticker": "ROB", "side": "BUY", "shares": "1"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    events = ws.get_received()
    assert any(event["name"] == "market_update" for event in events)
