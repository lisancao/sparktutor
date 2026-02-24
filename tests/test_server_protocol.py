"""Tests for the JSON-lines protocol message types."""

from __future__ import annotations

import json

from sparktutor.server.protocol import Notification, Request, Response


class TestRequest:
    def test_from_dict_full(self):
        data = {"id": 1, "method": "listCourses", "params": {"courseId": "abc"}}
        req = Request.from_dict(data)
        assert req.id == 1
        assert req.method == "listCourses"
        assert req.params == {"courseId": "abc"}

    def test_from_dict_no_params(self):
        data = {"id": 2, "method": "detectMode"}
        req = Request.from_dict(data)
        assert req.id == 2
        assert req.method == "detectMode"
        assert req.params == {}


class TestResponse:
    def test_success_json_line(self):
        resp = Response(id=1, result={"mode": "dry_run"})
        line = resp.to_json_line()
        assert line.endswith("\n")
        parsed = json.loads(line)
        assert parsed == {"id": 1, "result": {"mode": "dry_run"}}

    def test_error_json_line(self):
        resp = Response(id=2, error="Unknown method: foo")
        line = resp.to_json_line()
        parsed = json.loads(line)
        assert parsed == {"id": 2, "error": "Unknown method: foo"}
        assert "result" not in parsed

    def test_null_result(self):
        resp = Response(id=3, result=None)
        parsed = json.loads(resp.to_json_line())
        assert parsed["result"] is None


class TestNotification:
    def test_json_line(self):
        notif = Notification("output", {"line": "hello world"})
        line = notif.to_json_line()
        assert line.endswith("\n")
        parsed = json.loads(line)
        assert parsed == {"method": "output", "params": {"line": "hello world"}}

    def test_empty_params(self):
        notif = Notification("ping")
        parsed = json.loads(notif.to_json_line())
        assert parsed == {"method": "ping", "params": {}}
