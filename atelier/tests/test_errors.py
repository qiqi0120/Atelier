"""SPEC-01 §2 · 错误码测试。

重点是**契约**而不是实现：每个 code 都能 ``to_dict()``，http 码与 spec 表一致，
统一响应体外壳是 ``{"error": {...}}``。有其他 agent 依赖这些字符串。
"""

from __future__ import annotations

import pytest
from fastapi.responses import JSONResponse

from atelier.server.errors import (
    ERRORS,
    AtelierError,
    CrossSiteWriteBlocked,
    GateBlocked,
    HarnessTimeout,
    SnapshotStale,
    error_response,
    http_exception_response,
    to_body,
)
from atelier.server.gates.base import GateItem, Severity

#: SPEC-01 §2 表格里的 code → http。冻结契约，改这里等于改 spec。
SPEC_HTTP: dict[str, int] = {
    "PathEscapeError": 400,
    "ValidationError": 422,
    "NotFound": 404,
    "ProfileNotFound": 404,
    "SessionBusy": 409,
    "HarnessError": 502,
    "HarnessAuthError": 502,
    "HarnessTimeout": 504,
    "GateBlocked": 422,
    "SkillMissingKey": 409,
    "SkillNotFound": 404,
    "SkillRunFailed": 500,
    "PlatformAuthExpired": 409,
    "PlatformSmsWall": 202,
    "PublishFailed": 502,
    "SystemFileProtected": 403,
    "SnapshotStale": 200,
}


class TestCodes:
    @pytest.mark.parametrize("code", sorted(SPEC_HTTP))
    def test_code_is_registered(self, code: str) -> None:
        assert code in ERRORS, f"{code} 没进 ERRORS 表"

    @pytest.mark.parametrize(("code", "http"), sorted(SPEC_HTTP.items()))
    def test_http_matches_spec_table(self, code: str, http: int) -> None:
        assert ERRORS[code].http == http, f"{code} 的 http 与 SPEC-01 §2 不符"

    @pytest.mark.parametrize("code", sorted(ERRORS))
    def test_to_dict_shape(self, code: str) -> None:
        exc = ERRORS[code]()
        d = exc.to_dict()
        assert set(d) >= {"code", "message", "detail", "hint"}
        assert d["code"] == code
        assert isinstance(d["message"], str) and d["message"], f"{code} 没有人话 message"
        assert isinstance(d["detail"], dict)
        assert d["hint"] is None or isinstance(d["hint"], str)

    @pytest.mark.parametrize("code", sorted(ERRORS))
    def test_response_body_is_wrapped(self, code: str) -> None:
        exc = ERRORS[code]()
        body = to_body(exc)
        assert set(body) == {"error"}
        assert body["error"]["code"] == code

    @pytest.mark.parametrize("code", sorted(SPEC_HTTP))
    def test_每条错误都有人话(self, code: str) -> None:
        """PRD 原则四：不能只显示「失败」。"""
        exc = ERRORS[code]()
        assert exc.message != "出错了", f"{code} 用了基类默认文案"
        assert len(exc.message) >= 4


class TestOverridable:
    def test_message_detail_hint_overridable(self) -> None:
        exc = AtelierError("自定义", detail={"k": 1}, hint="这样做")
        assert exc.to_dict() == {
            "code": "AtelierError",
            "message": "自定义",
            "detail": {"k": 1},
            "hint": "这样做",
        }

    def test_hint_can_be_cleared(self) -> None:
        assert AtelierError("x", hint=None).hint is None


class TestGateBlocked:
    def test_requires_gate_items(self) -> None:
        with pytest.raises(ValueError):
            GateBlocked("没过", detail={"items": []})  # 没有 gate_items

    def test_from_report_carries_items(self) -> None:
        report_items = [
            GateItem("wordcount", "抖音标题字数", Severity.BLOCK, False, 61, 55, "超了", "删 6 个字"),
            GateItem("compliance", "合规词表", Severity.BLOCK, True, 0, 0, "干净", None),
        ]
        report = type("R", (), {"items": report_items})()
        err = GateBlocked.from_report(report)
        d = err.to_dict()
        assert d["code"] == "GateBlocked"
        assert err.http == 422
        assert len(d["detail"]["gate_items"]) == 2
        assert d["detail"]["failed"] == ["wordcount"]
        assert "61" in d["message"] and "55" in d["message"]
        assert d["hint"] == "删 6 个字"


class TestSnapshotStale:
    def test_not_an_error_response(self) -> None:
        exc = SnapshotStale("刷新失败")
        assert exc.http == 200
        assert exc.to_dict()["stale"] is True
        assert "stale" in exc.to_dict()


class TestHarnessTimeout:
    def test_is_504(self) -> None:
        assert HarnessTimeout().http == 504
        assert "120" in (HarnessTimeout().hint or "") or HarnessTimeout().hint


class TestResponses:
    def test_error_response(self) -> None:
        resp = error_response(HarnessTimeout())
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 504

    def test_http_exception_response(self) -> None:
        resp = http_exception_response(404, "没有这个东西")
        assert resp.status_code == 404
        assert b"HTTP404" in resp.body

    def test_http_exception_passes_through_atelier_body(self) -> None:
        resp = http_exception_response(409, {"code": "SessionBusy", "message": "忙", "detail": {}, "hint": None})
        assert resp.status_code == 409
        assert b"SessionBusy" in resp.body


class TestCsrfCode:
    def test_cross_site_write_blocked(self) -> None:
        exc = CrossSiteWriteBlocked()
        assert exc.http == 403
        assert exc.to_dict()["code"] == "CrossSiteWriteBlocked"
