# SPEC-13 · 制作能力扩展（M3）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-03 |
| 范围 | SPEC-00 §3 M3 全量：F-F7~F15 视觉 · F-F18~F29 图像/音频 · F-F34~F50 视频/长内容（F-F15 公众号排版、F-F16 AI 生图已在库） |
| 形态 | **全部走技能资产注册表**（`atelier/skills/<id>/`，layer=制作），能力地图/技能库零前端改动自动出现 |
| 依据 | `prd/PRD-Atelier-v1.0.md` §9 · `plans/PLAN-M2.md` §4（M3 拆 3~4 小批的指示）· `specs/SPEC-04`（技能资产契约） |

## 0. 已确认决策

| # | 决策 |
|---|---|
| D1 | **诚实能力分层**，每个技能的 SKILL.md 如实声明成熟度与依赖，不装能：①**纯本地真做**（SVG/Pillow/markdown-it/标准库）②**依赖 ffmpeg**（视频/音频处理，运行时 `shutil.which` 检测，缺失给安装指引并明确失败）③**依赖云 API 密钥**（TTS/ASR，`required_keys` 机制，缺钥 409）④**v0 准备工具**（声音克隆/AI 音乐无标准供应商 API——只做需求单/素材检查，如实标注「未接入供应商」）⑤**纯 agent 技能**（翻译/剧本/大纲等文本任务，SKILL.md 即手册） |
| D2 | **视觉产出 = SVG（矢量）+ HTML 预览包装**（xhs-card 先例），不引渲染器：Pillow 不渲染 SVG，引 cairosvg 等超范围。库预览走 `<img>`（浏览器原生渲 SVG）与 sandbox HTML。PRD 的「GIF 动画信息图」降级为静态 + 分帧说明（如实标注） |
| D3 | **视觉质检两道**：①每个视觉 run.py 内置确定性 QC（尺寸/文本溢出/纯黑占比/元素密度），结果写进 result_markdown 的「视觉质检」段，不合格附重做参数建议；②新门禁 `visual_qc`（WARN，`gates/visual_qc.py` @register）对含 `<svg` 的文本做结构质检——挂 ai_flavor 同级（SPEC-00 §3 M3 前置说明）。BUILTIN_MODULES 追加一行视为「注册」（PLAN-M2 §3 表述），既有门禁文件零改动 |
| D4 | **不信任模型算数据**：图表/数据报告的统计由 run.py 从用户数据算出（AI 不参与数值）；图表技能接收结构化数据参数而非让 AI 编数 |
| D5 | 新增依赖仅 `pypdf>=4`（F-F45 论文解读的 PDF 文本抽取）；ffmpeg **不是** Python 依赖（运行时检测）；ASR/TTS 走 OpenAI 兼容接口约定（`TTS_API_KEY`/`ASR_API_KEY` + 可选 `TTS_BASE_URL`/`ASR_BASE_URL`，默认官方端点） |
| D6 | PRD 9.6「边缘密度/死白/密度」质检在 SVG 结构层近似实现（元素密度、大面积纯色、文字缺失）；位图层（PNG）用 Pillow 统计对比度/死白比例。质检是 WARN 不是 BLOCK——视觉不合格提示重做，不落盘拦截 |
| D7 | 技能 id 与目录名一致（kebab-case）；F-F35 与 F-F44 共享 `atelier/server/media/tools.py` 的高光找点函数，两技能各自出资产（对应 PRD 两个编号） |

## 1. 技能清单（37 项）

### 1.1 视觉（8 项，全部 run.py 本地真做）

| id | PRD | 说明 | 关键参数 |
|---|---|---|---|
| quote-card | F-F7 | 16:9 横版金句卡/数据卡（SVG+HTML 预览） | quote, attribution?, theme, dataset?(名值对→数据卡) |
| poster | F-F8 | 1080×1920 竖版营销海报（标题/卖点条/行动区版式） | title, subtitle, bullets, cta, theme |
| chart | F-F9 | 图表：柱/横条/折线/面积/饼/环/散点/雷达/漏斗 9 类（PRD 25+ 类如实标注先做 9 类） | type, series(JSON), title?, theme |
| infographic | F-F10 | 竖版信息长图（分节+图标位+数据高亮）；GIF 动画模式如实标注为分帧脚本说明 | title, sections(JSON: heading+points+metric?) |
| compare | F-F11 | A vs B 对比图（参数行对照 + 优劣势两栏） | left, right, rows(JSON), verdicts? |
| mindmap | F-F12 | Markdown 缩进大纲 → SVG 思维导图 + 可折叠 HTML | outline, theme |
| meme | F-F13 | 上下大字梗图（Pillow PNG；可给底图路径） | top_text, bottom_text, base_image?, theme |
| ecommerce-visual | F-F14 | 电商主图版式 ×3（卖点矩阵）+ 详情页视觉方案 markdown | product, selling_points, palette? |

