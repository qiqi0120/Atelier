"""SPEC-01 §5 · 门禁测试。

4 个内置门禁各自的通过/失败路径 + 分级语义（BLOCK 阻断 / WARN 只告警）+
``secret_scan`` 的 **fail-closed**（扫描器自己坏掉时必须按命中处理）。
"""

from __future__ import annotations

import pytest

from atelier.server.gates import secret_scan as secret_scan_mod
from atelier.server.gates.base import Gate, GateInput, GateItem, GateReport, Severity
from atelier.server.gates.registry import clear, get_gate, list_gates, register, registry_errors, run_gates
from atelier.server.gates.wordcount import PLATFORM_LIMITS, count_chars

CLEAN = "今天去了三家咖啡馆，第二家最值得推荐，人均 38，坐着很安静。"


def _run(text: str = CLEAN, **kw: object) -> GateReport:
    return run_gates(GateInput.of(text, **kw))  # type: ignore[arg-type]


def _item(report: GateReport, gate: str) -> GateItem:
    return next(i for i in report.items if i.gate == gate)


class TestRegistry:
    def test_builtin_gates_registered(self) -> None:
        # M3 起 +visual_qc（SPEC-13 §0 D3），共 5 个内置门禁
        assert {g["id"] for g in list_gates()} == {
            "ai_flavor", "compliance", "secret_scan", "wordcount", "visual_qc"
        }

    def test_no_load_errors(self) -> None:
        assert registry_errors() == {}

    def test_list_gates_exposes_severity_and_doc(self) -> None:
        meta = {g["id"]: g for g in list_gates()}
        assert meta["wordcount"]["severity"] == "block"
        assert meta["ai_flavor"]["severity"] == "warn"
        assert all(g["doc"] for g in meta.values())

    def test_get_gate(self) -> None:
        assert get_gate("wordcount") is not None
        assert get_gate("没有这个") is None

    def test_run_all_gates_by_default(self) -> None:
        assert len(run_gates(GateInput.of(CLEAN)).items) == 5  # 含 M3 的 visual_qc

    def test_run_selected_gate(self) -> None:
        report = run_gates(GateInput.of(CLEAN), gate_ids=["secret_scan"])
        assert [i.gate for i in report.items] == ["secret_scan"]

    def test_unknown_gate_id_fails_closed(self) -> None:
        report = run_gates(GateInput.of(CLEAN), gate_ids=["不存在"])
        assert report.blocked is True
        assert "可用门禁" in (report.items[0].fix_hint or "")

    def test_gate_exceptions_become_blocked_items(self) -> None:
        """门禁自己抛异常 → 记成 BLOCK 失败项，不能当成「通过」。"""

        class Boom:
            id = "boom"
            label = "会炸的门禁"
            severity = Severity.BLOCK

            def run(self, content: GateInput) -> GateItem:
                raise RuntimeError("门禁内部炸了")

        register(Boom())
        try:
            report = run_gates(GateInput.of(CLEAN), gate_ids=["boom"])
            assert report.blocked is True
            assert "RuntimeError" in str(report.items[0].actual)
            assert report.items[0].severity == Severity.BLOCK
        finally:
            from atelier.server.gates.registry import _registry

            _registry.pop("boom", None)

    def test_register_rejects_object_without_id(self) -> None:
        with pytest.raises(ValueError):
            register(object())  # type: ignore[arg-type]

    def test_register_rejects_object_without_run(self) -> None:
        class NoRun:
            id = "norun"

        with pytest.raises(TypeError):
            register(NoRun())  # type: ignore[arg-type]

    def test_builtins_satisfy_gate_protocol(self) -> None:
        for gate in ("wordcount", "compliance", "secret_scan", "ai_flavor"):
            assert isinstance(get_gate(gate), Gate)

    def test_clear_then_reload_restores_builtins(self) -> None:
        from atelier.server.gates import registry as reg

        clear()
        assert reg._registry == {}, "clear() 应清空注册表"
        # list_gates()/run_gates() 会顺手把内置门禁装回来
        assert {g["id"] for g in list_gates()} == {
            "ai_flavor", "compliance", "secret_scan", "wordcount", "visual_qc"
        }


