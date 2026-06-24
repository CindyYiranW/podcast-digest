本文档是「AI 播客摘要系统 MVP」的技术需求说明书。本项目没有专职工程师，由 **Cindy（零编程背景、初次使用终端）本人端到端完成，全程使用 Claude Code 作为编程助手**。因此本文档既是需求说明，也是 Cindy 与 Claude Code 协作时的「任务清单 + 上下文」：你可以把每一节内容直接发给 Claude Code，让它帮你写代码、解释报错、一步步带你跑通。

## 0. 写在前面：给 Cindy 的使用说明

你不需要会写代码。你要做的是**当好"产品负责人"**——把需求讲清楚，让 Claude Code 当你的工程师。下面是贯穿全程的协作方式：

<callout icon="bulb" bgc="4">  
**和 Claude Code 协作的黄金三句话**  
1. 「请帮我完成第 X 节的功能，我没有编程背景，请一步步告诉我每条命令在终端里怎么敲。」  
2. 「这是我遇到的报错：（把整段报错复制粘贴给它），请解释原因并给我修复办法。」  
3. 「请逐行解释你刚才让我运行的命令是做什么的，确认安全后我再执行。」  
</callout>

**终端是什么？** 终端（Terminal）就是一个可以输入文字命令让电脑干活的黑窗口。Mac 上叫「终端 / Terminal」。你只需要"复制 Claude Code 给的命令 → 粘贴到终端 → 回车"。遇到任何不懂的，直接把屏幕内容贴回给 Claude Code 问它。

