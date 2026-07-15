from __future__ import annotations

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def test_ws_live_feed_receives_task_events(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/live") as websocket:
            response = client.post(
                "/tasks",
                json={
                    "title": "ws test",
                    "prompt": "p",
                    "tool_calls": [{"tool_name": "write_file", "args": {"path": "b.txt", "content": "x"}}],
                },
            )
            assert response.status_code == 200

            seen_types = set()
            for _ in range(20):
                event = websocket.receive_json()
                seen_types.add(event.get("event_type"))
                if {"task_completed", "task_failed"} & seen_types:
                    break

            assert "task_started" in seen_types


def test_ws_subscriber_gets_backlog_from_before_connecting(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        client.post("/tasks", json={"title": "before", "prompt": "p", "tool_calls": []})

        with client.websocket_connect("/ws/live") as websocket:
            event = websocket.receive_json()
            assert event["event_type"] in {"task_started", "evaluation", "task_completed", "task_failed"}
