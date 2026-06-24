# 播客摘要系统（Podcast Digest）

每周自动抓取指定播客的 RSS（只读 Show Notes 文字，不做音频转写），先用便宜模型
初筛打标签，再用高质量模型做深度分析，最终产出一份中文为主的情报报告。

- 初筛模型：Claude **Haiku**（便宜、快）
- 深度分析模型：Claude **Sonnet**（质量好）
- 一个 **Anthropic API Key** 同时调用这两个模型。

> 当前进度：**P0**——在本地跑通「抓取 → 清洗 → 初筛 → 深度分析 → 终端打印报告」。
> 飞书写入（P1）和 GitHub Actions 定时（P2）稍后再做。

---

## 本地运行步骤（零基础照抄）

下面每条以 `$` 开头的是终端命令，复制 `$` 后面的内容粘贴到终端、回车即可。

### 1. 进入项目目录
```bash
cd /Users/bytedance/podcast-digest
```

### 2. 创建并激活虚拟环境（给项目单独装依赖，不污染系统）
```bash
python3 -m venv .venv
source .venv/bin/activate
```
激活成功后，命令行最前面会出现 `(.venv)` 字样。

### 3. 安装依赖
```bash
pip install -r requirements.txt
```

### 4. 配置 API Key
```bash
cp .env.example .env
```
然后用编辑器打开 `.env`，把你的 Anthropic Key 填到这一行：
```
ANTHROPIC_API_KEY=sk-ant-你的key
```

### 5. 分步测试（推荐按顺序，每步看一眼结果）
```bash
# 只测 RSS 抓取（不需要 Key）
python -m src.fetch.rss_fetcher

# 只测 Show Notes 清洗（不需要 Key）
python -m src.parse.shownotes_parser

# 测初筛（需要 Key）
python -m src.llm.screening

# 测深度分析（需要 Key）
python -m src.llm.analysis
```

### 6. 跑完整流水线
```bash
python -m src.main
```

---

## 目录结构
```
config/        播客源(sources.yaml) 与 筛选标准(filters.yaml)
src/fetch/     RSS 抓取
src/parse/     Show Notes 清洗
src/llm/       client(模型调用) / screening(初筛) / analysis(分析)
src/prompts/   Prompt 模板（可直接编辑调优）
src/output/    飞书写入（P1）
src/main.py    入口，串联整条流水线
```

## 想加 / 减播客？
编辑 `config/sources.yaml`，把对应源的 `enabled` 改成 `true`/`false`，
并填上真实 RSS 地址即可，不用改代码。

## 想调整筛选口味？
编辑 `config/filters.yaml`（关注话题、竞品公司、分析框架都在里面）。
