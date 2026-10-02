"""技能资产层与能力地图域（SPEC-04）。

模块职责：
- ``loader``   扫描 ``atelier/skills/*/SKILL.md``（mtime 缓存）→ ``SkillMeta[]``
- ``manifest`` 解析 ``capabilities.toml`` → ``Capability[]``，自检死链
- ``runner``   就地运行（密钥检查 → 费用确认 → 脚本/AI → 门禁）
- ``executor`` 脚本沙箱（``shell=False``，超时 kill，stderr 8KB 摘要）
- ``keys``     密钥只写不回传（keychain，降级 ``var/secrets.enc``）
"""

from __future__ import annotations

__all__ = ["executor", "keys", "loader", "manifest", "runner"]