**唯一的参考资料**：本项目的需求来源与架构思路，参考团队已有的这份飞书 PRD 文档——[团队 AI 信息系统 PRD（飞书文档）](https://bytedance.larkoffice.com/docx/LybjdtaOsoMol5xjKJCcVXIfnCd)。本项目在它的架构思路上做裁剪定制（见第 2.3 节）。

---

## 1. 项目概述（可直接发给 Claude Code 当 Context）

我们要构建一个**播客自动摘要系统**，定位为「PGC + 短剧经营分析」团队（圣何塞）的情报雷达。系统每周（或每两周）自动抓取若干指定播客的 RSS Feed，**只读取 Show Notes 文字内容（不做音频转写）**，先用低成本 LLM 做相关性初筛与打标签，再用高质量 LLM 对保留下来的内容做深度分析，最终把一份中文为主的结构化情报报告写入飞书文档。整个流程通过 GitHub Actions 定时触发，无需人工干预。

项目在团队已有的 [AI 信息系统 PRD（飞书文档）](https://bytedance.larkoffice.com/docx/LybjdtaOsoMol5xjKJCcVXIfnCd) 所描述的架构思路基础上做定制裁剪：**只保留播客 RSS 信息源、内容形式改为 Show Notes 文字、时间窗口放宽到 7–14 天、输出频率降为每周/每两周、筛选视角切换为 PGC/短剧/AI 内容行业**。

<callout icon="bulb" bgc="3">  
**MVP 第一目标**：跑通「抓 3 个播客 → 初筛 → 深度分析 → 写入 1 篇飞书文档」的完整链路。先保证端到端能跑、能产出可读报告，再优化筛选精度与成本。  
</callout>

---

## 2. 技术栈与整体架构

### 2.1 技术栈选型（已确定）

<table header-row="true" col-widths="180,260,360">  
<tr><td>类别</td><td>选型</td><td>说明</td></tr>  
<tr><td>代码托管</td><td>GitHub</td><td>私有仓库，存放代码 + 管理运行密钥（Secrets）</td></tr>  
<tr><td>编程助手</td><td>Claude Code</td><td>你的"工程师"，负责写代码、解释命令、修报错</td></tr>  
<tr><td>运行语言</td><td>Python 3.11+</td><td>生态成熟，Claude Code 最擅长；你不需要懂语法</td></tr>  
<tr><td>定时任务</td><td>GitHub Actions</td><td>免费额度足够；每周或每两周自动运行</td></tr>  
<tr><td>初筛模型</td><td>低成本模型（doubao / GPT-4o-mini）</td><td>批量相关性判断 + 打标签，控成本</td></tr>  
<tr><td>深度分析模型</td><td>高质量模型（Claude Sonnet / doubao-seed）</td><td>跨集综合洞察，重质量</td></tr>  
<tr><td>输出目标</td><td>飞书文档（Feishu/Lark Doc）</td><td>通过飞书开放平台 API 写入</td></tr>  
</table>

### 2.2 数据流

整体数据流为单向流水线，每一步的输出是下一步的输入：

```text
[1] RSS 抓取
      ↓  拉取每个播客最近 7–14 天的 episode 列表
[2] Show Notes 解析
      ↓  从每条 episode 提取标题/嘉宾/链接/Show Notes 正文文字
[3] LLM 初筛（低成本模型）
      ↓  相关性判断 + 打标签 + 去重合并，过滤掉不相关 episode
[4] LLM 深度分析（高质量模型）
      ↓  逐集提炼关键论点 + 跨集综合洞察
[5] 飞书写入
      ↓  按格式生成报告，写入飞书文档（最新在最上方）
```

### 2.3 与参考 PRD 的关键差异

本项目参考 [团队 AI 信息系统 PRD（飞书文档）](https://bytedance.larkoffice.com/docx/LybjdtaOsoMol5xjKJCcVXIfnCd) 的架构思路，并做如下裁剪：

<table header-row="true" col-widths="150,330,330">  
<tr><td>维度</td><td>参考 PRD（团队信息系统）</td><td>本项目（播客摘要）</td></tr>  
<tr><td>信息源</td><td>微信公众号 + 即刻 + TechCrunch 等多源</td><td>仅播客 RSS（3 个）</td></tr>  
<tr><td>内容形式</td><td>文章正文 / 音频转写</td><td>Show Notes 文字（不做音频转写）</td></tr>  
<tr><td>时间窗口</td><td>过去 1 天</td><td>过去 7–14 天</td></tr>  
<tr><td>输出频率</td><td>每天</td><td>每周一次或每两周一次</td></tr>  
<tr><td>筛选视角</td><td>今日头条 / 番茄小说视角</td><td>PGC / 短剧 / AI 内容行业视角</td></tr>  
</table>

---

## 3. 目录结构建议

下面是建议的仓库结构。你不用手动建这些文件夹——直接把这一节发给 Claude Code，让它帮你一次性创建好整个项目骨架。

```text
podcast-digest/
├── .github/
│   └── workflows/
│       └── weekly_digest.yml      # GitHub Actions 定时配置
├── config/
│   ├── sources.yaml               # 播客信息源配置（RSS 地址、语言、频率）
│   └── filters.yaml               # 筛选标准（相关话题/竞品公司/排除项）
├── src/
│   ├── __init__.py
│   ├── main.py                    # 入口：串联整条流水线
│   ├── fetch/
│   │   ├── __init__.py
│   │   └── rss_fetcher.py         # RSS 抓取模块
│   ├── parse/
│   │   ├── __init__.py
│   │   └── shownotes_parser.py    # Show Notes 解析模块
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py              # LLM 调用封装（多模型路由）
│   │   ├── screening.py           # 初筛模块
│   │   └── analysis.py            # 深度分析模块
│   ├── output/
│   │   ├── __init__.py
│   │   └── feishu_writer.py       # 飞书写入模块
│   ├── prompts/
│   │   ├── screening_prompt.txt   # 初筛 Prompt 模板
│   │   └── analysis_prompt.txt    # 深度分析 Prompt 模板
│   └── utils/
│       ├── __init__.py
│       ├── config.py              # 读取 config/*.yaml 与环境变量
│       ├── dedup.py               # 去重/合并逻辑
│       └── logger.py              # 日志
├── data/
│   └── cache/                     # 已处理 episode 的缓存（避免重复处理）
├── tests/
│   ├── test_rss_fetcher.py
│   ├── test_shownotes_parser.py
│   └── test_screening.py
├── .env.example                   # 环境变量示例（不含真实密钥）
├── .gitignore
├── requirements.txt               # Python 依赖
├── README.md                      # 项目说明 + 本地运行步骤
└── HANDOVER.md                    # 交接手册（见第 9 章模板）
```

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：对它说「请按这个目录结构帮我创建一个新项目 podcast-digest，先把所有文件夹和空文件建好，并初始化 git 仓库；每一步请告诉我要在终端里运行什么命令。」  
</callout>

---

## 4. 各模块功能说明

每个模块下都有一段「💡 如何用 Claude Code 完成这一步」，照着把话发给它即可。建议**一个模块一个模块地做**，每做完一个就让它帮你运行测试一下。

### 4.1 RSS 抓取模块（`src/fetch/rss_fetcher.py`）

**职责**：根据 `config/sources.yaml` 中的播客列表，拉取每个播客的 RSS Feed，筛出「发布时间在过去 N 天（默认 7–14 天，可配置）」的 episode。

**输入**：`sources.yaml` 中的 RSS URL 列表、时间窗口参数。
**输出**：标准化的 episode 对象列表，每条包含：`source_name`（播客名）、`episode_title`、`published_at`、`audio_url` / `episode_link`（原集链接）、`raw_description`（RSS 中的 description/content 字段，通常就是 Show Notes 原文）、`guests`（如能从字段解析）。

**实现要点**：
- 用 `feedparser` 库解析 RSS，兼容不同播客平台的字段差异。
- 时间过滤：用 `published_parsed` 与当前时间比较，保留窗口内 episode。
- 三个信息源的接入方式见第 5 章。
- 网络请求需带超时与重试（建议 `requests` + 重试 3 次）。

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：对它说「请帮我写 `src/fetch/rss_fetcher.py`，用 feedparser 读取 sources.yaml 里的播客 RSS，只保留最近 14 天的 episode，输出上面这些字段。写完后给我一条命令，先只跑一个播客并把结果打印出来，让我确认能抓到内容。」  
</callout>

### 4.2 Show Notes 解析模块（`src/parse/shownotes_parser.py`）

**职责**：把每条 episode 的 Show Notes 清洗成干净的纯文本，供 LLM 使用。RSS 的 `description`/`content` 字段常含 HTML 标签、广告、时间轴等噪声。

**输入**：episode 对象（含 `raw_description`）。
**输出**：在 episode 对象上补充 `clean_shownotes`（纯文本）、`timeline`（如能解析出时间轴）、`guests`（如 Show Notes 中能补充嘉宾信息）。

**实现要点**：
- 用 `BeautifulSoup` 去除 HTML 标签，保留段落结构。
- 去除常见噪声：赞助广告段落、订阅引导、纯链接行。
- 中文播客（硅谷101）与英文播客分别处理，但产出统一结构。
- 若某 episode 的 Show Notes 过短（如 < 100 字），标记为 `low_content`，交给初筛模块决定是否丢弃。

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：对它说「请帮我写 Show Notes 清洗模块，把 RSS 里带 HTML 的简介去掉标签和广告，变成干净文字。用上一步抓到的真实数据测试，把清洗前后的对比打印给我看。」  
</callout>

### 4.3 LLM 初筛模块（`src/llm/screening.py`）

**职责**：用**低成本模型**对每条 episode 做相关性判断、打标签、并对内容高度重复的 episode 做合并。这是控制成本与噪声的关键关卡。

**输入**：清洗后的 episode 列表（`clean_shownotes`）、`config/filters.yaml`。
**输出**：每条 episode 附加 `is_relevant`（bool）、`relevance_score`（0–10）、`tags`（命中的相关话题/竞品标签）、`reason`（简短判断理由）。只有 `is_relevant=true` 的进入深度分析。

**初筛 Prompt 草稿**（存于 `src/prompts/screening_prompt.txt`）：

```text
你是「PGC + 短剧经营分析」团队的情报筛选助手。下面是一集播客的 Show Notes 内容。
请判断它是否与我们团队关注的方向相关，并打分、打标签。

【我们关注的相关话题（命中任一即相关）】
- 短剧出海 / short drama / webtoon / interactive drama
- AI 生成内容 / AIGC / AI-generated content
- PGC 商业化 / creator monetization
- 达人/创作者生态 / creator economy
- AI 音乐 / AI in music
- 流媒体竞争 / streaming / Netflix / YouTube / TikTok / Meta
- Meta 作者变现策略、YouTube AI 工具
- 短视频行业竞争格局、影视内容宣推 / 体育内容

【相关竞品公司（出现即视为高相关，relevance_score >= 7）】
- 海外：Meta（Instagram、Reels）、Google（YouTube）、Netflix、Spotify、TikTok
- 国内：爱奇艺、优酷、腾讯视频、小红书、B站
- AI 公司：OpenAI、Anthropic、Google DeepMind

【明确不相关（判为不相关，is_relevant=false）】
- 纯娱乐八卦、纯个人成长/职业心得、纯技术硬核（芯片/算法底层）
- 纯财经/宏观经济、机器人/具身智能、医疗/教育/法律 AI 应用

【输出要求】严格输出 JSON：
{
  "is_relevant": true/false,
  "relevance_score": 0-10 的整数,
  "tags": ["命中的话题或公司标签"],
  "reason": "一句话说明判断理由（中文）"
}

【待判断的 Show Notes】
播客名称：{source_name}
集名：{episode_title}
内容：
{clean_shownotes}
```

**合并/去重逻辑**（`src/utils/dedup.py`）：当多集 episode 标签高度重合且主题相近时，标记为同一主题簇，深度分析时合并讨论，避免报告冗余。

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：对它说「请帮我写初筛模块，调用低成本模型（用环境变量里的 API Key），把上面的 Prompt 套到每条 episode 上，返回 JSON。先用 2–3 条真实数据测试，把模型判断结果打印出来给我看看准不准。如果调用 API 报错，请告诉我是不是 Key 没配好、该怎么配。」  
</callout>

### 4.4 LLM 深度分析模块（`src/llm/analysis.py`）

**职责**：用**高质量模型**对初筛保留的 episode 做两层分析——逐集提炼关键论点，以及跨集综合洞察（本期核心判断）。

**输入**：`is_relevant=true` 的 episode 列表（含 tags、clean_shownotes）。
**输出**：
- 逐集：`key_points`（3–5 条关键论点，中文）、`summary`（一句话集摘要）。
- 整体：`cross_episode_insight`（跨播客综合洞察，本期核心判断）。

**深度分析 Prompt 草稿**（存于 `src/prompts/analysis_prompt.txt`）：

```text
你是「PGC + 短剧经营分析」团队的资深内容情报分析师。下面是本期筛选保留的若干集播客的 Show Notes。
请产出一份给业务决策者看的中文情报分析。

【分析要求】
1. 逐集分析：对每一集，提炼 3–5 条对我们团队（短剧出海 / PGC 商业化 / AI 内容 / 流媒体竞争）最有价值的关键论点。
   - 中文表达为主，英文播客中的关键术语、公司名、产品名保留英文原文。
   - 关键论点要具体（带数字、策略、案例），避免空泛。
2. 跨集综合洞察：综合本期所有内容，给出 2–4 条「本期核心判断」——
   指出值得团队关注的趋势、竞品动向、或对我们业务的启示。

【输出要求】严格输出 JSON：
{
  "cross_episode_insight": ["本期核心判断 1", "本期核心判断 2", "..."],
  "episodes": [
    {
      "source_name": "播客名称",
      "episode_title": "集名",
      "guests": "嘉宾",
      "episode_link": "原集链接",
      "key_points": ["关键论点1", "关键论点2", "关键论点3"],
      "summary": "一句话集摘要"
    }
  ]
}

【待分析内容】
{episodes_payload}
```

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：对它说「请帮我写深度分析模块，调用高质量模型，把初筛保留的内容套上面的 Prompt，输出 JSON。先不要写飞书，把生成的报告内容直接打印在终端里，让我读一遍看看质量好不好；不满意我会告诉你怎么改 Prompt。」  
</callout>

### 4.5 飞书写入模块（`src/output/feishu_writer.py`）

**职责**：把深度分析结果渲染成结构化报告，写入指定飞书文档。

**输入**：深度分析输出的 JSON。
**输出**：在目标飞书文档顶部追加一份本期报告（**最新在最上方**）。

**报告格式（飞书文档）**：
- **标题**：以日期为标题（如「2026-06-24 播客情报周报」），最新一期排在文档最上方。
- **本期核心判断**：放在最前面的高亮区块，列出跨播客综合洞察。
- **各集摘要**：每集包含——播客名称 + 集名 + 嘉宾 + 关键论点（3–5 条）+ 原集链接。
- **语言**：中文为主，英文播客的关键术语保留英文原文。

**实现要点**：
- 通过飞书开放平台 API：用 `app_id` + `app_secret` 换取 `tenant_access_token`，再调用文档块（block）写入接口，向 `FEISHU_DOC_ID` 指定的文档头部插入内容。
- 飞书文档 API 需要对应应用权限（`docx:document` 等），并把应用加入文档协作者。详见第 9 章交接手册。
- 建议把「渲染成飞书 block 结构」与「调用 API」拆成两个函数，便于本地先打印 markdown 预览再真正写入。

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：这步涉及飞书应用配置，最容易卡住。对它说「请带我一步步在飞书开放平台创建一个自建应用、开通文档写入权限、拿到 App ID 和 App Secret，并把应用加进我的目标文档协作者。每一步给我截图级别的点击指引。然后帮我写 feishu_writer.py，先用一条测试数据写进文档验证成功。」  
</callout>

### 4.6 GitHub Actions 定时配置（`.github/workflows/weekly_digest.yml`）

**职责**：按计划自动运行整条流水线，让系统不用你管也能每周更新。

```yaml
name: Weekly Podcast Digest

on:
  schedule:
    # 每周一 UTC 01:00（圣何塞前一晚 / 北京周一上午）运行；按需调整为每两周
    - cron: '0 1 * * 1'
  workflow_dispatch:        # 支持手动触发，便于调试

jobs:
  digest:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - name: Run digest pipeline
        env:
          LLM_SCREENING_API_KEY: ${{ secrets.LLM_SCREENING_API_KEY }}
          LLM_ANALYSIS_API_KEY: ${{ secrets.LLM_ANALYSIS_API_KEY }}
          FEISHU_APP_ID: ${{ secrets.FEISHU_APP_ID }}
          FEISHU_APP_SECRET: ${{ secrets.FEISHU_APP_SECRET }}
          FEISHU_DOC_ID: ${{ secrets.FEISHU_DOC_ID }}
        run: python -m src.main
```

<callout icon="bulb" bgc="3">  
**每两周运行**：GitHub Actions 原生 cron 不支持「每两周」。可把 cron 改为 `0 1 8,22 * *`（每月 8 号、22 号）近似两周一次，或保留每周 cron 并在代码里按周数奇偶判断是否执行。  
</callout>

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：等本地手动能跑通后再做这步。对它说「请帮我把上面的 weekly_digest.yml 放到正确位置，并带我在 GitHub 网页上把那几个密钥（Secrets）一个个填进去；然后教我怎么在 GitHub 上手动点一次运行来验证。」  
</callout>

---

## 5. 首批信息源配置（MVP 三个播客）

配置写入 `config/sources.yaml`，示例：

```yaml
window_days: 14            # 抓取时间窗口（过去 N 天）
sources:
  - name: "The Town with Matthew Belloni"
    lang: "en"
    rss: "<Megaphone 公开 RSS 地址>"   # 通过 Megaphone 获取
    frequency: "weekly"

  - name: "Decoder with Nilay Patel"
    lang: "en"
    rss: "<The Verge / Decoder RSS 地址>"  # 通过 The Verge 网站获取，常配完整文字稿
    frequency: "weekly"

  - name: "硅谷101"
    lang: "zh"
    rss: "<苹果播客镜像 feed 或 OPML 导出地址>"  # 小宇宙/苹果播客；小宇宙 show notes 详尽
    frequency: "weekly"
```

<table header-row="true" col-widths="160,120,240,240">  
<tr><td>播客</td><td>语言</td><td>RSS 获取方式</td><td>Show Notes 情况</td></tr>  
<tr><td>The Town with Matthew Belloni</td><td>英文</td><td>Megaphone 公开 RSS</td><td>有，含时间轴</td></tr>  
<tr><td>Decoder with Nilay Patel</td><td>英文</td><td>The Verge 网站获取</td><td>有，常配完整文字稿</td></tr>  
<tr><td>硅谷101</td><td>中文</td><td>苹果播客镜像 feed / OPML 导出</td><td>有，小宇宙 show notes 详尽</td></tr>  
</table>

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：三个播客的真实 RSS 地址需要先找到。对它说「请帮我找到这三个播客的真实 RSS 地址，并教我怎么验证地址有效（比如用浏览器打开看看是不是一堆 XML）。Decoder 因为常带完整文字稿，我们先用它做第一个测试源。」  
</callout>

---

## 6. 环境变量清单

「环境变量」就是把密钥单独存放、不写进代码里的安全做法。本地放在一个叫 `.env` 的文件里（参考下面的 `.env.example`），在 GitHub 上则放进 Repository Secrets。

<table header-row="true" col-widths="280,420">  
<tr><td>变量名</td><td>说明</td></tr>  
<tr><td>LLM_SCREENING_API_KEY</td><td>初筛低成本模型的 API Key（doubao / GPT-4o-mini）</td></tr>  
<tr><td>LLM_ANALYSIS_API_KEY</td><td>深度分析高质量模型的 API Key（Claude / doubao-seed）</td></tr>  
<tr><td>LLM_SCREENING_MODEL</td><td>（可选）初筛模型名，默认值写在代码里</td></tr>  
<tr><td>LLM_ANALYSIS_MODEL</td><td>（可选）深度分析模型名</td></tr>  
<tr><td>FEISHU_APP_ID</td><td>飞书自建应用的 App ID</td></tr>  
<tr><td>FEISHU_APP_SECRET</td><td>飞书自建应用的 App Secret</td></tr>  
<tr><td>FEISHU_DOC_ID</td><td>目标飞书文档的 document_id（报告写入此文档）</td></tr>  
</table>

`.env.example` 内容（提交到仓库，不含真实值）：

```bash
LLM_SCREENING_API_KEY=
LLM_ANALYSIS_API_KEY=
LLM_SCREENING_MODEL=gpt-4o-mini
LLM_ANALYSIS_MODEL=claude-sonnet
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_DOC_ID=
```

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：对它说「请帮我创建 .env 文件，并把 .env 加入 .gitignore（这样我的密钥不会被上传到 GitHub）。然后告诉我每个 Key 去哪里申请、拿到后粘到 .env 的哪一行。」  
</callout>

---

## 7. 开发优先级建议（你的执行顺序）

把这张表当成你的"通关地图"，**从上往下一行一行做**，每完成一行就让 Claude Code 帮你验证再进入下一行。

<table header-row="true" col-widths="80,260,360">  
<tr><td>阶段</td><td>任务</td><td>目标 / 验收</td></tr>  
<tr><td>P0</td><td>RSS 抓取 + Show Notes 解析</td><td>能从 1 个播客（建议 Decoder）拉到最近 14 天 episode 并打印干净文字</td></tr>  
<tr><td>P0</td><td>LLM 初筛跑通</td><td>对抓到的 episode 输出 is_relevant/score/tags 的 JSON</td></tr>  
<tr><td>P0</td><td>LLM 深度分析 + 本地预览</td><td>对保留 episode 产出 key_points 与跨集洞察，先打印不写飞书</td></tr>  
<tr><td>P1</td><td>飞书写入模块</td><td>把报告真正写入飞书文档，最新在最上方</td></tr>  
<tr><td>P1</td><td>扩展到 3 个播客 + 配置化</td><td>sources.yaml / filters.yaml 驱动，去重合并生效</td></tr>  
<tr><td>P2</td><td>GitHub Actions 定时</td><td>cron 自动运行，Secrets 配置完成，手动触发可用</td></tr>  
<tr><td>P2</td><td>缓存去重 + 错误处理 + 测试</td><td>避免重复处理；单源失败不影响整体；补关键测试</td></tr>  
</table>

<callout icon="bulb" bgc="4">  
**核心原则**：先纵向打通单个播客的端到端链路（P0），再横向扩展信息源（P1），最后自动化（P2）。不要一开始就追求三个源全接入或筛选精度最优。每个阶段都让 Claude Code 帮你"跑一次、看结果、再继续"。  
</callout>

---

## 8. 第一个可运行 MVP 的最小范围定义

<callout icon="first_place_medal" bgc="11">  
**MVP 验收标准（做到这些就算成功）**：在本地手动运行（Claude Code 会给你那条命令，通常是 `python -m src.main`），系统能够——  
1. 从 **Decoder（1 个播客）** 抓取最近 14 天的 episode；  
2. 解析出干净的 Show Notes 文字；  
3. 用低成本模型完成初筛（输出相关性 JSON）；  
4. 用高质量模型对保留 episode 产出关键论点 + 跨集洞察；  
5. 把一份中文为主的结构化报告**成功写入指定飞书文档，最新在最上方**。  
</callout>

**MVP 明确不包含**（留到后续迭代）：
- 音频转写（永不做，本项目只用 Show Notes）。
- 三个播客全部接入（MVP 先 1 个，跑通后再加）。
- GitHub Actions 自动化（MVP 阶段你手动运行即可）。
- 复杂去重/主题聚类、邮件/IM 告警、Web 界面。

<callout icon="speech_balloon" bgc="5">  
**💡 如何用 Claude Code 完成这一步**：当你完成 P0+P1 后，对它说「请帮我做一次完整的 MVP 验收：从头跑一遍 Decoder，确认这 5 条都达成，并把每一步的输出贴给我确认。如果哪一步失败，请带我定位并修复。」  
</callout>

---

## 9. HANDOVER.md 交接手册模板

下方为 `HANDOVER.md` 的完整内容，请保存为仓库根目录下的 `HANDOVER.md`（可以让 Claude Code 帮你创建并填好占位符）。它面向**完全没有技术背景的接手同事**，目标是 **30 分钟内完成交接**。

<callout icon="speech_balloon" bgc="5">  
**💡 提示**：把模板里所有 `【】` 占位符替换成真实信息（仓库地址、应用名称、文档链接、负责人等）后再交付。带 `#` 的命令行内容保持不变，让接手人照抄即可。可以直接让 Claude Code：「请帮我把 HANDOVER.md 里的占位符换成我的真实信息」。  
</callout>

````markdown
# 工具交接手册（HANDOVER）

> 本手册写给**完全没有技术背景**的同事。照着一步步做，约 30 分钟即可完成交接。
> 全程你不需要写任何代码，只需要"点击网页按钮"和"复制粘贴"。

## 这个工具是做什么的？

它每周自动帮我们读几个播客（The Town、Decoder、硅谷101）的文字简介，
挑出和"短剧 / AI 内容 / 流媒体竞争"相关的内容，写成一份中文周报，自动发到一篇飞书文档里。
它住在 GitHub 上，自己定时运行，平时不用管。

交接其实就是把"三把钥匙"交给你：
1. **GitHub 仓库**（代码住的地方）
2. **运行密钥 GitHub Secrets**（让它能调用 AI 和飞书的密码）
3. **飞书文档和飞书应用**（它把周报写进去的地方）

---

## 准备工作（2 分钟）

请先准备好：
- 你的 GitHub 账号（没有就去 github.com 免费注册）
- 你的飞书账号（公司飞书即可）
- 把你的 GitHub 用户名、飞书邮箱发给交接人【交接人姓名 / 联系方式】

---

## 第一步：加入 GitHub 仓库（约 8 分钟）

GitHub 是存放这个工具代码的网站。你需要被"邀请"成为协作者才能管理它。

**交接人操作（请交接人完成）：**
1. 用浏览器打开仓库：【仓库地址，例如 https://github.com/你们的组织/podcast-digest】
2. 点击页面上方的 **Settings（设置）**
3. 左边菜单点 **Collaborators（协作者）**（可能需要再次输入 GitHub 密码）
4. 点绿色按钮 **Add people（添加成员）**
5. 输入接手人的 GitHub 用户名或邮箱，选择权限为 **Admin（管理员）**，点 **Add**

**接手人操作（你来完成）：**
6. 打开你的邮箱，会收到一封 GitHub 邀请邮件，点邮件里的 **Accept invitation（接受邀请）**
7. 接受后，你再打开仓库地址，能看到 **Settings** 选项，就说明成功了 ✅

> 如果交接人要彻底离开，可在第 5 步把自己从 Collaborators 列表移除（点名字后面的 Remove）。

---

## 第二步：重新配置 GitHub Secrets（约 12 分钟）

"Secrets"是这个工具运行需要的密码（比如调用 AI、写飞书的钥匙）。
交接时通常需要**换成新的钥匙**，避免老员工还能用旧钥匙。

**先拿到新钥匙（找对应负责人要）：**
- AI 模型的 API Key：找【AI 平台负责人 / 申请入口】要两把
  - 初筛模型 Key（便宜的那把）
  - 深度分析模型 Key（高质量那把）
- 飞书的 App ID / App Secret：见第三步会拿到
- 飞书文档 ID：见第三步会拿到

**在 GitHub 上填入钥匙：**
1. 打开仓库，点上方 **Settings**
2. 左边菜单找到 **Secrets and variables（密钥和变量）→ Actions**
3. 你会看到已有的几条 Secret（名字看得到，值看不到，这是正常的）
4. 要更新某条：点它右边的 **Update（更新）**，把新值粘进去，点 **Save**
5. 按下表逐条更新（名字必须完全一致，不要改名）：

   | Secret 名称 | 填什么 |
   |---|---|
   | `LLM_SCREENING_API_KEY` | 初筛模型的新 API Key |
   | `LLM_ANALYSIS_API_KEY` | 深度分析模型的新 API Key |
   | `FEISHU_APP_ID` | 飞书应用的 App ID（第三步获得） |
   | `FEISHU_APP_SECRET` | 飞书应用的 App Secret（第三步获得） |
   | `FEISHU_DOC_ID` | 目标飞书文档 ID（第三步获得） |

6. 全部更新完后，验证一下：
   - 点仓库上方 **Actions** 标签
   - 找到名为 **Weekly Podcast Digest** 的流程，点进去
   - 点右边 **Run workflow（运行工作流）** 手动跑一次
   - 等几分钟，如果出现绿色 ✅ 就说明钥匙配对了；红色 ❌ 就把页面截图发给【技术支持联系人】

> 安全提醒：钥匙就像家门钥匙，不要发到群里、不要截图给无关的人。

---

## 第三步：转移飞书文档和飞书应用权限（约 8 分钟）

工具把周报写进一篇**飞书文档**，靠一个**飞书应用**（机器人）来写入。两样都要转给你。

### 3.1 飞书文档：把你设为所有者

1. 打开周报所在的飞书文档：【飞书文档链接】
2. 点右上角 **分享（Share）** 按钮
3. 在协作者列表里找到你自己（没有就先搜索你的名字添加，权限选"可管理"）
4. 交接人点自己名字旁的角色，选择 **设为所有者 / 转移所有权** 给接手人
5. 确认后，你就是这篇文档的所有者了 ✅

### 3.2 飞书应用：把你设为管理员

这个"应用"是写文档的机器人，在飞书开放平台后台管理。

1. 浏览器打开飞书开放平台：【开放平台地址，如 https://open.feishu.cn】，用公司飞书账号登录
2. 进入 **开发者后台 → 企业自建应用**，找到名为【应用名称】的应用
3. 打开它，进入 **应用管理 / 协作者** 设置
4. 把接手人添加为 **管理员（Admin）**
5. 在应用的 **凭证与基础信息** 页面，可以看到 **App ID** 和 **App Secret**
   —— 这两个值就是第二步要填进 GitHub Secrets 的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`
   （如需更换 Secret，点 **重置 App Secret**，重置后记得回第二步更新 GitHub）

### 3.3 确认应用还在文档里

1. 回到 3.1 的飞书文档，点 **分享**
2. 确认协作者里有那个机器人应用【应用名称】，且权限是"可编辑"
   （如果没有，点添加，搜索应用名称加进来）

### 3.4 拿到文档 ID（填 FEISHU_DOC_ID 用）

1. 看飞书文档的网址，形如：`https://【你们的飞书域名】/docx/XXXXXXXXXXXX`
2. 最后那串 `XXXXXXXXXXXX` 就是文档 ID
3. 把它填到第二步的 `FEISHU_DOC_ID`

---

## 完成交接检查清单（1 分钟）

全部打勾就算交接完成 🎉：

- [ ] 我能打开 GitHub 仓库并看到 Settings（第一步）
- [ ] 我已更新所有 GitHub Secrets，并手动运行 Actions 出现了绿色 ✅（第二步）
- [ ] 我是飞书周报文档的所有者（第三步 3.1）
- [ ] 我是飞书应用的管理员（第三步 3.2）
- [ ] 飞书文档协作者里有那个机器人应用且可编辑（第三步 3.3）

---

## 平时怎么用？遇到问题找谁？

- **平时**：什么都不用做，它每周自动运行并更新飞书文档。
- **想立刻跑一次**：GitHub 仓库 → Actions → Weekly Podcast Digest → Run workflow。
- **周报没更新 / 出现红色 ❌**：去 Actions 点开那次失败记录，截图发给【技术支持联系人】，或打开 Claude Code 把报错贴给它求助。
- **想加 / 减播客**：用 Claude Code 修改 `config/sources.yaml`，或联系【技术支持联系人】。

| 找谁 | 联系方式 |
|---|---|
| 原负责人 / 交接人 | 【姓名 + 飞书】 |
| 技术支持 | 【姓名 + 飞书】 |
| AI 平台 Key 申请 | 【入口 / 负责人】 |
````
