"""SPEC-06 · 发布中心域测试。

覆盖 SPEC-06 §9 的清单，另加前端要验的 4 条硬交互对应的后端契约：

1. ``count_platform_chars`` 的中文口径（SPEC-06 §2）
2. 预检**分级**：BLOCK 阻断 / WARN 只告警（UI-SPEC 规则 17）
3. ★ **人设不一致绝不阻断**（F-G13 硬要求）
4. 发布必须 ``confirm: true``，有 BLOCK 未过时 422 ``GateBlocked``
5. ★ **单平台失败隔离**：一个失败另一个照常成功（SPEC-06 §4）
6. 错误码 → 人话映射（原则四）
7. 平台形态校验：抖音只吃视频、公众号必须有封面

所有测试都跑在 ``atelier_root`` 临时根下（conftest.py 已保证），不碰真实 outputs/var。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atelier.server.core.models import PlatformVariant, Profile, PublishDraft
from atelier.server.errors import GateBlocked, ValidationError
from atelier.server.gates.base import Severity
from atelier.server.main import create_app
from atelier.server.publish import adapt, dispatcher, precheck, wordcount
from atelier.server.publish.platforms import get_adapter
from atelier.server.publish.platforms.douyin import DouyinAdapter
from atelier.server.publish.platforms.wechat_mp import WechatMPAdapter
from atelier.server.publish.precheck import precheck_blocked, run_precheck
from atelier.server.publish.wordcount import count_platform_chars, crop_to_limit

JSON = {"Content-Type": "application/json"}

#: 抖音标题：按本域口径**正好 61 字**，抖音上限 55 → 61/55 触发硬门禁（原型同款读数）
DY_OVER_TITLE = (
    "我用 3 个 Agent 把内容流程砍掉一半，结果反而更慢了｜"
    "完整复盘 30 天实测：起号第 1 天就有人问我在用什么工具，附完整清单和 3 个真实踩坑记录啊快"
)
DY_SHORT_TITLE = "3 个 Agent 砍掉一半内容流程"
COVER_XHS = "card-01-1080x1440.png"  # 3:4
COVER_GZH = "cover-900x383.png"      # ≈2.35:1
VIDEO_DY = "vertical-1080x1920.mp4"


def test_fixture_title_is_exactly_61() -> None:
    """守住 61/55 这条验收读数：改文案时要重新数。

    注意是**平台口径计数**（空格/标点不计），不是 ``len()``——
    这正是 SPEC-06 §2 要求前端消费后端结果的原因。
    """
    assert count_platform_chars(DY_OVER_TITLE, "dy") == 61
    assert len(DY_OVER_TITLE) != 61  # 原始长度 ≠ 平台计数（标点与空格不计）
    assert adapt.limit_for("dy") == 55


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def client(atelier_root: Path) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seed_auth(atelier_root: Path) -> Iterator[Any]:
    """给三个平台种一条 ``platform_creds``：xhs/dy 有效，gzh 过期（验证 BLOCK 登录态）。"""
    from atelier.server.core.db import get_conn, init_db, utcnow

    init_db()
    rows = [
        ("c_xhs", "xhs", "@ai", "valid"),
        ("c_dy", "dy", "@ai_dy", "valid"),
        ("c_gzh", "gzh", "@gh", "expired"),
    ]
    for cid, plat, account, state in rows:
        get_conn().execute(
            "INSERT OR REPLACE INTO platform_creds (id, platform, account, secret_ref, state, verified_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, plat, account, f"keychain://{plat}", state, utcnow(), utcnow()),
        )
    get_conn().commit()
    yield get_conn


def _profile(**kw: Any) -> Profile:
    base = {
        "id": "p1", "name": "AI 效率观察", "platforms": ["xhs", "dy", "gzh"],
        "identity": "只讲自己真跑过的 AI 工作流", "style": "短句、只用真实经历、可以不用 emoji",
        "audience": "一个人做内容的小团队", "platform_rules": "",
        "preferences": "不用黑话，不吹疗效", "general_mode": False,
        "created_at": "2026-10-01T10:00:00Z", "updated_at": "2026-10-02T10:00:00Z",
    }
    base.update(kw)
    return Profile(**base)  # type: ignore[arg-type]


def _variant(platform: str, title: str, body: str, **kw: Any) -> PlatformVariant:
    v = PlatformVariant(
        platform=platform,  # type: ignore[arg-type]
        title=title, body=body, char_count=0,
        char_limit=adapt.limit_for(platform), over_limit=False,
        adapted=True, status="ready", **kw,
    )
    return adapt.recount(v)


def _draft(**kw: Any) -> PublishDraft:
    base = {
        "id": "pd_test", "project": None,
        "title": DY_SHORT_TITLE,
        "body": "上个月我同时跑 3 个 AI 写稿，产出越来越像同一篇。问题不在工具，在于每次对话都从零开始。",
        "topic_tags": ["AI工作流"], "variants": [], "attachments": [],
        "created_at": "2026-10-02T10:00:00Z", "updated_at": "2026-10-02T10:00:00Z",
    }
    base.update(kw)
    return PublishDraft(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T1 · 字数计数（SPEC-06 §2）
# ---------------------------------------------------------------------------


class TestCharCount:
    def test_char_count_rules_zh_en_emoji(self) -> None:
        """中文 1 字 = 1；英文 1 词 = 1；emoji 1 个 = 2；空格标点不计。"""
        assert count_platform_chars("你好世界", "xhs") == 4
        assert count_platform_chars("hello world", "xhs") == 2  # 按词，不按字母
        assert count_platform_chars("你好，world！", "xhs") == 3  # 逗号感叹号不计
        assert count_platform_chars("😀", "xhs") == 2  # emoji = 2
        assert count_platform_chars("你好 😀 world", "xhs") == 2 + 2 + 1
        assert count_platform_chars("#AI工作流 内容创作", "xhs") == 8  # # 不计
        assert count_platform_chars("2026 年", "xhs") == 2

    def test_emoji_zwj_sequence_counts_once(self) -> None:
        """ZWJ 家庭 emoji 算 1 个（= 2），不按 3 个头像算 6。"""
        assert count_platform_chars("👨‍👩‍👧 家庭", "xhs") == 4

    def test_unknown_platform_does_not_raise(self) -> None:
        """传未知平台不能把页面搞崩（将来加平台时的向前兼容）。"""
        assert count_platform_chars("你好", "unknown_platform") == 2

    def test_crop_to_limit_respects_boundary_and_limit(self) -> None:
        cropped, before, after = crop_to_limit(DY_OVER_TITLE, 55)
        assert before > 55
        assert after <= 55
        assert len(cropped) <= len(DY_OVER_TITLE)
        # 未超限时原样返回，不加省略号
        assert crop_to_limit("短句。", 100) == ("短句。", 2, 2)

    def test_per_platform_limits_correct(self) -> None:
        """SPEC-06 §2 的平台约束表逐字段核对。"""
        assert adapt.PLATFORM_LIMITS["xhs"]["body_max"] == 1000
        assert adapt.PLATFORM_LIMITS["xhs"]["title_max"] == 20
        assert adapt.PLATFORM_LIMITS["xhs"]["cover_ratio"] == "3:4"
        assert adapt.PLATFORM_LIMITS["dy"]["body_max"] == 55
        assert adapt.PLATFORM_LIMITS["dy"]["forms"] == ["video"]
        assert adapt.PLATFORM_LIMITS["dy"]["needs_cover"] is False
        assert adapt.PLATFORM_LIMITS["gzh"]["body_max"] == 20000
        assert adapt.PLATFORM_LIMITS["gzh"]["cover_ratio"] == "2.35:1"

    def test_variant_recount_uses_shared_platform_counter(self) -> None:
        """★ variant 的字数读数来自平台口径（与门禁同一个函数，SPEC-06 §2）。"""
        v = adapt.blank_variant("xhs")
        v.body = "hello world 你好"
        adapt.recount(v)
        assert v.char_count == 4  # 2 词 + 2 字
        assert v.char_limit == 1000
        assert v.over_limit is False

        v.body = "字" * 1001
        adapt.recount(v)
        assert v.char_count == 1001
        assert v.over_limit is True


# ---------------------------------------------------------------------------
# T2 · 适配（SPEC-06 §2）
# ---------------------------------------------------------------------------


class TestAdapt:
    async def test_stream_adapt_emits_deltas_and_done(self, atelier_root: Path) -> None:
        """MockHarness 下：逐字 delta + 一条 done，最终 variant 可用。"""
        d = _draft(variants=[adapt.blank_variant("xhs")])
        events = [e async for e in adapt.stream_adapt(d, "xhs", _profile())]
        kinds = [e["type"] for e in events]
        assert "delta" in kinds
        assert kinds[-1] == "done"
        done = events[-1]
        assert done["char_limit"] == 1000
        assert done["char_count"] >= 0

    async def test_prompt_contains_limits_master_and_profile(self) -> None:
        """system_prompt 里必须同时有：平台约束表 + 母版原文 + 画像（SPEC-06 §2）。"""
        d = _draft()
        p = adapt.build_adapt_prompt(d, ["dy"], _profile())
        assert "抖音" in p and "55" in p
        assert d.body[:12] in p
        assert "AI 效率观察" in p or "只讲自己真跑过" in p

    async def test_adapt_isolates_single_platform_failure(self, atelier_root: Path, monkeypatch) -> None:
        """★ 一个平台适配失败不影响其他平台（SPEC-06 §2 硬要求）。"""
        d = _draft(variants=[adapt.blank_variant("xhs"), adapt.blank_variant("dy")])
        orig = adapt.stream_adapt

        async def flaky(draft, platform, profile, **kw):
            if platform == "dy":
                yield adapt.AdaptEvent(type="error", platform="dy", message="抖音适配炸了")
                return
            async for e in orig(draft, platform, profile, **kw):
                yield e

        monkeypatch.setattr(adapt, "stream_adapt", flaky)
        got = [e async for e in adapt.adapt_platforms(d, ["xhs", "dy"], _profile())]
        summary = got[-1]
        assert summary["type"] == "summary"
        assert summary["ok"] == ["xhs"]
        assert "dy" in summary["failed"]


# ---------------------------------------------------------------------------
# T3 · 预检分级（SPEC-06 §3）
# ---------------------------------------------------------------------------


class TestPrecheck:
    async def test_precheck_blocks_on_wordcount(self, atelier_root: Path, seed_auth: Any) -> None:
        """抖音标题 61/55 → BLOCK 硬门禁。"""
        d = _draft(variants=[_variant("dy", DY_OVER_TITLE, "正文")])
        items = await run_precheck(d, _profile(), selected=["dy"])
        wc = next(i for i in items if i.id == "wordcount:dy")
        assert wc.severity == Severity.BLOCK
        assert wc.passed is False
        assert count_platform_chars(DY_OVER_TITLE, "dy") == 61
        assert "55" in wc.message
        assert precheck_blocked(items) is True

    async def test_precheck_dy_body_over_limit_also_blocks(
        self, atelier_root: Path, seed_auth: Any
    ) -> None:
        """★ 抖音正文也限 55：标题合规但正文超限，同样必须拦。

        口径一致性：预检（SPEC-06 §3）与 adapter 校验（SPEC-06 §5）必须同判，
        否则会出现「预检说过了、发布时 adapter 又报超限」的自相矛盾。
        """
        long_body = "口" * 66
        d = _draft(variants=[_variant("dy", DY_SHORT_TITLE, long_body)])
        items = await run_precheck(d, _profile(), selected=["dy"])
        wc = next(i for i in items if i.id == "wordcount:dy")
        assert wc.passed is False
        assert "66" in wc.message and "55" in wc.message
        assert precheck_blocked(items) is True

        # 且 adapter 的判定与预检一致（同一个 fail）
        from atelier.server.publish.platforms.douyin import DouyinAdapter

        v = next(x for x in d.variants if x.platform == "dy")
        assert DouyinAdapter().validate(v, [VIDEO_DY]) is not None

    async def test_precheck_warns_on_persona_mismatch(self, atelier_root: Path, seed_auth: Any) -> None:
        """人设不一致 → WARN，且 message 写明「不阻断」。"""
        d = _draft(
            title=DY_SHORT_TITLE,
            body="本篇将通过闭环打法打造心智抓手，颗粒度拉满，实现势能跃迁。",
            variants=[_variant("xhs", "很棒的一篇", "闭环打法、心智抓手、颗粒度拉满")],
            attachments=[COVER_XHS],
        )
        items = await run_precheck(d, _profile(), selected=["xhs"])
        persona = next(i for i in items if i.id == "persona")
        assert persona.severity == Severity.WARN
        assert persona.passed is False
        assert "不阻断" in persona.message

    async def test_precheck_never_blocks_on_warn_only(self, atelier_root: Path, seed_auth: Any) -> None:
        """★ F-G13 硬要求：只有 WARN 未过时，预检**不得**阻断。"""
        d = _draft(
            title="随便一个没有钩子的标题",
            body="闭环打法、心智抓手、颗粒度拉满，赋能团队势能。",
            variants=[_variant("xhs", "随便一个没有钩子的标题", "闭环打法、心智抓手、颗粒度拉满，赋能团队。")],
            attachments=[COVER_XHS],
        )
        items = await run_precheck(d, _profile(), selected=["xhs"])
        warns = [i for i in items if i.severity == Severity.WARN and not i.passed]
        assert warns, "这个草稿应当至少有一条 WARN 未过"
        blocks = [i for i in items if i.severity == Severity.BLOCK and not i.passed]
        assert blocks == [], f"不该有 BLOCK 未过，但有：{[b.id for b in blocks]}"
        assert precheck_blocked(items) is False

    async def test_precheck_persona_general_mode_passes(self, atelier_root: Path, seed_auth: Any) -> None:
        """通用模式不注入画像 → 人设项跳过且不算未过。"""
        d = _draft(variants=[_variant("xhs", "标题在这里", "正文内容在这里写足够长一些"), ],
                   attachments=[COVER_XHS])
        items = await run_precheck(d, None, selected=["xhs"])
        persona = next(i for i in items if i.id == "persona")
        assert persona.passed is True
        assert persona.severity == Severity.WARN

    async def test_precheck_block_on_missing_cover_and_auth(self, atelier_root: Path, seed_auth: Any) -> None:
        """封面缺失与登录态失效都是 BLOCK。"""
        d = _draft(variants=[_variant("gzh", "公众号标题", "公众号正文内容，写得足够长一些以通过校验")])
        items = await run_precheck(d, _profile(), selected=["gzh"])
        cover = next(i for i in items if i.id == "cover:gzh")
        auth = next(i for i in items if i.id == "auth:gzh")
        assert cover.severity == Severity.BLOCK and cover.passed is False
        assert auth.severity == Severity.BLOCK and auth.passed is False  # gzh 种的是 expired
        assert precheck_blocked(items) is True

    async def test_precheck_secret_scan_is_fail_closed_block(self, atelier_root: Path, seed_auth: Any) -> None:
        """出站密钥命中 → BLOCK（fail-closed）。"""
        d = _draft(
            title="我的 API 配置",
            body="我的 key 是 sk-ant-abcdefghijklmnopqrstuvwxyz123456 请勿外传。",
            variants=[_variant("xhs", "我的 API 配置", "key 是 sk-ant-abcdefghijklmnopqrstuvwxyz123456")],
            attachments=[COVER_XHS],
        )
        items = await run_precheck(d, _profile(), selected=["xhs"])
        sec = next(i for i in items if i.id == "secret_scan")
        assert sec.severity == Severity.BLOCK
        assert sec.passed is False
        assert precheck_blocked(items) is True

    async def test_title_score_warns_not_blocks(self, atelier_root: Path, seed_auth: Any) -> None:
        """标题打分是 WARN。"""
        d = _draft(title="随便写的", variants=[_variant("xhs", "随便写的", "正文内容在这里写足够长一些")],
                   attachments=[COVER_XHS])
        items = await run_precheck(d, _profile(), selected=["xhs"])
        score = next(i for i in items if i.id == "title_score")
        assert score.severity == Severity.WARN
        assert precheck_blocked(items) is False

    def test_precheck_blocked_ignores_warn_items(self) -> None:
        """纯函数层面再钉一次：只有 BLOCK 参与阻断判定。"""
        items = [
            precheck.PrecheckItem(id="a", label="a", severity=Severity.WARN, passed=False, message="x"),
            precheck.PrecheckItem(id="b", label="b", severity=Severity.BLOCK, passed=True, message="y"),
        ]
        assert precheck_blocked(items) is False


# ---------------------------------------------------------------------------
# T4 · 平台 adapter 校验（SPEC-06 §5）
# ---------------------------------------------------------------------------


class TestAdapters:
    def test_douyin_video_only_rejects_image(self) -> None:
        """★ 抖音只接受视频：挂图片 = 形态不合法，必须在发之前拦住。"""
        dy = DouyinAdapter()
        v = _variant("dy", DY_SHORT_TITLE, "口播短句")
        bad = dy.validate(v, [COVER_XHS])
        assert bad is not None
        assert bad.ok is False
        assert bad.error_code == "dy_form_rejected"
        assert "视频" in (bad.error or "")
        # 有视频就通过形态校验
        assert dy.validate(v, [VIDEO_DY]) is None

    def test_gzh_requires_cover(self) -> None:
        """★ 公众号必须有封面图，且比例要对。"""
        gzh = WechatMPAdapter()
        v = _variant("gzh", "公众号标题", "公众号正文内容，写得足够长一些以通过校验")
        missing = gzh.validate(v, [])
        assert missing is not None
        assert missing.error_code == "gzh_no_cover"

        good = gzh.validate(v, [COVER_GZH])
        assert good is None, f"2.35:1 封面应通过，实际：{good and good.error}"

        wrong_ratio = gzh.validate(v, [COVER_XHS])  # 3:4 不满足 2.35:1
        assert wrong_ratio is not None
        assert wrong_ratio.error_code == "gzh_no_cover"

    def test_xhs_requires_media(self) -> None:
        xhs = get_adapter("xhs")
        v = _variant("xhs", "小红书标题", "正文")
        assert xhs.validate(v, []) is not None
        assert xhs.validate(v, [COVER_XHS]) is None

    async def test_publish_is_dry_run_and_says_so(self) -> None:
        """★ dry-run 必须在 raw 里诚实标明是模拟执行，不许假装真发出去了。"""
        dy = DouyinAdapter()
        v = _variant("dy", DY_SHORT_TITLE, "口播短句")
        res = await dy.publish(v, [VIDEO_DY], dry_run=True)
        assert res.ok is True
        assert res.raw["dry_run"] is True
        assert res.raw["simulated"] is True
        assert "模拟执行" in res.raw["notice"]
        assert res.url is None  # 没有真发出去，就不给假 URL

    async def test_real_publish_refuses_instead_of_faking(self) -> None:
        """dry_run=False 必须显式说「未接入」，绝不能假装成功。"""
        dy = DouyinAdapter()
        v = _variant("dy", DY_SHORT_TITLE, "口播短句")
        res = await dy.publish(v, [VIDEO_DY], dry_run=False)
        assert res.ok is False
        assert res.error_code == "not_implemented"

    async def test_check_auth_reads_platform_creds_not_marker_file(self, atelier_root: Path, seed_auth: Any) -> None:
        """登录态是**真校验**：读 platform_creds 表，不是看标记文件。"""
        assert (await DouyinAdapter().check_auth()).logged_in is True
        assert (await WechatMPAdapter().check_auth()).logged_in is False

    async def test_check_auth_missing_row_is_not_logged_in(self, atelier_root: Path) -> None:
        st = await DouyinAdapter().check_auth()
        assert st.logged_in is False
        assert "未登录" in st.message

    def test_get_adapter_unknown_platform_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            get_adapter("weibo")


# ---------------------------------------------------------------------------
# T5 · 错误码 → 人话（原则四）
# ---------------------------------------------------------------------------


class TestErrorHints:
    def test_error_code_mapped_to_human_text(self) -> None:
        """SPEC-06 §4 的 5 个错误码必须都有明确的人话，不许只显示裸码。"""
        assert dispatcher.ERROR_HINTS["dy_auth_4012"] == "登录态过期，需重新扫码 + 短信验证码"
        assert "5 分钟内有效" in dispatcher.ERROR_HINTS["dy_sms_required"]
        assert "风控" in dispatcher.ERROR_HINTS["xhs_risk_control"]
        assert dispatcher.ERROR_HINTS["gzh_no_cover"] == "公众号图文必须有封面图"
        assert "超时" in dispatcher.ERROR_HINTS["timeout"]

    def test_unknown_error_code_still_gets_human_text(self) -> None:
        """未知码也要给人话 + 指向日志（原则四）。"""
        hint = dispatcher.error_hint("platform_brand_new_9000")
        assert "platform_brand_new_9000" in hint
        assert "日志" in hint
        assert dispatcher.error_hint(None) == ""

    def test_status_machine_allows_defined_transitions(self) -> None:
        """状态机只允许 SPEC-06 §4 定义的迁移。"""
        assert "ready" in dispatcher.STATUS_FLOW["adapting"]
        assert "sent" in dispatcher.STATUS_FLOW["publishing"]
        assert "awaiting_sms" in dispatcher.STATUS_FLOW["publishing"]
        assert "publishing" in dispatcher.STATUS_FLOW["awaiting_sms"]
        assert dispatcher.STATUS_FLOW["sent"] == set()


# ---------------------------------------------------------------------------
# T6 · 发布编排（SPEC-06 §4）
# ---------------------------------------------------------------------------


class TestPublishDispatch:
    async def test_publish_blocked_when_gate_fails(self, atelier_root: Path, seed_auth: Any) -> None:
        """抖音标题超字数 → 抛 GateBlocked（422），带 gate_items。"""
        d = _draft(variants=[_variant("dy", DY_OVER_TITLE, "正文")])
        with pytest.raises(GateBlocked) as ei:
            await dispatcher.publish_draft(d, ["dy"], _profile(), confirm=True)
        assert ei.value.code == "GateBlocked"
        assert ei.value.http == 422
        assert ei.value.detail["gate_items"]
        assert "抖音" in ei.value.detail["gate_items"][0]["label"]

    async def test_blocked_message_is_readable_without_dangling_slash(
        self, atelier_root: Path, seed_auth: Any
    ) -> None:
        """登录态这类没有字数读数的项，message 不能拼出「标签 /」这种断头句。"""
        d = _draft(variants=[_variant("gzh", "公众号标题", "公众号正文内容，写得足够长一些以通过校验")],
                   attachments=[COVER_GZH])
        with pytest.raises(GateBlocked) as ei:
            await dispatcher.publish_draft(d, ["gzh"], _profile(), confirm=True)
        msg = ei.value.message
        assert msg.startswith("硬门禁未通过：")
        assert not msg.rstrip().endswith("/")
        assert "61/55" not in msg  # 这条是 gzh 登录态，不该出现字数读数

    async def test_blocked_message_includes_wordcount_reading(
        self, atelier_root: Path, seed_auth: Any
    ) -> None:
        d = _draft(variants=[_variant("dy", DY_OVER_TITLE, "正文")])
        with pytest.raises(GateBlocked) as ei:
            await dispatcher.publish_draft(d, ["dy"], _profile(), confirm=True)
        assert "61 / 55" in ei.value.message or "61/55" in ei.value.message

    async def test_publish_requires_confirm(self, atelier_root: Path, seed_auth: Any) -> None:
        """★ 缺 confirm 直接拒（服务端二次确认，SPEC-06 §4）。"""
        d = _draft(variants=[_variant("dy", DY_SHORT_TITLE, "口播")], attachments=[VIDEO_DY])
        with pytest.raises(ValidationError) as ei:
            await dispatcher.publish_draft(d, ["dy"], _profile(), confirm=False)
        assert "二次确认" in ei.value.message
        assert ei.value.http == 422

    async def test_publish_no_platform_raises(self, atelier_root: Path) -> None:
        d = _draft()
        with pytest.raises(ValidationError):
            await dispatcher.publish_draft(d, [], _profile(), confirm=True)

    async def test_single_platform_failure_isolated(self, atelier_root: Path, monkeypatch, seed_auth: Any) -> None:
        """★ 抖音失败，小红书**仍然成功**（SPEC-06 §4 / §8 验收 11）。"""
        from atelier.server.publish.platforms import douyin as dy_mod

        async def boom(*a, **kw):
            raise RuntimeError("模拟平台接口炸了")

        monkeypatch.setattr(dy_mod.adapter, "publish", boom)

        d = _draft(
            variants=[_variant("dy", DY_SHORT_TITLE, "口播"), _variant("xhs", "小红书标题", "正文内容写长一点")],
            attachments=[VIDEO_DY, COVER_XHS],
        )
        result = await dispatcher.publish_draft(d, ["dy", "xhs"], _profile(), confirm=True)

        by = {r.platform: r for r in result.results}
        assert by["dy"].status == "failed"
        assert by["dy"].error_code == "publish_failed"
        assert by["dy"].hint  # 有人话提示
        assert by["xhs"].status == "sent"  # ★ 另一个平台照常成功
        assert result.failed_count == 1
        assert result.ok_count == 1
        assert by["dy"].dry_run is True and by["xhs"].dry_run is True
        assert "模拟执行" in result.notice

    async def test_persona_mismatch_still_publishable(self, atelier_root: Path, seed_auth: Any) -> None:
        """★ F-G13 硬验收：人设不一致时**仍可发布**，只告警。"""
        d = _draft(
            title="随便一个没有钩子的标题",
            body="闭环打法、心智抓手、颗粒度拉满，赋能团队势能跃迁。",
            variants=[_variant("xhs", "随便一个标题", "闭环打法、心智抓手、颗粒度拉满，赋能团队。")],
            attachments=[COVER_XHS],
        )
        items = await run_precheck(d, _profile(), selected=["xhs"])
        assert precheck_blocked(items) is False
        result = await dispatcher.publish_draft(d, ["xhs"], _profile(), confirm=True)
        assert result.results[0].status == "sent"

    async def test_publish_marks_variant_status_sent(self, atelier_root: Path, seed_auth: Any) -> None:
        d = _draft(variants=[_variant("dy", DY_SHORT_TITLE, "口播")], attachments=[VIDEO_DY])
        await dispatcher.publish_draft(d, ["dy"], _profile(), confirm=True)
        v = next(x for x in d.variants if x.platform == "dy")
        assert v.status == "sent"

    async def test_failed_auth_maps_to_platform_error_code(self, atelier_root: Path, seed_auth: Any) -> None:
        """gzh 种的是 expired → 登录态 BLOCK 的那条路径，错误码要是人话能懂的那个。"""
        d = _draft(
            variants=[_variant("gzh", "公众号标题", "公众号正文内容，写得足够长一些以通过校验")],
            attachments=[COVER_GZH],
        )
        with pytest.raises(GateBlocked) as ei:
            await dispatcher.publish_draft(d, ["gzh"], _profile(), confirm=True)
        ids = [i["id"] for i in ei.value.detail["gate_items"]]
        assert "auth:gzh" in ids


# ---------------------------------------------------------------------------
# T7 · HTTP API（SPEC-06 §6 的 14 个端点）
# ---------------------------------------------------------------------------


class TestPublishApi:
    def test_platforms_endpoint_exposes_limits_and_auth(self, client: TestClient) -> None:
        r = client.get("/api/publish/platforms")
        assert r.status_code == 200
        data = r.json()
        keys = {p["platform"] for p in data["platforms"]}
        # M4 起共 7 平台（SPEC-14 §0 D1/D2）
        assert keys == {"xhs", "dy", "gzh", "ks", "zhihu", "bilibili", "wcs"}
        dy = next(p for p in data["platforms"] if p["platform"] == "dy")
        assert dy["body_max"] == 55
        assert dy["title_max"] == 55
        assert dy["cover_ratio"] is None
        assert dy["forms"] == ["video"]
        assert dy["auth"]["platform"] == "dy"  # 真校验结果（此测试未种凭证 → 未登录）
        assert dy["auth"]["logged_in"] is False
        assert dy["constraint"] and "55" in dy["constraint"]

    def test_platforms_endpoint_reflects_real_auth_state(self, client: TestClient, seed_auth: Any) -> None:
        """登录态来自 platform_creds 表的真校验，不是固定值。"""
        data = client.get("/api/publish/platforms").json()
        by = {p["platform"]: p for p in data["platforms"]}
        assert by["xhs"]["auth"]["logged_in"] is True
        assert by["dy"]["auth"]["logged_in"] is True
        assert by["dy"]["auth"]["need_sms"] is True  # 抖音可能弹短信墙
        assert by["gzh"]["auth"]["logged_in"] is False  # 种的是 expired

    def test_draft_crud_and_autosave_roundtrip(self, client: TestClient) -> None:
        """★ 草稿改标题刷新后不丢（F-G17 / §8 验收 9）。"""
        created = client.post("/api/publish/drafts", headers=JSON, json={"title": "初稿", "body": "正文"}).json()
        did = created["id"]
        assert client.get(f"/api/publish/drafts/{did}").json()["title"] == "初稿"

        # 前端 debounce 800ms 只发改动的字段
        patched = client.patch(f"/api/publish/drafts/{did}", headers=JSON, json={"title": "改过的标题"}).json()
        assert patched["title"] == "改过的标题"
        assert patched["body"] == "正文"  # 未改字段保留

        reloaded = client.get(f"/api/publish/drafts/{did}").json()
        assert reloaded["title"] == "改过的标题"  # 刷新后还在

        listing = client.get("/api/publish/drafts").json()
        assert any(d["id"] == did for d in listing["drafts"])

        token = client.post("/api/publish/confirm-token", headers=JSON, json={"draft_id": did}).json()["token"]
        # 写请求要带 Content-Type（跨站写拦截，SPEC-01 §8）
        assert client.delete(
            f"/api/publish/drafts/{did}", headers=JSON, params={"confirm": token}
        ).status_code == 200
        assert client.get(f"/api/publish/drafts/{did}").status_code == 404

    def test_draft_topic_link_and_schedule(self, client: TestClient) -> None:
        """SPEC-10 §2：草稿可关联选题与排期；坏选题 404；空串清空；缺省不动。"""
        tid = client.post("/api/topics", headers=JSON, json={"title": "被关联的选题"}).json()["id"]
        did = client.post(
            "/api/publish/drafts", headers=JSON,
            json={"title": "排期草稿", "topic_id": tid, "scheduled_date": "2026-11-11"},
        ).json()["id"]
        body = client.get(f"/api/publish/drafts/{did}").json()
        assert body["topic_id"] == tid and body["scheduled_date"] == "2026-11-11"
        # 选题不存在 → 404（SPEC-10 §0 D5）
        r = client.patch(f"/api/publish/drafts/{did}", headers=JSON, json={"topic_id": "topic-none"})
        assert r.status_code == 404
        # 非零填充日期 → 422（D6，复用选题 due_date 校验）
        r = client.patch(f"/api/publish/drafts/{did}", headers=JSON, json={"scheduled_date": "2026-1-1"})
        assert r.status_code == 422
        # 缺省不动
        patched = client.patch(f"/api/publish/drafts/{did}", headers=JSON, json={"title": "新标题"}).json()
        assert patched["topic_id"] == tid and patched["scheduled_date"] == "2026-11-11"
        # "" 清空（归 NULL）
        patched = client.patch(
            f"/api/publish/drafts/{did}", headers=JSON, json={"topic_id": "", "scheduled_date": ""}
        ).json()
        assert patched["topic_id"] is None and patched["scheduled_date"] is None

    def test_delete_draft_requires_confirm_token(self, client: TestClient) -> None:
        did = client.post("/api/publish/drafts", headers=JSON, json={"title": "x"}).json()["id"]
        # 缺 confirm 参数 → FastAPI 参数校验 422
        assert client.delete(f"/api/publish/drafts/{did}", headers=JSON).status_code == 422
        r = client.delete(f"/api/publish/drafts/{did}", headers=JSON, params={"confirm": "not-a-token"})
        assert r.status_code == 422
        assert client.get(f"/api/publish/drafts/{did}").status_code == 200

    def test_precheck_endpoint_reports_items_and_blocked(self, client: TestClient) -> None:
        did = _seed_draft_with_variant(client, "dy", DY_OVER_TITLE, "正文")
        r = client.post(f"/api/publish/drafts/{did}/precheck", headers=JSON, json={})
        assert r.status_code == 200
        data = r.json()
        ids = {i["id"] for i in data["items"]}
        assert "compliance" in ids and "persona" in ids and "title_score" in ids
        assert data["blocked"] is True
        persona = next(i for i in data["items"] if i["id"] == "persona")
        assert persona["severity"] == "warn"  # 人设一致性永远是 warn

    def test_publish_endpoint_returns_422_gate_blocked(self, client: TestClient, seed_auth: Any) -> None:
        """★ 超字数点发布 → 422 GateBlocked + gate_items。"""
        did = _seed_draft_with_variant(client, "dy", DY_OVER_TITLE, "正文", attachments=[VIDEO_DY])
        r = client.post(f"/api/publish/drafts/{did}/publish", headers=JSON, json={"confirm": True, "platforms": ["dy"]})
        assert r.status_code == 422
        body = r.json()["error"]
        assert body["code"] == "GateBlocked"
        assert body["detail"]["gate_items"]

    def test_publish_endpoint_requires_confirm(self, client: TestClient, seed_auth: Any) -> None:
        did = _seed_draft_with_variant(client, "dy", DY_SHORT_TITLE, "口播", attachments=[VIDEO_DY])
        r = client.post(f"/api/publish/drafts/{did}/publish", headers=JSON, json={"confirm": False})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "ValidationError"

    def test_publish_endpoint_returns_results_with_dry_run_notice(self, client: TestClient, seed_auth: Any) -> None:
        """★ dry-run 必须在响应里诚实标明（验收第 10 条）。"""
        did = _seed_draft_with_variant(client, "dy", DY_SHORT_TITLE, "口播", attachments=[VIDEO_DY])
        r = client.post(f"/api/publish/drafts/{did}/publish", headers=JSON, json={"confirm": True, "platforms": ["dy"]})
        assert r.status_code == 200
        data = r.json()
        assert data["dry_run"] is True
        assert "模拟执行" in data["notice"]
        res = data["results"][0]
        assert res["platform"] == "dy"
        assert res["status"] == "sent"
        assert res["dry_run"] is True
        assert "模拟执行" in res["raw"]["notice"]

    def test_autofix_resolves_over_limit(self, client: TestClient, seed_auth: Any) -> None:
        """★ 点「一键裁剪」→ 门禁解除（§8 验收 4）。"""
        did = _seed_draft_with_variant(client, "dy", DY_OVER_TITLE, "正文", attachments=[VIDEO_DY])
        before = client.post(f"/api/publish/drafts/{did}/precheck", headers=JSON, json={"platforms": ["dy"]}).json()
        assert before["blocked"] is True
        assert before["items"]

        fx = client.post(
            f"/api/publish/drafts/{did}/autofix", headers=JSON, json={"platform": "dy", "field": "title"}
        )
        assert fx.status_code == 200
        body = fx.json()
        assert body["before"] == 61
        assert body["after"] <= 55

        after = client.post(f"/api/publish/drafts/{did}/precheck", headers=JSON, json={"platforms": ["dy"]}).json()
        wc = next(i for i in after["items"] if i["id"] == "wordcount:dy")
        assert wc["passed"] is True

    def test_autofix_rejects_unknown_platform_and_field(self, client: TestClient) -> None:
        did = client.post("/api/publish/drafts", headers=JSON, json={"title": "x"}).json()["id"]
        assert client.post(
            f"/api/publish/drafts/{did}/autofix", headers=JSON, json={"platform": "weibo", "field": "body"}
        ).status_code == 422
        assert client.post(
            f"/api/publish/drafts/{did}/autofix", headers=JSON, json={"platform": "dy", "field": "summary"}
        ).status_code == 422

    def test_autofix_all_crops_title_and_body_together(self, client: TestClient, seed_auth: Any) -> None:
        """★ 抖音标题与正文同限 55：field=all 两个都裁，否则门禁解不掉。"""
        long_body = "口" * 66
        did = _seed_draft_with_variant(client, "dy", DY_OVER_TITLE, long_body, attachments=[VIDEO_DY])
        fx = client.post(
            f"/api/publish/drafts/{did}/autofix", headers=JSON, json={"platform": "dy", "field": "all"}
        )
        assert fx.status_code == 200
        body = fx.json()
        assert set(body["changes"]) == {"title", "body"}
        assert body["changes"]["title"]["before"] == 61
        assert body["changes"]["body"]["before"] == 66
        assert body["changes"]["title"]["after"] <= 55
        assert body["changes"]["body"]["after"] <= 55

        after = client.post(f"/api/publish/drafts/{did}/precheck", headers=JSON, json={"platforms": ["dy"]}).json()
        wc = next(i for i in after["items"] if i["id"] == "wordcount:dy")
        assert wc["passed"] is True

        # 裁完之后真能发出去（预检 + adapter 两道都过）
        r = client.post(f"/api/publish/drafts/{did}/publish", headers=JSON,
                        json={"confirm": True, "platforms": ["dy"]})
        assert r.status_code == 200, r.text
        assert r.json()["results"][0]["status"] == "sent"

    def test_adapt_endpoint_streams_sse(self, client: TestClient) -> None:
        """★ 适配走 SSE，逐字事件（F-G10）。"""
        did = _seed_draft_with_variant(client, "xhs", "标题", "正文内容")
        with client.stream(
            "POST", f"/api/publish/drafts/{did}/adapt", headers=JSON, json={"platforms": ["xhs"]}
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            lines = [ln for ln in resp.iter_lines() if ln.startswith("data: ")]

        payloads = [json.loads(ln[6:]) for ln in lines]
        kinds = {p.get("type") for p in payloads}
        assert "delta" in kinds
        assert "variant" in kinds
        assert "summary" in kinds
        variant = next(p for p in payloads if p.get("type") == "variant")["variant"]
        assert variant["adapted"] is True
        assert variant["char_limit"] == 1000

        # 落库后可读回
        saved = client.get(f"/api/publish/drafts/{did}").json()
        assert any(v["platform"] == "xhs" and v["adapted"] for v in saved["variants"])

    def test_adapt_requires_platform(self, client: TestClient) -> None:
        did = client.post("/api/publish/drafts", headers=JSON, json={"title": "x"}).json()["id"]
        r = client.post(f"/api/publish/drafts/{did}/adapt", headers=JSON, json={"platforms": []})
        assert r.status_code == 422

    def test_records_endpoint_and_retry(self, client: TestClient, seed_auth: Any) -> None:
        """发布记录可查；已 sent 的记录不重复发。"""
        did = _seed_draft_with_variant(client, "dy", DY_SHORT_TITLE, "口播", attachments=[VIDEO_DY])
        client.post(f"/api/publish/drafts/{did}/publish", headers=JSON, json={"confirm": True, "platforms": ["dy"]})
        recs = client.get(f"/api/publish/drafts/{did}/records").json()
        assert recs["count"] == 1
        rec = recs["records"][0]
        assert rec["platform_name"] == "抖音"
        assert rec["dry_run"] is True

        again = client.post(f"/api/publish/records/{rec['id']}/retry", headers=JSON, json={})
        assert again.json()["skipped"] is True
        assert client.post("/api/publish/records/nope/retry", headers=JSON, json={}).status_code == 404

    def test_sms_endpoints(self, client: TestClient) -> None:
        """短信墙状态轮询 + 提交验证码（真实验证属 M4）。"""
        rec = dispatcher.new_record_id()
        st = client.get(f"/api/publish/sms/{rec}").json()
        assert st["need_sms"] is False

        opened = dispatcher.open_sms_wall(rec)
        assert opened["need_sms"] is True
        assert 0 < opened["expires_in"] <= dispatcher.SMS_TTL

        st2 = client.get(f"/api/publish/sms/{rec}").json()
        assert st2["need_sms"] is True

        bad = client.post(f"/api/publish/sms/{rec}", headers=JSON, json={"code": "12"})
        assert bad.status_code == 422
        ok = client.post(f"/api/publish/sms/{rec}", headers=JSON, json={"code": "123456"})
        assert ok.status_code == 200 and ok.json()["accepted"] is True
        assert client.get(f"/api/publish/sms/{rec}").json()["need_sms"] is False

    def test_publish_404_for_missing_draft(self, client: TestClient) -> None:
        r = client.post("/api/publish/drafts/nope_draft/publish", headers=JSON, json={"confirm": True})
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NotFound"


def _seed_draft_with_variant(
    client: TestClient, platform: str, title: str, body: str, *, attachments: list[str] | None = None
) -> str:
    """建一份草稿并塞一个 variant（走真实 PATCH 链路）。"""
    did = client.post("/api/publish/drafts", headers=JSON, json={"title": title, "body": body}).json()["id"]
    v = adapt.blank_variant(platform, title, body)
    v.title = title
    v.body = body
    v.adapted = True
    v.status = "ready"
    adapt.recount(v)
    payload = {"variants": [json.loads(v.model_dump_json())], "attachments": attachments or []}
    r = client.patch(f"/api/publish/drafts/{did}", headers=JSON, json=payload)
    assert r.status_code == 200, r.text
    return did


# ---------------------------------------------------------------------------
# T8 · 跨域一致性：前端拿到的读数与后端口径一致
# ---------------------------------------------------------------------------


class TestCounterContract:
    def test_frontend_uses_backend_count_not_own_implementation(self, client: TestClient) -> None:
        """★ SPEC-06 §2：前端只显示后端结果。这里锁住「后端给什么就是什么」。"""
        did = _seed_draft_with_variant(client, "dy", DY_OVER_TITLE, DY_OVER_TITLE, attachments=[VIDEO_DY])
        saved = client.get(f"/api/publish/drafts/{did}").json()
        v = saved["variants"][0]
        # variant.char_count 由后端 recount 算好，前端不再算一遍
        assert v["char_count"] == count_platform_chars(DY_OVER_TITLE, "dy")
        assert v["char_limit"] == 55
        assert v["over_limit"] is True

    def test_gate_and_precheck_share_one_counter(self) -> None:
        """★ 门禁与预检必须读出**同一个数字**，且只有一份实现。

        历史：门禁用「非空白字符数」、预检用「平台口径」，同一段文字
        门禁显示 36 / 预检显示 29，英文标题差 4.8 倍，且门禁会把 20 词的
        合法英文标题误判为超限而错误阻断。计数原语已下沉到
        ``gates/wordcount.py``，发布域经**模块转发**复用。

        这里锁两条不变量：①数值一致（含经 gates registry reload 之后仍一致）
        ②发布域不再自带第二份切分实现。
        """
        import importlib

        from atelier.server.gates import wordcount as gate
        from atelier.server.gates.wordcount import count_chars

        samples = [
            "我用 3 个 Agent 把内容流程砍掉一半，结果反而更慢了｜完整复盘 30 天实测",
            "This is an English title about AI workflow tools and efficiency",
            "出发 🇨🇳 加油 ❤️",
        ]
        for text in samples:
            assert gate.count_platform_chars(text, "dy") == count_platform_chars(text, "dy"), text
            assert count_chars(text) == count_platform_chars(text, "dy"), text

        # gates registry 会 importlib.reload 内置门禁；发布域必须自动跟随，
        # 不能因 from-import 绑死旧函数对象而静默漂移
        importlib.reload(gate)
        for text in samples:
            assert gate.count_platform_chars(text, "dy") == count_platform_chars(text, "dy"), (
                f"reload 后漂移：{text}"
            )

        # 结构不变量：切分原语只存在于地基层，发布域没有第二份
        assert not hasattr(wordcount, "_units_with_pos"), "发布域不应自带计数实现"
        assert not hasattr(wordcount, "_CJK_RANGES"), "发布域不应自带计数实现"

        # 英文按「词」计而不是按「字母」——这是旧口径会误杀的那一类
        english = "This is an English title about AI workflow tools and efficiency for creators"
        assert count_platform_chars(english, "dy") == 13
        assert count_platform_chars(english, "dy") <= 55, "20 词英文标题不该被判超抖音标题上限"
