"""SPEC-01 §6 · 共享模型测试。

``core/models.py`` 的模型名与字段在 §11 冻结，所以这里逐个模型验证：
能实例化、必填字段会拦、枚举字面量生效、``completeness()`` 六维齐、JSON 可导出。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from atelier.server.core import models
from atelier.server.gates.base import Severity

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _profile(**kw: object) -> models.Profile:
    base: dict[str, object] = {
        "id": "p1", "name": "阿宇", "platforms": ["xhs", "dy"],
        "created_at": NOW, "updated_at": NOW,
    }
    base.update(kw)
    return models.Profile(**base)  # type: ignore[arg-type]


class TestProfile:
    def test_instantiate(self) -> None:
        p = _profile()
        assert p.id == "p1"
        assert p.platforms == ["xhs", "dy"]
        assert p.general_mode is False
        assert p.memories == []

    def test_name_and_platforms_required(self) -> None:
        with pytest.raises(PydanticValidationError):
            models.Profile(id="p1", created_at=NOW, updated_at=NOW)  # type: ignore[call-arg]

    def test_empty_dimensions_default_to_blank(self) -> None:
        p = _profile()
        for dim in ("identity", "style", "audience", "platform_rules", "preferences"):
            assert getattr(p, dim) == ""

    def test_completeness_has_six_dimensions(self) -> None:
        c = _profile().completeness()
        assert set(c) == set(models.PROFILE_DIMENSIONS)
        assert len(c) == 6
        assert all(0 <= v <= 100 for v in c.values())

    def test_completeness_empty_is_zero(self) -> None:
        assert all(v == 0 for v in _profile().completeness().values())

    def test_completeness_saturates(self) -> None:
        p = _profile(identity="定" * 200, style="风" * 200)
        c = p.completeness()
        assert c["identity"] == 100
        assert c["style"] == 100

    def test_completeness_counts_adopted_memories_only(self) -> None:
        mem = lambda i, adopted: models.Memory(
            id=f"m{i}", text=f"记忆{i}", source="归因", created_at=NOW, adopted=adopted
        )
        p = _profile(memories=[mem(1, True), mem(2, True), mem(3, False), mem(4, False)])
        assert p.completeness()["memories"] == 50  # 只算 2 条被采纳的

    @pytest.mark.parametrize("name", ["定位", "identity"])
    def test_dimension_accepts_both_chinese_and_key(self, name: str) -> None:
        p = _profile(identity="一个写字的人", style="克制")
        assert p.dimension(name) == "一个写字的人"

    def test_dimension_all_lists_labels(self) -> None:
        out = _profile(identity="x", style="y").dimension("all")
        assert "定位" in out and "风格" in out

    def test_dimension_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            _profile().dimension("胡说八道")

    def test_general_mode(self) -> None:
        assert _profile(general_mode=True).general_mode is True


class TestMemory:
    def test_instantiate_and_default_adopted(self) -> None:
        m = models.Memory(id="m1", text="他偏好具体数字", source="归因", created_at=NOW)
        assert m.adopted is True

    def test_text_and_source_required(self) -> None:
        with pytest.raises(PydanticValidationError):
            models.Memory(id="m1", created_at=NOW)  # type: ignore[call-arg]


class TestAttachment:
    def test_instantiate(self) -> None:
        a = models.Attachment(id="a1", kind="image", path="demo/成品/x.png", name="x.png", size=12, mime="image/png")
        assert a.kind == "image"

    @pytest.mark.parametrize("bad", ["video2", "", "IMAGE", "docx"])
    def test_kind_is_restricted(self, bad: str) -> None:
        with pytest.raises(PydanticValidationError):
            models.Attachment(id="a1", kind=bad, path="x", name="x", size=1, mime="x")  # type: ignore[arg-type]


class TestSession:
    def test_instantiate_with_defaults(self) -> None:
        s = models.Session(id="s1", title="新会话", profile_id=None, created_at=NOW, updated_at=NOW)
        assert s.archived is False
        assert s.last_turn_id is None

    def test_title_required(self) -> None:
        with pytest.raises(PydanticValidationError):
            models.Session(id="s1", profile_id=None, created_at=NOW, updated_at=NOW)  # type: ignore[call-arg]


class TestMessage:
    def test_instantiate(self) -> None:
        m = models.Message(
            id="msg1", session_id="s1", role="user", text="写一篇", turn_id="t1", created_at=NOW
        )
        assert m.attachments == []
        assert m.gate_report is None

    def test_turn_id_nullable_but_required(self) -> None:
        """spec 里 ``turn_id: str | None`` 没有默认值 → 键必须给（可为 null）。"""
        with pytest.raises(PydanticValidationError):
            models.Message(id="m", session_id="s", role="user", text="t", created_at=NOW)  # type: ignore[call-arg]
        ok = models.Message(id="m", session_id="s", role="user", text="t", turn_id=None, created_at=NOW)
        assert ok.turn_id is None

    @pytest.mark.parametrize("bad", ["tool", "USER", "", "assistant2"])
    def test_role_is_restricted(self, bad: str) -> None:
        with pytest.raises(PydanticValidationError):
            models.Message(id="m", session_id="s", role=bad, text="t", turn_id=None, created_at=NOW)  # type: ignore[arg-type]

    def test_nested_attachment(self) -> None:
        a = models.Attachment(id="a1", kind="doc", path="p", name="n", size=1, mime="text/md")
        m = models.Message(
            id="m", session_id="s", role="user", text="t", turn_id=None, attachments=[a], created_at=NOW
        )
        assert m.attachments[0].name == "n"

    def test_mutable_default_not_shared(self) -> None:
        """可变默认必须是 per-instance（pydantic 默认行为，防共享列表）。"""
        a = models.Message(id="a", session_id="s", role="user", text="t", turn_id=None, created_at=NOW)
        b = models.Message(id="b", session_id="s", role="user", text="t", turn_id=None, created_at=NOW)
        a.attachments.append(
            models.Attachment(id="x", kind="doc", path="p", name="n", size=1, mime="m")
        )
        assert b.attachments == []


class TestSkill:
    def test_skill_param(self) -> None:
        assert models.SkillParam(key="limit", label="字数上限").default == ""

    def test_skill_meta(self) -> None:
        m = models.SkillMeta(
            id="xhs-card", name="小红书知识卡", layer="制作", maturity="v1",
            trigger="做张图", cost="本地 · 免费", required_keys=[], params=[],
            body_markdown="# 卡片", script=None,
        )
        assert m.layer == "制作"
        assert m.script is None

    @pytest.mark.parametrize("bad_layer", ["创作", "", "营销"])
    def test_layer_is_restricted(self, bad_layer: str) -> None:
        with pytest.raises(PydanticValidationError):
            models.SkillMeta(
                id="x", name="x", layer=bad_layer, maturity="v1", trigger="t", cost="c",
                required_keys=[], params=[], body_markdown="", script=None,
            )  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_maturity", ["v4", "done", "", "V1"])
    def test_maturity_is_restricted(self, bad_maturity: str) -> None:
        with pytest.raises(PydanticValidationError):
            models.SkillMeta(
                id="x", name="x", layer="通用", maturity=bad_maturity, trigger="t", cost="c",
                required_keys=[], params=[], body_markdown="", script=None,
            )  # type: ignore[arg-type]

    def test_required_keys_list(self) -> None:
        m = models.SkillMeta(
            id="x", name="x", layer="制作", maturity="v2", trigger="t", cost="按量计费 · 需密钥",
            required_keys=["MINIMAX_API_KEY"], params=[], body_markdown="", script="run.py",
        )
        assert m.required_keys == ["MINIMAX_API_KEY"]


class TestCapability:
    def test_skill_id_is_nullable_but_required(self) -> None:
        """spec 里 ``skill_id: str | None`` 无默认值 → 键必须给（可为 null）。"""
        with pytest.raises(PydanticValidationError):
            models.Capability(id="c1", group="g", name="写文案", trigger="写一篇", maturity="v0")
        c = models.Capability(id="c1", group="做内容 · 要成品", name="写文案", trigger="写一篇",
                              maturity="v0", skill_id=None)
        assert c.skill_id is None

    @pytest.mark.parametrize("bad", ["mature", "v5", ""])
    def test_maturity_is_restricted(self, bad: str) -> None:
        with pytest.raises(PydanticValidationError):
            models.Capability(id="c", group="g", name="n", trigger="t", maturity=bad)  # type: ignore[arg-type]


class TestPublish:
    def test_platform_variant(self) -> None:
        v = models.PlatformVariant(
            platform="xhs", title="标题", body="正文", char_count=10, char_limit=1000,
            over_limit=False, adapted=True, status="ready",
        )
        assert v.error is None
        assert v.published_url is None

    @pytest.mark.parametrize("bad", ["douyin", "XHS", "", "b站"])
    def test_platform_is_restricted(self, bad: str) -> None:
        with pytest.raises(PydanticValidationError):
            models.PlatformVariant(
                platform=bad, title="t", body="b", char_count=0, char_limit=1,
                over_limit=False, adapted=False, status="pending",
            )  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", ["done", "", "READY"])
    def test_status_is_restricted(self, bad: str) -> None:
        with pytest.raises(PydanticValidationError):
            models.PlatformVariant(
                platform="dy", title="t", body="b", char_count=0, char_limit=1,
                over_limit=False, adapted=False, status=bad,
            )  # type: ignore[arg-type]

    def test_recount_computes_over_limit(self) -> None:
        v = models.PlatformVariant(
            platform="dy", title="t", body="标" * 61, char_count=0, char_limit=55,
            over_limit=False, adapted=True, status="pending",
        ).recount()
        assert v.char_count == 61
        assert v.over_limit is True

    def test_recount_ignores_whitespace(self) -> None:
        v = models.PlatformVariant(
            platform="gzh", title="t", body="正文  \n\n  一点", char_count=0, char_limit=100,
            over_limit=False, adapted=True, status="ready",
        ).recount()
        assert v.char_count == 4  # 「正文一点」= 4 个非空白字符

    def test_publish_draft(self) -> None:
        d = models.PublishDraft(
            id="d1", project="lunch", title="探店", body="正文", topic_tags=["咖啡"],
            variants=[], attachments=[], created_at=NOW, updated_at=NOW,
        )
        assert d.project == "lunch"

    def test_publish_draft_project_nullable(self) -> None:
        d = models.PublishDraft(
            id="d1", project=None, title="t", body="b", topic_tags=[],
            variants=[], attachments=[], created_at=NOW, updated_at=NOW,
        )
        assert d.project is None


class TestPrecheckItem:
    def test_instantiate(self) -> None:
        p = models.PrecheckItem(
            id="p1", label="抖音标题字数", severity=Severity.BLOCK,
            passed=False, message="超了", fix_hint="删 6 个字", platform="dy",
        )
        assert p.severity == Severity.BLOCK
        assert p.severity.value == "block"

    def test_optional_fields(self) -> None:
        p = models.PrecheckItem(id="p1", label="l", severity=Severity.WARN, passed=True, message="ok")
        assert p.fix_hint is None
        assert p.platform is None

    def test_severity_accepts_string(self) -> None:
        p = models.PrecheckItem(id="p", label="l", severity="warn", passed=True, message="m")
        assert p.severity == Severity.WARN


class TestSerialization:
    @pytest.mark.parametrize(
        "factory",
        [
            _profile,
            lambda: models.Memory(id="m", text="t", source="手动", created_at=NOW),
            lambda: models.Attachment(id="a", kind="doc", path="p", name="n", size=1, mime="m"),
            lambda: models.Session(id="s", title="t", profile_id=None, created_at=NOW, updated_at=NOW),
            lambda: models.Message(id="m", session_id="s", role="user", text="t", turn_id=None, created_at=NOW),
            lambda: models.SkillMeta(
                id="x", name="x", layer="通用", maturity="v0", trigger="t", cost="c",
                required_keys=[], params=[], body_markdown="", script=None,
            ),
            lambda: models.Capability(id="c", group="g", name="n", trigger="t", maturity="v0", skill_id=None),
            lambda: models.PublishDraft(
                id="d", project=None, title="t", body="b", topic_tags=[], variants=[],
                attachments=[], created_at=NOW, updated_at=NOW,
            ),
            lambda: models.PrecheckItem(id="p", label="l", severity=Severity.WARN, passed=True, message="m"),
        ],
    )
    def test_every_model_is_json_serialisable(self, factory) -> None:
        """落库/落盘都要 JSON 化，datetime 必须能转字符串。"""
        payload = models.to_dict(factory())
        assert json.loads(json.dumps(payload, ensure_ascii=False))

    def test_to_dict_datetime_becomes_iso(self) -> None:
        d = models.to_dict(_profile())
        assert d["created_at"].startswith("2026-10-02T12:00")