### 1.2 图像处理（4 项，Pillow 真做；「AI 增强」如实标注为传统算法）

| id | PRD | 说明 |
|---|---|---|
| img-enhance | F-F18 | LANCZOS 放大 + 中值降噪 + UnsharpMask 锐化（notice：传统算法非 AI 超分） |
| img-resize | F-F19 | 改尺寸/中心裁剪/补边/转格式/压到目标 KB（质量二分） |
| img-decorate | F-F20 | 文字水印（平铺/单角）、圆角、多图纵向拼接 |
| chroma-key | F-F21 | 绿/蓝幕色距抠像 → 透明 PNG，可换纯色/图片背景 |

### 1.3 音频（8 项）

| id | PRD | 形态 |
|---|---|---|
| tts | F-F22 **P0** | run.py + `TTS_API_KEY`（OpenAI 兼容 `/audio/speech`）→ mp3 |
| asr | F-F23 **P0** | run.py + `ASR_API_KEY`（whisper 兼容 `/audio/transcriptions`，verbose_json）→ txt/srt/json |
| multi-voice | F-F24 | run.py + `TTS_API_KEY`：按角色音色逐段合成；wav 用标准库拼接，mp3 拼接注明需 ffmpeg（缺失给分段产物） |
| voice-clone | F-F25 | **v0 准备工具**：参考音频检查（wav 时长/声道/大小）+ 音色需求单；未接入克隆供应商（如实标注） |
| ai-music | F-F26 | **v0 准备工具**：生成 BGM 需求单（风格/结构/时长/参考），供外部音乐工具使用；未接入供应商 |
| audio-denoise | F-F27 | run.py + ffmpeg（afftdn 降噪链）；ffmpeg 缺失 → 明确失败 |
| audio-mix | F-F28 | run.py + ffmpeg（amix 混音 + 背景音量/闪避简化参数） |
| audio-visualize | F-F29 | run.py + ffmpeg（showwavespic 波形 PNG；视频模式标注需 ffmpeg 全功能） |

### 1.4 视频（10 项；除注明外 run.py + ffmpeg，缺失明确失败并给安装指引）

| id | PRD | 说明 |
|---|---|---|
| sub-trans | F-F34 | agent 技能：SRT 双语/纯译文（如实标注 ≤200 条/次，更长分段） |
| clip-cut | F-F35 | 切片：mode=points（给时间点）\|energy（ffmpeg silencedetect 反向找高能段） |
| aspect-crop | F-F36 | 16:9↔9:16：中心裁剪或模糊垫底 |
| album-video | F-F37 | 图片序列 + zoompan Ken Burns + concat，可挂 BGM |
| beat-cut | F-F38 | 按 BPM 网格踩点切片（notice：真实节拍检测需外部工具，本技能按给定 BPM 均分） |
| intro-outro | F-F39 | Pillow 画片头/片尾卡 → ffmpeg 拼进视频头尾 |
| video-chapters | F-F40 | agent 技能：粘贴转录文本 → 章节时间戳目录 |
| ai-drama | F-F42 | agent 技能：剧集圣经/分集剧本/分镜表；出片部分指向 aigc-image/one-video/tts 组合 |
| video-to-article | F-F43 | agent 技能：转录文本 → 图文文章 + 章节目录 |
| live-highlights | F-F44 | run.py + ffmpeg：直播录像按能量+最短时长切高光 |

### 1.5 长内容（7 项）

| id | PRD | 形态 |
|---|---|---|
| pdf-extract | F-F45 前置 | run.py + pypdf：PDF → 文本落盘（页码标记），供 paper-read 供料 |
| paper-read | F-F45 | agent 技能：论文文本 → 解读（问题/方法/结论/局限/对我们有用什么） |
| novel-writer | F-F46 | agent 技能：世界观/人设/三级大纲 → 逐章正文（先圣经后章节，防吃设定） |
| longform-outline | F-F47 | agent 技能：H2/H3 大纲 + 字数分配 + 图表位 + FAQ |
| framework | F-F48 | agent 技能：PAS/AIDA/BAB/STAR/SLAY 五框架结构化成文 |
| data-report | F-F49 | run.py：CSV/JSON → 统计表（count/mean/min/max/分布）+ SVG 柱/线图 + Markdown 报告（洞察留给对话，不编） |
| doc-convert | F-F50 | run.py：MD → 自包含 HTML（markdown-it-py + 内联样式）；PDF/长图需浏览器渲染引擎，如实标注「输出可打印 HTML」 |

