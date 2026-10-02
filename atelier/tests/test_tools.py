"""SPEC-01 §4 · 5 个进程内 MCP 工具测试。

核心断言是**门禁绕不过去**：

- ``atelier_gate_run`` 命中 BLOCK → ``blocked: true``
- ``atelier_artifact_write`` 命中 BLOCK → **文件根本没被创建**

第二条才是真正生效的那道（模型可以无视第一条的返回，但绕不过第二条）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier.server import paths
from atelier.server.errors import NotFound, PathEscapeError, ProfileNotFound, ValidationError
from atelier.server.harness import tools

CLEAN = "今天去了三家咖啡馆，第二家最值得推荐，人均 38。"

#: 假的但是「像」的密钥，够 secret_scan 命中
FAKE_KEY = "sk-ant-api03-" + "A" * 40


class TestToolManifest:
    def test_exactly_five_tools(self) -> None:
        assert len(tools.TOOL_SPECS) == 5

    def test_tool_names_match_spec(self) -> None:
        assert {t.name for t in tools.TOOL_SPECS} == {
            "atelier_gate_run",
            "atelier_artifact_write",
            "atelier_library_list",
            "atelier_skill_run",
            "atelier_profile_get",
        }

    def test_allowed_tool_names_are_mcp_qualified(self) -> None:
        names = tools.allowed_tool_names()
        assert f"mcp__{tools.MCP_SERVER_NAME}__atelier_gate_run" in names
        assert len(names) == 5

    def test_every_tool_has_schema_and_doc(self) -> None:
        for t in tools.TOOL_SPECS:
            assert t.description.strip(), t.name
            assert t.input_schema.get("type") == "object", t.name

    def test_gate_run_schema_requires_text(self) -> None:
        assert tools.get_tool("atelier_gate_run").input_schema["required"] == ["text"]

    def test_artifact_write_schema_required_fields(self) -> None:
        assert tools.get_tool("atelier_artifact_write").input_schema["required"] == [
            "project", "filename", "content"
        ]

    def test_zone_enum_uses_chinese_zones(self) -> None:
        zone = tools.get_tool("atelier_artifact_write").input_schema["properties"]["zone"]
        assert zone["enum"] == ["成品", "素材"]

    def test_get_unknown_tool(self) -> None:
        with pytest.raises(NotFound):
            tools.get_tool("atelier_nope")

    def test_sdk_tools_wraps_five(self) -> None:
        """用真实 SDK 的 @tool 包一层（验证入参 schema 被 SDK 接受）。"""
        wrapped = tools.sdk_tools()
        assert len(wrapped) == 5
        assert {w.name for w in wrapped} == {t.name for t in tools.TOOL_SPECS}

    def test_build_mcp_server(self) -> None:
        cfg = tools.build_mcp_server()
        assert cfg["name"] == tools.MCP_SERVER_NAME


class TestGateRun:
    async def test_clean_content_passes(self, atelier_root: Path) -> None:
        r = await tools.atelier_gate_run(CLEAN, platform="xhs")
        assert r["blocked"] is False
        assert len(r["items"]) == 5  # M3 起 +visual_qc
        assert "可以调用" in r["instruction"]

    async def test_blocked_returns_flag_and_hints(self, atelier_root: Path) -> None:
        """验收项：命中 BLOCK 时返回 blocked。"""
        r = await tools.atelier_gate_run(FAKE_KEY, platform="xhs")
        assert r["blocked"] is True
        assert any(i["gate"] == "secret_scan" and not i["passed"] for i in r["items"])
        assert r["fix_hint"], "必须告诉模型怎么改"
        assert "atelier_artifact_write" in r["instruction"], "要告诉模型改完怎么落盘"

    async def test_blocked_by_wordcount(self, atelier_root: Path) -> None:
        r = await tools.atelier_gate_run("字" * 1200, platform="xhs")
        assert r["blocked"] is True
        assert "裁剪" in r["fix_hint"]

    async def test_blocked_by_title_limit(self, atelier_root: Path) -> None:
        r = await tools.atelier_gate_run("正文", platform="dy", title="标" * 61)
        assert r["blocked"] is True

    async def test_selected_gate_ids(self, atelier_root: Path) -> None:
        r = await tools.atelier_gate_run(CLEAN, gate_ids=["compliance"], platform="xhs")
        assert [i["gate"] for i in r["items"]] == ["compliance"]

    async def test_invalid_project_rejected(self, atelier_root: Path) -> None:
        with pytest.raises(ValidationError):
            await tools.atelier_gate_run(CLEAN, project="../evil")

    async def test_summary_shape(self, atelier_root: Path) -> None:
        r = await tools.atelier_gate_run(CLEAN, platform="xhs")
        assert r["summary"]["total"] == 5  # M3 起 +visual_qc
        assert r["summary"]["blocked_items"] == 0


class TestArtifactWrite:
    async def test_writes_product(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        r = await tools.atelier_artifact_write("lunch", "笔记.md", CLEAN, zone="成品", platform="xhs")
        assert r["ok"] is True
        assert r["written"] is True
        target = paths.product_dir("lunch") / "笔记.md"
        assert target.exists()
        assert target.read_text("utf-8") == CLEAN
        assert r["abs_path"] == str(target)
        assert r["rel_path"] == "outputs/lunch/成品/笔记.md"

    async def test_writes_material(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        r = await tools.atelier_artifact_write("lunch", "raw/0.png", "假数据", zone="素材")
        assert r["ok"] is True
        assert (paths.material_dir("lunch") / "raw" / "0.png").exists()

    async def test_nested_path_created(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        r = await tools.atelier_artifact_write("lunch", "a/b/c/深.md", CLEAN, zone="成品", platform="xhs")
        assert r["ok"] is True
        assert paths.rel_to_root(Path(r["abs_path"])).endswith("a/b/c/深.md")

    async def test_gate_blocks_secret_and_nothing_is_written(self, atelier_root: Path) -> None:
        """★ 机制核心：模型无视 gate_run 的返回直接写盘，也写不进去。"""
        paths.new_project("lunch")
        r = await tools.atelier_artifact_write("lunch", "泄密.md", FAKE_KEY, zone="成品", platform="xhs")
        assert r["blocked"] is True
        assert r["written"] is False
        assert r["ok"] is False
        assert not (paths.product_dir("lunch") / "泄密.md").exists(), "被拦的内容绝不能落盘"
        assert r["fix_hint"]

    async def test_gate_blocks_over_limit(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        r = await tools.atelier_artifact_write("lunch", "超长.md", "字" * 1200, zone="成品", platform="xhs")
        assert r["blocked"] is True
        assert not (paths.product_dir("lunch") / "超长.md").exists()

    async def test_gate_blocks_compliance(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        r = await tools.atelier_artifact_write("lunch", "违规.md", "我们是全网第一", zone="成品", platform="xhs")
        assert r["blocked"] is True
        assert not (paths.product_dir("lunch") / "违规.md").exists()

    async def test_gate_report_returned_on_success(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        r = await tools.atelier_artifact_write("lunch", "好.md", CLEAN, zone="成品", platform="xhs")
        assert r["gates"] is not None
        assert r["gates"]["blocked"] is False
        assert len(r["gates"]["items"]) == 3  # WRITE_GATE_IDS 三个

    async def test_binary_extension_skips_wordcount(self, atelier_root: Path) -> None:
        """图片不该被字数门禁拦（只看密钥扫描）。"""
        paths.new_project("lunch")
        r = await tools.atelier_artifact_write("lunch", "图.png", "字" * 5000, zone="素材")
        assert r["ok"] is True
        assert r["gates"] is None

    async def test_path_escape_rejected(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        with pytest.raises(PathEscapeError):
            await tools.atelier_artifact_write("lunch", "../../../etc/passwd", "x", zone="成品")

    async def test_symlink_escape_rejected(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        outside = atelier_root / "outside"
        outside.mkdir()
        (outside / "s.txt").write_text("x", encoding="utf-8")
        (paths.product_dir("lunch") / "link").symlink_to(outside, target_is_directory=True)
        with pytest.raises(PathEscapeError):
            await tools.atelier_artifact_write("lunch", "link/s.txt", "x", zone="成品")

    async def test_invalid_project_rejected(self, atelier_root: Path) -> None:
        with pytest.raises(ValidationError):
            await tools.atelier_artifact_write("../evil", "a.md", "x")

    async def test_invalid_zone_rejected(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        with pytest.raises(ValidationError) as ei:
            await tools.atelier_artifact_write("lunch", "a.md", "x", zone="中间件")
        assert "成品" in ei.value.detail.get("zone", "") or "素材" in (ei.value.hint or "")

    async def test_overwrite_false_refuses(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        await tools.atelier_artifact_write("lunch", "a.md", CLEAN, zone="成品", platform="xhs")
        r = await tools.atelier_artifact_write("lunch", "a.md", "新内容", zone="成品", overwrite=False)
        assert r["ok"] is False
        assert r["error"] == "文件已存在且 overwrite=false"

    async def test_overwrite_default_true(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        await tools.atelier_artifact_write("lunch", "a.md", "第一版", zone="成品", platform="xhs")
        r = await tools.atelier_artifact_write("lunch", "a.md", "第二版", zone="成品", platform="xhs")
        assert r["overwritten"] is True
        assert (paths.product_dir("lunch") / "a.md").read_text("utf-8") == "第二版"

    async def test_too_large_rejected(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        with pytest.raises(ValidationError) as ei:
            await tools.atelier_artifact_write("lunch", "big.md", "x" * (tools.MAX_WRITE_BYTES + 1), zone="素材")
        assert ei.value.http == 422


class TestLibraryList:
    async def test_empty_library(self, atelier_root: Path) -> None:
        paths.ensure_dirs()
        r = await tools.atelier_library_list()
        assert r["ok"] is True
        assert r["items"] == []

    async def test_lists_products_and_materials(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        paths.new_project("dinner")
        (paths.product_dir("lunch") / "a.md").write_text("x", encoding="utf-8")
        (paths.material_dir("lunch") / "b.png").write_text("y", encoding="utf-8")
        r = await tools.atelier_library_list()
        names = {(i["project"], i["name"]) for i in r["items"]}
        assert ("lunch", "a.md") in names
        assert ("lunch", "b.png") in names
        assert r["read_only"] is True

    async def test_filter_by_project(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        paths.new_project("dinner")
        (paths.product_dir("lunch") / "a.md").write_text("x", encoding="utf-8")
        (paths.product_dir("dinner") / "b.md").write_text("y", encoding="utf-8")
        r = await tools.atelier_library_list(project="lunch")
        assert [i["name"] for i in r["items"]] == ["a.md"]

    async def test_filter_by_zone(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        (paths.product_dir("lunch") / "a.md").write_text("x", encoding="utf-8")
        (paths.material_dir("lunch") / "b.png").write_text("y", encoding="utf-8")
        r = await tools.atelier_library_list(zone="素材")
        assert [i["name"] for i in r["items"]] == ["b.png"]

    async def test_limit(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        for i in range(5):
            (paths.product_dir("lunch") / f"{i}.md").write_text("x", encoding="utf-8")
        assert len((await tools.atelier_library_list(limit=2))["items"]) == 2

    async def test_system_files_hidden(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        r = await tools.atelier_library_list()
        assert all(".session" not in i["rel_path"] for i in r["items"])
        assert all(not i["name"].startswith(".atelier") for i in r["items"])

    async def test_invalid_project_rejected(self, atelier_root: Path) -> None:
        with pytest.raises(ValidationError):
            await tools.atelier_library_list(project="../x")

    async def test_is_read_only(self, atelier_root: Path) -> None:
        paths.new_project("lunch")
        before = sorted(p.name for p in paths.OUTPUTS.rglob("*"))
        await tools.atelier_library_list()
        assert sorted(p.name for p in paths.OUTPUTS.rglob("*")) == before


class TestSkillRun:
    """技能执行器由技能域提供（atelier/server/skills/），这里验证接线契约。"""

    _LONG_TEXT = (
        "首先，不得不承认，在当今这个快节奏的时代，内容创作已经发生了深刻的变化。"
        "其次，越来越多的创作者开始依赖人工智能工具来完成日常的写作工作。"
        "值得注意的是，这一趋势正在引发广泛的讨论和关注。"
    )

    async def test_missing_key_returns_blocked_not_bare_exception(self) -> None:
        """缺密钥要给出「缺哪个」的结构化信息，不能是裸异常。"""
        from atelier.server.skills import loader

        need = next((s for s in loader.list_skills() if getattr(s, "required_keys", None)), None)
        if need is None:  # 资产里没有需要密钥的技能时跳过，而不是写一个假断言
            pytest.skip("当前资产里没有需要密钥的技能")

        r = await tools.atelier_skill_run(need.id, {}, project="tools-wiring-test")
        assert r["ok"] is False
        assert r["blocked"] is True
        assert r["reason"] == "missing_keys"
        assert r["missing_keys"], "必须说清缺哪些密钥"
        assert r["fix_hint"]

    async def test_runs_a_real_skill_and_returns_artifacts(self) -> None:
        """能跑的技能要真产出产物路径。"""
        r = await tools.atelier_skill_run(
            "de-ai", {"text": self._LONG_TEXT}, project="tools-wiring-test"
        )
        assert r["ok"] is True, r
        assert r["artifacts"], "应返回至少一个产物"
        assert r["result_markdown"], "应返回可渲染的结果"

    async def test_skill_failure_surfaces_reason_not_bare_500(self) -> None:
        """输入不满足技能前置条件时，要把原因说出来（PRD 原则四）。

        注意：``str(exc)`` 只有摘要，真实原因在 ``exc.detail['stderr']`` 里——
        这正是「失败要留痕」要求的结构，不允许退化成裸 500。
        """
        from atelier.server.errors import SkillRunFailed

        with pytest.raises(SkillRunFailed) as ei:
            await tools.atelier_skill_run("de-ai", {"text": "太短了"}, project="tools-wiring-test")

        exc = ei.value
        detail = getattr(exc, "detail", None) or {}
        assert "返回码" in str(exc)
        assert detail.get("returncode") not in (None, 0)
        # 脚本自己给出的原因必须能透出来
        assert "字" in (detail.get("stderr") or ""), detail.get("stderr")


class TestProfileGet:
    def _write_profile(self, profile_id: str = "p1") -> Path:
        paths.ensure_dirs()
        md = paths.PROFILES / f"{profile_id}.md"
        md.write_text(
            "# 咖啡老王\n\n## 定位\n十年咖啡师，只聊豆子\n\n## 风格\n克制，先给结论\n\n"
            "## 受众\n一二线白领\n\n## 平台约束\n小红书标题不超过 20 字\n\n"
            "## 偏好红线\n不吹牛，不编数据\n\n## 长期记忆\n- 他爱用具体数字（归因）\n",
            encoding="utf-8",
        )
        return md

    async def test_missing_profile_raises(self, atelier_root: Path) -> None:
        with pytest.raises(ProfileNotFound) as ei:
            await tools.atelier_profile_get("nope")
        assert ei.value.http == 404
        assert "通用模式" in (ei.value.hint or "")

    async def test_invalid_profile_id_rejected(self, atelier_root: Path) -> None:
        with pytest.raises(ValidationError):
            await tools.atelier_profile_get("../etc/passwd")

    @pytest.mark.parametrize(
        ("dimension", "expect"),
        [("定位", "十年咖啡师"), ("风格", "克制"), ("受众", "白领"), ("偏好红线", "不吹牛")],
    )
    async def test_dimension_by_chinese_label(self, atelier_root: Path, dimension: str, expect: str) -> None:
        self._write_profile()
        r = await tools.atelier_profile_get("p1", dimension)
        assert r["ok"] is True
        assert expect in r["content"]

    async def test_dimension_by_english_key(self, atelier_root: Path) -> None:
        self._write_profile()
        r = await tools.atelier_profile_get("p1", "identity")
        assert r["dimension"] == "identity"
        assert "十年咖啡师" in r["content"]

    async def test_all_returns_whole_file(self, atelier_root: Path) -> None:
        self._write_profile()
        r = await tools.atelier_profile_get("p1", "all")
        assert "咖啡老王" in r["content"]
        assert "长期记忆" in r["content"]

    async def test_empty_dimension_returns_empty_string(self, atelier_root: Path) -> None:
        paths.ensure_dirs()
        (paths.PROFILES / "p2.md").write_text("# 空画像\n\n## 定位\n", encoding="utf-8")
        r = await tools.atelier_profile_get("p2", "风格")
        assert r["content"] == ""

    async def test_unknown_dimension_rejected(self, atelier_root: Path) -> None:
        self._write_profile()
        with pytest.raises(ValidationError) as ei:
            await tools.atelier_profile_get("p1", "胡说八道")
        assert "定位" in (ei.value.hint or "")


class TestGateInputHelper:
    def test_gate_input_from(self) -> None:
        gi = tools.gate_input_from("文本", platform="xhs", title="标题")
        assert gi.text == "文本"
        assert gi.platform == "xhs"
        assert gi.title == "标题"
        assert gi.image_paths == []
