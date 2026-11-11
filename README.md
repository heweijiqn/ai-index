# 热卖指数

通过闲鱼关键词搜索采样，观察 AI 教程、副业和工具部署相关话题的变化，生成可阅读的数据文档、3 张分享卡片和发布文案。

维护者：[hwj](https://github.com/heweijiqn) · [项目仓库](https://github.com/heweijiqn/ai-index)

## 能做什么

- 使用本地浏览器登录会话抓取手动输入的关键词，自行指定每个关键词的商品采样上限。
- 按商品 ID 和卖家 ID 去重，汇总数量与平均价格。
- 将历史保存为 **中文 TXT + JSON 文档**，双击 TXT 即可阅读。
- 生成 3 张 **1080 × 1080 PNG** 和 `post.txt` 发布文案，默认署名 **hwj**。
- **每次运行新建结果文件夹**，同一天重复运行也会保留之前的结果。
- 登录失效、访问受限或解析异常时明确报错，避免用失败数据生成指数。

## 已配置好的本机

项目位置：`D:\ai-index`。

1. 双击 **`run.bat`** 开始运行。
2. 输入关键词（多个关键词用中文或英文逗号分隔，例如 `AI 副业，Sora 教程`），再输入每个关键词最多抓取的商品数，例如 `100`。
3. 等待控制台显示 `=== Done ===` 和 `Exit code: 0`。
4. 打开 **`output` 下最新的结果文件夹**，查看图片、文案和数据。

数量按每个关键词的去重商品数计算。例如两个关键词、每个 `100` 条，合计最多 `200` 条关键词商品记录。结果不足时保留实际数量并提示，不补齐虚假数据。

控制台输入示例（输入后按回车）：

```text
请输入关键词（多个关键词用中文或英文逗号分隔）：AI 副业，Sora 教程
每个关键词最多抓取多少条商品（正整数）：100
本次关键词：AI 副业、Sora 教程；每个关键词最多 100 条去重商品。
```

关键词中的空格会保留，重复关键词只抓一次。关键词不能留空，数量应填写 `100` 这样的正整数，不要填 `100条` 或小数；交互输入有误时会要求重填。每次双击都会重新输入，本次选择不会保存为下次默认值。

需要登录时，先运行 **`login.bat`**，在 Chrome 中登录闲鱼并完成必要验证。确认搜索商品出现后，**关闭整个登录浏览器窗口**，再运行 `run.bat`。同一时间只运行一个登录或抓取任务。

详细步骤和常见问题见 [中文使用手册](使用手册.txt)。

## 从 GitHub 首次安装

需要 Python 3.12、Git，以及已安装的 Chrome。以下为 PowerShell 命令：

```powershell
git clone https://github.com/heweijiqn/ai-index.git D:\ai-index
Set-Location D:\ai-index
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.browsers"
.\.venv\Scripts\python.exe -m playwright install chromium --only-shell
```

安装后运行 `login.bat` 完成登录，再运行 `run.bat`。Python 环境、Chromium 和登录状态都在本地创建，不随源码仓库提供。

Linux/macOS 使用 Python 3.12 创建 `.venv`，后续命令使用 `.venv/bin/python3`。服务器部署和浏览器会话要求见 [部署说明](docs/deployment.md)。

## 结果保存在哪里

```text
data/
  history/
    2026-11-11.txt         每日最新数据，直接阅读
    2026-11-11.json        每日最新数据，供程序计算趋势
  browser-profile/        本机浏览器登录状态

output/
  2026-11-11_164830_449717_b3484009/
    抓取数据.txt           本次数据文档
    records.json          本次数据快照
    card1_index_2026_11_11.png
    card2_daily_2026_11_11.png
    card3_weekly_2026_11_11.png
    post.txt              本次发布文案
```

结果文件夹包含记录日期、北京时间和唯一编号。每天的历史文档更新为最新记录，各次运行文件夹保留自己的快照。删除旧结果文件夹不会删除每日历史。

本地数据、登录会话、生成结果、运行日志和环境文件均不上传 GitHub；克隆仓库后会从自己的抓取结果开始积累历史。

## 常用操作

**测试渲染环境**：双击 `smoke-test.bat`。固定样例结果每次保存到 `output/smoke/` 下的新文件夹，不修改真实历史。

**验证一个关键词，不保存数据**：

```powershell
Set-Location D:\ai-index
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.browsers"
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe crawler.py --keyword 'AI 副业' --limit 100 --dry-run
```

**直接指定关键词和数量**（参数齐全时不会再提问）：

```powershell
.\run.bat --keyword 'AI 副业' --keyword 'Sora 教程' --limit 100
```

关键词中的空格会保留；命令行传多个关键词时重复使用 `--keyword`。`run.bat` 会提示补全缺失的关键词或数量。自动化任务可直接调用 `.venv/Scripts/python.exe run_daily.py`；不传采样参数时继续使用 `config.py` 中的默认 8 个关键词、每个最多 2 页，传 `--keyword` / `--limit` 可覆盖。

例如，只想提前指定数量、运行时再输入关键词：

```powershell
.\run.bat --limit 100
```

直接运行 Python 时，加 `--interactive` 才会提示输入：

```powershell
.\.venv\Scripts\python.exe run_daily.py --interactive
```

**指定记录日期**：

```powershell
.\run.bat --date 2026-11-11
```

默认记录日期使用 UTC，北京时间凌晨 00:00–07:59 运行时可能记录为前一天。`--date` 只指定记录日期，实际抓取的仍是运行当时的搜索结果。

**修改输出署名**：

```powershell
$env:AI_INDEX_AUTHOR = 'hwj'
.\run.bat
```

默认署名为 `hwj`。日常关键词和数量在运行时输入，无需修改源码；自动化使用的默认关键词及其他项目设置集中在 `config.py`。

## 怎样理解数据

商品数是搜索结果的采样计数，按指定上限去重截取；达到上限或搜索结果结束即停止。关键词之间可能有重复商品，不代表闲鱼平台全部商品总量。

本次图片和文案只分析本次抓取的关键词；每日历史仍按关键词合并保留。同一关键词跨天比较时应保持采样上限一致，更改上限本身也会改变指数和趋势。

初期需要积累历史数据，趋势与周变化才有可比较的基础。已部署机器保留的旧版全零历史会在对应 TXT 中提醒；新克隆的仓库不包含这些旧数据。

浏览器会话可能失效，平台也可能要求人工验证。当前主要使用方式是本地登录后运行；云端无人值守抓取需要单独验证。

## 开发与验证

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.browsers"
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m black . --line-length 100 --check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy . --ignore-missing-imports
```

GitHub Actions 运行代码检查、回归测试和样例渲染。真实商品抓取在具有有效登录会话的环境中执行。

- [使用手册](使用手册.txt)：日常操作、文件位置、常见问题和备份。
- [部署说明](docs/deployment.md)：Windows、VPS 和 Docker 运行条件。
- [项目架构](docs/architecture.md)：抓取、文档存储、分析与渲染的数据流。
- [开发约定](AGENTS.md)：项目命令、代码规范与任务范围。