class TestWordcount:
    def test_limits_match_spec(self) -> None:
        assert PLATFORM_LIMITS == {"xhs": 1000, "dy": 55, "gzh": 20000}

    def test_count_chars_ignores_whitespace(self) -> None:
        assert count_chars("你好 世界\n\n") == 4

    def test_xhs_within_limit(self) -> None:
        assert _item(_run(platform="xhs"), "wordcount").passed is True

    def test_xhs_over_limit_blocked(self) -> None:
        report = _run("字" * 1200, platform="xhs")
        item = _item(report, "wordcount")
        assert report.blocked is True
        assert item.actual == 1200
        assert item.limit == 1000
        assert "200" in item.message
        assert item.fix_hint and "裁剪" in item.fix_hint

    def test_dy_title_61_over_55(self) -> None:
        """SPEC-01 §2 的例子：抖音标题 61/55 字。"""
        report = _run("正文", platform="dy", title="标" * 61)
        item = _item(report, "wordcount")
        assert report.blocked is True
        assert (item.actual, item.limit) == (61, 55)
        assert item.label == "抖音标题字数"

    def test_dy_title_55_exactly_passes(self) -> None:
        report = _run("正文", platform="dy", title="标" * 55)
        assert _item(report, "wordcount").passed is True

    def test_gzh_long_form_allowed(self) -> None:
        assert _item(_run("字" * 5000, platform="gzh"), "wordcount").passed is True

    def test_gzh_over_limit(self) -> None:
        assert _run("字" * 20001, platform="gzh").blocked is True

    def test_no_platform_uses_strict_fallback(self) -> None:
        report = _run("字" * 1001)
        item = _item(report, "wordcount")
        assert report.blocked is True
        assert "未指定平台" in item.label

    def test_unknown_platform_passes_with_note(self) -> None:
        item = _item(_run(platform="b站"), "wordcount")
        assert item.passed is True
        assert "没有 b站" in item.message


class TestCompliance:
    def test_clean_text_passes(self) -> None:
        assert _item(_run(), "compliance").passed is True

    @pytest.mark.parametrize(
        "text",
        ["我们是全网第一", "这个牌子行业第一", "全网最好用的", "销量第一的酸奶", "行业最强", "质量最优"],
    )
    def test_extreme_words_blocked(self, text: str) -> None:
        report = _run(text, platform="xhs")
        assert report.blocked is True
        assert "极限用语" in _item(report, "compliance").label

    @pytest.mark.parametrize("text", ["能根治你的鼻炎", "纯天然无害", "三天祛斑", "增强免疫力"])
    def test_medical_claims_blocked(self, text: str) -> None:
        report = _run(text, platform="xhs")
        assert report.blocked is True
        assert _item(report, "compliance").fix_hint

    @pytest.mark.parametrize("text", ["代开发票", "仿真枪便宜卖", "冰毒"])
    def test_forbidden_words_blocked(self, text: str) -> None:
        report = _run(text, platform="xhs")
        assert report.blocked is True
        assert "违禁品" in _item(report, "compliance").label

    @pytest.mark.parametrize(
        "text",
        ["这是最后一次去", "最近很忙", "我最好的朋友开了一家店", "最佳拍档", "我们是最强团队", "一个最佳实践指南"],
    )
    def test_ambiguous_superlatives_not_blocked(self, text: str) -> None:
        """裸最高级在口语里太常见（「我最好的朋友」），BLOCK 级门禁不该误杀；
        只有带评价主体的（品牌第一 / 全网最好）才拦。"""
        assert _run(text, platform="xhs").blocked is False, text

    def test_title_is_also_scanned(self) -> None:
        report = _run("正文没问题", platform="xhs", title="全网第一推荐")
        assert report.blocked is True
        assert "标题" in _item(report, "compliance").message

    def test_hit_lists_category_and_term(self) -> None:
        item = _item(_run("全网第一，能根治", platform="xhs"), "compliance")
        assert "极限用语" in str(item.actual)
        assert "医疗功效" in str(item.actual)
        assert "全网第一" in str(item.actual)


