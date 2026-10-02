---
id: wechat-layout
name: 公众号排版
layer: 制作
maturity: v0
trigger: 当你说「排个版」「贴到公众号会掉样式」「转成内联样式」时使用
cost: 本地 · 免费
required_keys: []
params:
  - {key: markdown, label: Markdown 正文, default: ""}
  - {key: theme, label: 主题, default: "default"}
  - {key: inline_css, label: 强制内联样式, default: "true"}
outputs: [html]
paid: false
---

# 公众号排版

Markdown → **内联样式 HTML**。公众号编辑器会剥掉 `<style>` 和大部分 class，
所以**必须内联**，否则贴进去就是一堆裸标签。

## 为什么必须内联

| 写法 | 公众号表现 |
|---|---|
| `<style>.x{color:red}</style><p class="x">` | 样式全丢，红色没了 |
| `<p style="...">...</p>` | ✅ 正常显示 |

本技能**永远输出内联样式**，即使传 `inline_css=false` 也会警告。

## 主题

| theme | 特点 |
|---|---|
| `default` | 正文 16px / 行高 1.75 / 段间距 1em，微信默认灰 |
| `clean` | 无首行缩进，适合技术文 |
| `warm` | 深棕正文 + 米色引用块，适合随笔 |

## 执行

```bash
python atelier/skills/wechat-layout/run.py \
  --params '{"markdown":"# 标题\n\n正文…","theme":"clean"}' \
  --out outputs/<项目>/成品/wechat-layout
```

支持：标题 h1–h4、段落、**/加粗**、`*斜体*`、无序/有序列表、引用 `>`、
分割线 `---`、代码块 ```、超链接、行内 `code`。

不支持（**必须显式转成图片或纯文本**，不要静默丢弃）：表格、脚注、HTML 原样嵌入、
行内公式。遇到时在产物里列出 `## 未支持语法`，让人来决定怎么办。

## 门禁要求

- `wordcount`（BLOCK）：公众号上限 20000 字
- `compliance`（BLOCK）：极限词
- `secret_scan`（BLOCK）：**特别注意**——排版时别把 `.env` 内容贴进正文

## 落盘

- 路径：`<项目>/成品/wechat-layout/<slug>.html`（可直接复制粘贴进公众号）
- 附 `<slug>.md` 原文，方便比对

## 失败处理

| 情况 | 处理 |
|---|---|
| 含未支持语法 | **不报错**，但产物必须列出「未支持语法」清单（PRD 原则四：失败留痕） |
| Markdown 解析异常 | 抛 `ValidationError` 并指出行号 |
| 正文为空 | 回问，不产出空文件 |
