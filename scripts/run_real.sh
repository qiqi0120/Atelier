#!/usr/bin/env bash
# 用真实模型起 Atelier（不设 ATELIER_MOCK）。
#
# 凭证从 ~/.claude/settings.json 的 env 段读取——那是本机已有的 Anthropic 兼容端点配置，
# 刻意不硬编码、不写进仓库、不打印到终端。
#
#   ./scripts/run_real.sh [端口]     默认 7300
#
# ⚠️ 当前这台机器配的是**智谱 GLM 的 Anthropic 兼容端点**（open.bigmodel.cn/api/anthropic，
#    模型 glm-5.3-flash），不是官方 Anthropic。管道是真的，模型不是 Claude。
#    换成官方 key 只需改 settings.json 里的 ANTHROPIC_BASE_URL / ANTHROPIC_MODEL。
set -euo pipefail

PORT="${1:-7300}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

if [ ! -f "$SETTINGS" ]; then
  echo "找不到 $SETTINGS" >&2
  exit 1
fi

# 用 python 读 JSON 并导出，避免 token 出现在 ps / 日志里
eval "$(python3 - "$SETTINGS" <<'PY'
import json, shlex, sys
env = json.load(open(sys.argv[1])).get("env", {})
for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"):
    v = env.get(k)
    if v:
        print(f"export {k}={shlex.quote(v)}")
# SDK 只读 ANTHROPIC_API_KEY，两者同源
if env.get("ANTHROPIC_AUTH_TOKEN"):
    print(f"export ANTHROPIC_API_KEY={shlex.quote(env['ANTHROPIC_AUTH_TOKEN'])}")
PY
)"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "settings.json 里没有 ANTHROPIC_AUTH_TOKEN，无法起真实模式" >&2
  exit 1
fi

unset ATELIER_MOCK   # 关键：必须清掉，否则还是走 MockHarness

echo "端点  : ${ANTHROPIC_BASE_URL:-（官方默认）}"
echo "模型  : ${ANTHROPIC_MODEL:-（服务端默认）}"
echo "密钥  : ${ANTHROPIC_API_KEY:0:6}…（${#ANTHROPIC_API_KEY} 字符，不显示全文）"
echo "地址  : http://127.0.0.1:${PORT}/"
echo
echo "注意：这是真实模型，每次对话都会计费。"
echo

cd "$ROOT"
exec .venv/bin/python -m atelier.cli.main web --port "$PORT"