class TestSecretScan:
    @pytest.mark.parametrize(
        ("label", "payload"),
        [
            ("anthropic_key", "sk-ant-api03-" + "A" * 40),
            ("openai_style_key", "sk-" + "B" * 32),
            ("aws_access_key", "AKIAIOSFODNN7EXAMPLE"),
            ("github_token", "ghp_" + "c" * 36),
            ("github_token", "gho_" + "d" * 36),
            ("private_key_block", "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n"),
            ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"),
            ("slack_token", "xoxb-123456789012-abcdefghijkl"),
            ("stripe_live_key", "sk_live_" + "e" * 20),
            ("google_api_key", "AIza" + "f" * 35),
            ("assigned_secret", 'api_key = "abcdefghijklmnop1234"'),
        ],
    )
    def test_detects_each_pattern(self, label: str, payload: str) -> None:
        report = _run(payload, platform="xhs")
        assert report.blocked is True, f"{label} 没被检出"
        assert label in _item(report, "secret_scan").message

    def test_clean_text_passes(self) -> None:
        assert _item(_run(), "secret_scan").passed is True

    def test_masked_value_never_echoes_full_secret(self) -> None:
        secret = "sk-ant-api03-" + "Z" * 40
        item = _item(_run(secret, platform="xhs"), "secret_scan")
        assert secret not in item.message
        assert "Z" * 40 not in str(item.actual)
        assert "…" in item.message

    def test_title_is_also_scanned(self) -> None:
        report = _run("正文干净", platform="xhs", title="AKIAIOSFODNN7EXAMPLE")
        assert report.blocked is True
        assert "标题" in _item(report, "secret_scan").message

    def test_fail_closed_when_scanner_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """扫描器自身抛异常 → 必须按「命中」阻断（宁可误杀不可漏放）。"""
        def boom(text: str, title: str | None = None) -> list[dict[str, str]]:
            raise RuntimeError("正则引擎炸了")

        monkeypatch.setattr(secret_scan_mod, "scan_secrets", boom)
        gate = get_gate("secret_scan")
        item = gate.run(GateInput.of(CLEAN))  # type: ignore[union-attr]
        assert item.passed is False
        assert item.severity == Severity.BLOCK
        assert "fail-closed" in item.message
        assert "RuntimeError" in item.message

    def test_fail_closed_when_pattern_table_broken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """规则表被破坏（少了规则）→ 拒绝以「无命中」放行。"""
        monkeypatch.setattr(secret_scan_mod, "PATTERN_SPECS", (("only_one", r"x"),))
        gate = get_gate("secret_scan")
        item = gate.run(GateInput.of(CLEAN))  # type: ignore[union-attr]
        assert item.passed is False
        assert "fail-closed" in item.message

    def test_fail_closed_when_pattern_is_not_regex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(secret_scan_mod, "_PATTERNS", {"bad": "not-a-regex"})
        gate = get_gate("secret_scan")
        item = gate.run(GateInput.of(CLEAN))  # type: ignore[union-attr]
        assert item.passed is False

    def test_probe_helper(self) -> None:
        assert callable(secret_scan_mod.probe())
        assert secret_scan_mod.probe()("AKIAIOSFODNN7EXAMPLE")


class TestAiFlavor:
    def test_severity_is_warn(self) -> None:
        assert _item(_run(), "ai_flavor").severity == Severity.WARN

    def test_never_blocks_even_when_low(self) -> None:
        """软提醒只告警：AI 味再重也不阻断落盘（PRD 原则二的分级）。"""
        robotic = (
            "在当今社会，随着科技的不断发展，越来越多的人开始关注生活品质的提升。"
            "首先，我们需要认识到，保持良好的作息习惯可能是非常重要的。"
            "其次，适度运动也有助于身心健康的可能性。"
            "此外，在饮食方面也值得我们进一步去认真地考虑和深入地思考一下。"
            "与此同时，我们也可以从以下几个维度来进行系统性的分析与探讨。"
            "综上所述，我们应当全面地提升整体的生活质量，从而获得更加的身心健康。"
        )
        report = _run(robotic, platform="gzh")
        assert _item(report, "ai_flavor").passed is False
        assert report.blocked is False, "ai_flavor 是 WARN 级，绝不能阻断"

    def test_low_score_reports_five_dimensions(self) -> None:
        item = _item(_run("在当今社会，随着发展，首先其次此外总而言之。", platform="gzh"), "ai_flavor")
        assert item.limit == 60
        for dim in ("直接性", "节奏", "信任度", "活人感", "精炼度"):
            assert dim in item.message

    def test_concrete_text_scores_higher(self) -> None:
        item = _item(_run(CLEAN, platform="xhs"), "ai_flavor")
        assert item.passed is True
        assert isinstance(item.actual, int)

    def test_empty_text_passes(self) -> None:
        assert _item(_run("", platform="xhs"), "ai_flavor").passed is True

    def test_warn_failure_shows_up_in_warnings_not_blocked(self) -> None:
        report = _run("在当今，随着发展。首先其次。此外总之。", platform="gzh")
        assert report.blocked is False
        assert report.warnings == [] or all(i.severity == Severity.WARN for i in report.warnings)


class TestReport:
    def test_blocked_only_counts_block_level_failures(self) -> None:
        report = GateReport(items=[
            GateItem("a", "A", Severity.BLOCK, True, 1, 1, "ok", None),
            GateItem("b", "B", Severity.WARN, False, 1, 2, "有点 AI 味", "改改"),
        ])
        assert report.blocked is False
        assert len(report.warnings) == 1

    def test_to_dict_summary(self) -> None:
        report = _run("全网第一" + "字" * 1200, platform="xhs")
        d = report.to_dict()
        assert d["blocked"] is True
        assert d["summary"]["blocked_items"] >= 2
        assert len(d["items"]) == 5  # M3 起 +visual_qc
        assert all("severity" in i and "fix_hint" in i for i in d["items"])

    def test_fix_hints_deduped(self) -> None:
        report = _run("字" * 1200, platform="xhs")
        assert len(report.fix_hints()) == len(set(report.fix_hints()))

    def test_severity_values_are_frozen(self) -> None:
        assert Severity.BLOCK.value == "block"
        assert Severity.WARN.value == "warn"

    def test_clean_text_passes_everything(self) -> None:
        report = _run(CLEAN, platform="xhs", title="咖啡探店")
        assert report.blocked is False
        assert all(i.passed for i in report.items)
