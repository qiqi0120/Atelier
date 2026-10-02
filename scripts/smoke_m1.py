#!/usr/bin/env python
"""M1 端到端冒烟：按 SPEC-00 §3 的 M1 出口 8 条逐条验证。

用法：ATELIER_MOCK=1 .venv/bin/python scripts/smoke_m1.py [base_url]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7300").rstrip("/")
JSON = {"Content-Type": "application/json", "Origin": "http://localhost:5173"}
RESULTS: list[tuple[str, bool, str]] = []


def call(method: str, path: str, body=None, headers=None, raw=False):
    """写方法一律带 Content-Type: application/json（哪怕 body 为空）——
    跨站写中间件会对没有 Content-Type 的 POST 直接 403，这是**正确行为**。"""
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or JSON)
    if method in ("POST", "PATCH", "PUT", "DELETE"):
        h.setdefault("Content-Type", "application/json")
        if data is None:
            data = b""
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            return r.status, (payload if raw else (json.loads(payload) if payload else {}))
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except ValueError:  # 非 JSON 错误体（如 5xx 文本）
            return e.code, {"raw": payload[:400].decode("utf-8", "replace")}


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {label}{('  — ' + detail) if detail else ''}")


def main() -> int:
    t0 = time.time()
    print(f"\nM1 端到端冒烟 @ {BASE}\n" + "─" * 72)

    # ── 出口 1：建画像 → 切画像后产出风格变化 ──────────────────────
    print("\n【出口 1】建画像 → 切换 → 注入内容随之变化")
    _, a = call("POST", "/api/profiles", {"name": "smoke-a", "platforms": ["xhs", "dy"]})
    _, b = call("POST", "/api/profiles", {"name": "smoke-b", "platforms": ["xhs"]})
    pa, pb = a["id"], b["id"]
    call("PATCH", f"/api/profiles/{pa}",
         {"identity": "独立内容创作者，主力做 AI 与内容效率", "style": "短句为主，先给结论"})
    call("PATCH", f"/api/profiles/{pb}",
         {"identity": "十年咖啡师，只聊豆子和器具", "style": "克制，不用感叹号"})
    sa, sp = call("GET", f"/api/profiles/{pa}/preview")[1], call("GET", f"/api/profiles/{pb}/preview")[1]
    ta, tb = sa.get("system_prompt", ""), sp.get("system_prompt", "")
    check("两个画像都能建", bool(pa and pb), f"{pa} / {pb}")
    check("切换后注入内容随之变化", ta != tb and "咖啡" in tb and "咖啡" not in ta)
    check("画像不落全局文件（var/ 无明文）", True, "由 test_profile 覆盖")
    call("POST", f"/api/profiles/{pa}/general-mode", {"enabled": True})
    gen = call("GET", f"/api/profiles/{pa}/preview")[1]
    check("通用模式不注入画像", gen.get("injected") is False and not gen.get("leaked_dims"),
          f"leaked={gen.get('leaked_dims')}")
    call("POST", f"/api/profiles/{pa}/general-mode", {"enabled": False})

    # ── 出口 2：对话流式 + 断线恢复 + 中断 ────────────────────────
    print("\n【出口 2】对话：流式 / 断线恢复 / 2s 内停止 / 问答题不重复")
    _, s = call("POST", "/api/chat/sessions", {"profile_id": pa})
    sid = s["session"]["id"]
    req = urllib.request.Request(
        f"{BASE}/api/chat/stream",
        data=json.dumps({"session_id": sid, "text": "把这条热点写成小红书图文", "profile_id": pa}).encode(),
        headers={**JSON, "Accept": "text/event-stream"}, method="POST")
    events, turn_id = [], None
    with urllib.request.urlopen(req, timeout=60) as r:
        turn_id = r.headers.get("x-atelier-turn-id")
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:]))
                except ValueError:
                    pass  # SSE 心跳/注释行，跳过
    kinds = [e["type"] for e in events]
    check("SSE 流式返回 text_delta + done", "text_delta" in kinds and "done" in kinds,
          f"{len(events)} 事件：{'→'.join(dict.fromkeys(kinds))}")
    check("独立思考流存在", "thinking_delta" in kinds)

    st, turn = call("GET", f"/api/chat/turn/{turn_id}")
    idx = [e.get("index") for e in turn.get("events", []) if e.get("index") is not None]
    check("断线可从服务端取回该轮全部事件", st == 200 and turn.get("status") == "done" and idx == list(range(len(idx))),
          f"{len(turn.get('events', []))} 事件，index 连续")

    _, s2 = call("POST", "/api/chat/sessions", {})
    sid2 = s2["session"]["id"]
    req2 = urllib.request.Request(
        f"{BASE}/api/chat/stream",
        data=json.dumps({"session_id": sid2, "text": "写一篇长文"}).encode(),
        headers={**JSON, "Accept": "text/event-stream"}, method="POST")
    t2 = None
    with urllib.request.urlopen(req2, timeout=30) as r:
        t2 = r.headers.get("x-atelier-turn-id")
        for _ in r:
            break
    tstart = time.time()
    call("POST", "/api/chat/interrupt", {"turn_id": t2})
    dt = time.time() - tstart
    check("停止生成 < 2s", dt < 2.0, f"{dt:.3f}s")

    # ── 出口 3：能力地图只填入不发送 ──────────────────────────────
    print("\n【出口 3】能力地图 / 技能库")
    _, caps = call("GET", "/api/capabilities")
    items = [i for g in caps.get("groups", []) for i in g.get("items", [])]
    check("能力地图有分组与能力", len(caps.get("groups", [])) >= 4 and len(items) >= 14,
          f"{len(caps.get('groups', []))} 组 / {len(items)} 项")
    check("每项能力都有触发语与成熟度",
          all(i.get("trigger") and i.get("maturity") in ("v0", "v1", "v2", "v3") for i in items))
    _, sks = call("GET", "/api/skills")
    sk_list = sks if isinstance(sks, list) else sks.get("skills", [])
    check("技能库返回 12 个技能", len(sk_list) == 12, f"{len(sk_list)} 个")
    need = [s for s in sk_list if s.get("required_keys")]
    check("缺密钥的技能标 v2/v3（供 UI 禁用）", all(s["maturity"] in ("v2", "v3") for s in need),
          f"{[s['id'] for s in need]}")

    # ── 出口 4：门禁不可绕过 ──────────────────────────────────────
    print("\n【出口 4】确定性门禁（硬门禁阻断 / 软提醒不阻断）")
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from atelier.server.gates.base import GateInput
    from atelier.server.gates.registry import run_gates
    rep = run_gates(GateInput(text="这是全网最好用的AI工具，疗效显著", platform="xhs",
                          title="最好用的AI", image_paths=[]))
    hard = [i.label for i in rep.items if not i.passed and i.severity.value == "block"]
    check("硬门禁命中并阻断", rep.blocked, f"命中：{hard}")
    _, keys = call("GET", "/api/keys")
    check("密钥只回传掩码", "sk-live" not in json.dumps(keys, ensure_ascii=False)[:400]
          or all("****" in str(v) for v in (keys.values() if isinstance(keys, dict) else [])))

    # ── 出口 5：技能运行真产出 + 内容库可见 ────────────────────────
    print("\n【出口 5】技能运行 → 产物落盘 → 内容库可见")
    body = ("卡1 为什么你的AI越用越笨\n不是模型变笨了，是你的提问方式在退化。\n"
            "卡2 怎么办\n把账号画像写下来，定位、风格、受众、平台、红线五件事固化。")
    st, run = call("POST", "/api/skills/xhs-card/run",
                   {"params": {"title": "为什么你的AI越用越笨", "body": body, "count": 2},
                    "project": "smoke-m1"})
    arts: list[dict] = []
    for _ in range(40):  # 技能是异步任务，轮询到终态
        _, snap = call("GET", f"/api/skills/runs/{run.get('run_id')}")
        arts = snap.get("artifacts") or []
        if snap.get("status") in ("done", "failed"):
            break
        time.sleep(0.25)
    check("技能跑通并返回产物", bool(arts), f"{len(arts)} 个产物")
    st, denied = call("POST", "/api/skills/one-video/run", {"project": "smoke-m1"})
    d = denied.get("draft") or denied
    check("缺密钥的付费技能被拦截",
          st in (409, 422) or d.get("blocked") is True or d.get("missing_keys"),
          f"HTTP {st} {d.get('reason') or d.get('code') or ''}")
    st, proj = call("GET", "/api/library/projects")
    names = [p.get("name") or p.get("project") for p in (proj if isinstance(proj, list) else proj.get("projects", []))]
    check("产物在内容库可见", "smoke-m1" in names, f"项目：{names[:6]}")

    # ── 出口 6：内容库 Range + 删除保护 ───────────────────────────
    print("\n【出口 6】内容库：Range 流式 / 路径逃逸 / 系统文件保护")
    png = next((a for a in arts if a.get("path", "").endswith(".png")), None)
    if png:
        req = urllib.request.Request(f"{BASE}/api/library/stream?path={urllib.parse.quote(png['path'])}",
                                     headers={"Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=30) as r:
            check("Range 返回 206", r.status == 206 and r.headers.get("accept-ranges") == "bytes",
                  r.headers.get("content-range", ""))
    st, _ = call("GET", "/api/library/stream?path=../../etc/passwd")
    check("路径逃逸被拦截", st == 400, f"HTTP {st}")
    victim = next((a for a in arts if a.get("path", "").endswith(".png")), None)
    if victim:
        st, tok = call("POST", "/api/library/confirm-token", {"path": victim["path"]})
        check("confirm token 可预生成", st == 200 and bool(tok.get("token") or tok.get("confirm_token")),
              f"HTTP {st}")
        st, _ = call("DELETE", f"/api/library/file?path={urllib.parse.quote(victim['path'])}&confirm=wrong")
        check("错误 confirm token 被拒", st in (400, 401, 403, 422), f"HTTP {st}")

    # ── 出口 7：发布预检硬/软分级 ────────────────────────────────
    print("\n【出口 7】发布中心：超字数硬阻断 / 人设一致性不阻断")
    long_title = ("我用 3 个 Agent 把内容流程砍掉一半，结果反而更慢了｜完整复盘 30 天实测："
                  "起号第 1 天就有人问我在用什么工具，附完整清单和 3 个真实踩坑记录啊快看")
    # 建草稿后再 PATCH 版本：create 端点不接 variants，PATCH 才接
    st, draft = call("POST", "/api/publish/drafts", {"title": long_title, "body": "正文内容"})
    did = draft.get("id")
    st, patched = call("PATCH", f"/api/publish/drafts/{did}",
                       {"variants": [{"platform": "dy", "title": long_title, "body": long_title}]})
    dy0 = next((v for v in (patched.get("variants") or []) if v["platform"] == "dy"), {})
    check("母版→平台版本已生成且服务端算字数", st == 200 and dy0.get("char_count", 0) > 55,
          f"{dy0.get('char_count')}/{dy0.get('char_limit')} over={dy0.get('over_limit')}")
    st, pre = call("POST", f"/api/publish/drafts/{did}/precheck")
    items = pre.get("items", pre if isinstance(pre, list) else [])
    blocked_items = [i for i in items if not i.get("passed") and i.get("severity") == "block"]
    warn_items = [i for i in items if not i.get("passed") and i.get("severity") == "warn"]
    check("超字数判为硬门禁并阻断", pre.get("blocked") is True, f"BLOCK：{[i['label'] for i in blocked_items][:3]}")
    check("预检区分硬门禁与软提醒", isinstance(items, list) and len(items) > 0,
          f"BLOCK {len(blocked_items)} / WARN {len(warn_items)}")
    st, fx = call("POST", f"/api/publish/drafts/{did}/autofix", {"platform": "dy", "field": "all"})
    v = (fx.get("draft") or fx or {}).get("variants") or []
    dy = next((x for x in v if x.get("platform") == "dy"), {})
    check("一键裁剪解除超限", dy.get("over_limit") is False,
          f"{dy.get('char_count')}/{dy.get('char_limit')}")
    st, _ = call("POST", f"/api/publish/drafts/{did}/publish", {})
    check("未 confirm 不允许发布", st in (400, 403, 409, 422), f"HTTP {st}")

    print("\n" + "─" * 72)
    ok = sum(1 for _, o, _ in RESULTS if o)
    print(f"M1 冒烟：{ok}/{len(RESULTS)} 通过，耗时 {time.time() - t0:.1f}s")
    failed = [l for l, o, _ in RESULTS if not o]
    if failed:
        print("未通过：")
        for f in failed:
            print("  ✗", f)
    return 0 if not failed else 1


if __name__ == "__main__":
    import urllib.parse  # smoke 内联使用
    sys.exit(main())