## 2. 共享代码（新文件，业务库代码非技能资产）

- `atelier/server/visual/svgkit.py`：XML 转义、svg 头尾、CJK 换行、色板、slug、SVG 结构 QC、`ATELIER_RESULT` emit、参数解析（run.py 复用；**技能脚本 import 本仓库包**——runner 以 `sys.executable` 在包环境内执行，合法）
- `atelier/server/media/tools.py`：ffmpeg/ffprobe 检测与调用（shell=False、超时）、probe 元数据、SRT 解析/组装、时间戳换算、wav 信息
- `atelier/server/gates/visual_qc.py`：WARN 门禁（§0 D3）

## 3. API / 前端

**零新端点、零前端改动**：技能由既有 `/skills` 与能力地图（F-C6 五层分区/F-C8 就地运行/F-C9 密钥表单/F-C10 缺钥标记）自动承载。`outputs` 声明使用既有 kind（image/html/audio/video/markdown/json），内容库预览已支持。

## 4. 验收标准

1. 金句卡/海报/图表/对比图/导图等信息图技能：粘贴内容 → 落盘 SVG+HTML，库内可预览，QC 段如实给出尺寸/密度检查结果
2. 图像四技能对本机图片真处理（Pillow），产物可预览；参数非法给明确报错
3. TTS/ASR 未配密钥时运行按钮禁用（409 写明缺哪个 key）；voice-clone/ai-music 如实标注 v0「未接入供应商」
4. ffmpeg 技能在本机无 ffmpeg 时明确报「需要 ffmpeg + 安装指引」，不是含糊 500
5. agent 技能（翻译/章节/剧本/大纲等）走 harness 时手册可执行、有输入校验意识（反问不瞎编）
6. data-report 统计数字与输入数据一致（代码算，不是 AI 编）
7. 全部新技能被 loader 正常装载（frontmatter 10 字段齐、id=目录名），能力地图「制作」层可见

## 5. 必测清单（`atelier/tests/test_m3_skills.py`）

- 装载：遍历 M3 新技能 → `loader.scan()` 全部合法、layer=制作、id=目录名
- 视觉：quote-card/chart/mindmap/compare 冒烟（真实执行 run.py）→ artifacts 含 svg+html、QC 段存在；chart 非法 type → 退出码 2 + stderr 明确；visual_qc 门禁：正常 SVG pass、无文本/超小 viewBox WARN
- 图像：img-resize 压缩到目标 KB 真降质量、img-decorate 拼接尺寸正确、chroma-key 绿幕像素变透明（构造测试图断言 alpha）
- 音频：tts/asr 无 key → 409（runner 前置， fake PATH 注入假 ffmpeg 后测其余）；audio-denoise 用**假 ffmpeg 脚本**（PATH 注入）测参数拼装与产物回传；无 ffmpeg → 退出码 2 + 「brew install ffmpeg」提示
- 视频：aspect-crop/clip-cut 假 ffmpeg 测命令拼装（断言关键滤镜/参数）；假 ffprobe 返回时长 JSON
- 长内容：pdf-extract 用 pypdf 生成物 roundtrip（构造 PDF→抽取文本）；data-report CSV→统计数与 SVG 图元断言；doc-convert MD→HTML 含标题/表格
- 回归：`loader.scan()` 无新增 SkillIssue；doctor 不因新技能变红

## 6. 偏差与待办登记

- F-F17 智能抠图（P0）不在 SPEC-00 M3 清单且需语义分割模型——绿幕场景由 F-F21 chroma-key 覆盖，通用抠图登记为「待接入本地分割模型」（与 F-I5 本地 Agent 同批评估）
- F-F30/F-F31/F-F32/F-F33（AI 视频生成/一键成片/自然语言剪辑/自动字幕）不在 M3：前两者已由 aigc-image/one-video 承载核心路径，后两者依赖 ASR（asr 技能本批交付后组合可用）
- PRD F-F9「25+ 图表类型」本批 9 类，其余登记按需增量（不虚标数量）
- F-F10 动画 GIF、F-F38 真实节拍检测、F-F50 PDF 输出：依赖项超范围，如实降级并标注（D2/D1④）
