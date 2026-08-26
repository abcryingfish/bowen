# 可视化目录说明

本目录是本地量化看板、回测结果页、组合图表页和相关 HTTP API 的入口目录。

日常使用时，优先通过批处理脚本启动服务：

```powershell
可视化\start_all.bat
```

启动后默认访问：

```text
http://127.0.0.1:8086/量化因子/index.html
```

如果只启动 Web 静态服务或 API 服务，可分别使用：

```powershell
可视化\start_web_server.bat
可视化\start_api_server.bat
```

---

## 一句话

真正页面现在放在各自文件夹里的 `index.html`；目录根部的若干 `.html` 文件主要是兼容旧链接的跳转壳。

例如：

```text
量化因子.html  ->  量化因子/index.html
形态面.html    ->  形态面/index.html
舆情面.html    ->  舆情面/index.html
基本面.html    ->  基本面/index.html
实盘面.html    ->  实盘面/index.html
结果展示.html  ->  结果展示/index.html
result.html    ->  组合结果/index.html
index.html     ->  组合图表/index.html
```

这些根部 `.html` 文件不要轻易删除，因为浏览器收藏、旧文档、外部脚本或历史链接可能还在访问它们。

---

## 推荐入口

| 页面 | 推荐访问路径 | 说明 |
|------|--------------|------|
| 量化因子主看板 | `/量化因子/index.html` | K 线、因子副图、自选股、回测入口等主页面 |
| 形态面 | `/形态面/index.html` | 形态相关视图 |
| 舆情面 | `/舆情面/index.html` | 舆情相关视图 |
| 基本面 | `/基本面/index.html` | 基本面/公司数据相关视图 |
| 实盘面 | `/实盘面/index.html` | 实盘或实时观察页面 |
| 市场研究 | `/市场研究/index.html` | 沪、深、科创、全 A 集中度与 RSI 比值 |
| 板块轮动 | `/板块轮动/index.html` | 同花顺板块收益曲线、排序、搜索和成分查看 |
| 模型有效性 | `/模型有效性/index.html` | 个股风格模型高低分组合表现、持仓和交易 |
| 多维度分析 | `/多维度分析/index.html` | 板块研究正式报告读取与全展开视图 |
| 量化因子有效性检验 | `/量化因子有效性检验/dashboard.html` | 因子收益检验、异步任务和历史记录 |
| 结果展示 | `/结果展示/index.html` | 回测历史列表、结果跳转、删除等 |
| 组合结果 | `/组合结果/index.html` | 组合回测结果外壳，内部嵌入组合图表 |
| 组合图表 | `/组合图表/index.html` | 组合曲线图表内嵌页，一般不直接作为主入口打开 |

平时打开主站建议使用：

```text
http://127.0.0.1:8086/量化因子/index.html
```

不建议把下面这种旧路径作为新文档或新代码里的入口：

```text
http://127.0.0.1:8086/量化因子.html
```

旧路径仍会跳转，只是为了兼容。

---

## 目录职责

### `量化因子/`

量化主看板页面。

典型内容：

- `index.html`：主入口 HTML。
- `board_quant.js`：量化因子页面自己的逻辑。

常见功能包括：

- 日 K / 分钟 K 展示。
- 因子副图。
- 自选股。
- 回测任务入口。
- 与 `shared/chart_board_core.js`、`shared/chart_board_backtest.js` 配合工作。

### `形态面/`

形态分析视图。

典型内容：

- `index.html`
- `board_morph.js`

这个页面复用公共图表和导航能力，但放置形态相关的页面逻辑。

### `舆情面/`

舆情信息视图。

典型内容：

- `index.html`
- `sentiment.css`
- 舆情页面自己的 JS 文件。

舆情/信息类页面通常会复用 `shared/chart_board_info_core.js`。

### `基本面/`

基本面视图。

典型内容：

- `index.html`
- `board_fundamental.js`
- `fundamental.css`

用于展示公司基本面、财务、估值等信息。后端数据通常来自 `api_server.py` 转发的本地数据服务。

### `实盘面/`

实盘或实时观察页面。

典型内容：

- `index.html`
- `live_board.js`
- `live_board.css`

用于和实时行情、实时因子、实盘状态类模块对接。这个页面与历史回测页面职责不同，修改前要确认数据来源和刷新逻辑。

### 独立研究与检验页面

- `市场研究/`：四类 A 股市场集中度和 RSI 比值，详见 [`市场研究/README.md`](市场研究/README.md)。
- `板块轮动/`：同花顺 881/882/885/886 指数与成分，详见 [`板块轮动/README.md`](板块轮动/README.md)。
- `模型有效性/`：风格模型组合账本，详见 [`模型有效性/README.md`](模型有效性/README.md)。
- `多维度分析/`：板块研究报告页，详见 [`多维度分析/README.md`](多维度分析/README.md)。
- `量化因子有效性检验/`：因子检验任务和记录，详见 [`量化因子有效性检验/README.md`](量化因子有效性检验/README.md)。

### `结果展示/`

回测结果列表页。

典型内容：

- `index.html`

用于展示已有回测任务、查看结果、跳转到组合结果页等。它不是 K 线主看板，但会和回测任务服务、结果文件列表相关。

### `组合结果/`

组合回测结果外壳页。

典型内容：

- `index.html`
- `result_print_light.css`
- `result_print_light.js`

这个页面通常会创建 iframe，把 `组合图表/index.html` 嵌进去，用来展示组合回测曲线和打印主题。

一般访问：

```text
http://127.0.0.1:8086/组合结果/index.html
```

### `组合图表/`

组合图表内嵌页。

典型内容：

- `index.html`

这是给 `组合结果/index.html` 的 iframe 使用的图表页面。直接打开时可能会提示从量化因子或组合结果页进入。

修改组合曲线、`.YKRS` 组合曲线展示、组合图表内嵌逻辑时，需要同时检查：

- `组合结果/index.html`
- `组合图表/index.html`
- `shared/chart_board_core.js`
- `shared/backtest_run_context.js`

### `shared/`

多页面共享资源目录。

典型内容：

- `chart_board_core.js`：K 线看板公共核心逻辑。
- `chart_board_backtest.js`：回测任务 UI 和参数遍历逻辑。
- `chart_board_info_core.js`：舆情/基本面等信息页面的公共逻辑。
- `chart_board.css`：公共样式。
- `edge_float_nav.js`、`edge_float_hud.js`、`edge_float.css`：侧边悬浮导航相关逻辑和样式。
- `lightweight-charts.standalone.production.js`：图表库文件。
- `backtest_run_context.js`：回测运行上下文在 URL、页面间的传递逻辑。

原则：

- 多个页面都要用的逻辑放 `shared/`。
- 只有某个页面用的逻辑放对应页面目录。
- 不要为了省事把所有页面的独有逻辑都塞进 `shared/`，否则后面会越来越难维护。

---

## 根目录 HTML 文件为什么还在

根目录下这些 HTML 文件：

```text
index.html
result.html
量化因子.html
形态面.html
舆情面.html
基本面.html
实盘面.html
市场研究.html
板块轮动.html
模型有效性.html
结果展示.html
```

主要是旧入口兼容文件。它们通常只有两层跳转逻辑：

1. `<meta http-equiv="refresh">` 用于无 JS 场景跳转。
2. `location.replace(...)` 用于保留 query string 和 hash。

例如访问：

```text
http://127.0.0.1:8086/量化因子.html?code=000001.SZ
```

会跳转到：

```text
http://127.0.0.1:8086/量化因子/index.html?code=000001.SZ
```

这样老链接仍然能用，同时不会在浏览器历史里额外留一层旧页面。

---

## 新增页面时的建议结构

如果以后新增一个页面，比如 `龙虎榜`，推荐使用：

```text
可视化/
  龙虎榜/
    index.html
    board_lhb.js
    lhb.css
```

如果需要兼容旧入口，可以额外加：

```text
可视化/龙虎榜.html
```

内容只做跳转：

```html
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0; url=龙虎榜/index.html">
    <script>
        location.replace("龙虎榜/index.html" + location.search + location.hash);
    </script>
</head>
<body>
    页面已移动到 <a href="龙虎榜/index.html">龙虎榜/index.html</a>
</body>
</html>
```

是否需要加旧入口跳转文件，取决于这个页面是否已经被外部引用、收藏或写进文档。

---

## 后端服务文件

### `api_server.py`

HTTP API 入口，提供前端页面需要的数据接口。

常见职责：

- K 线数据。
- 因子数据。
- 股票搜索。
- 回测模型列表。
- 回测任务触发。
- 基本面/公司数据接口转发。
- 市场研究、板块指数、成分和风格模型接口。
- 因子有效性检验异步任务与记录接口。

修改前端请求路径时，通常要同步看这里。

### `market_data_service.py`

读取本地 parquet 行情、因子、分钟线等数据的服务层。

常见数据源：

- `D:\database\stock_basic_data_daily`
- `D:\database\stock_basic_data_mins`
- `D:\database\signal_daily`

如果前端 K 线、因子副图、左拖历史加载异常，通常需要同时看：

- `api_server.py`
- `market_data_service.py`
- `shared/chart_board_core.js`

### `backtest_job_service.py`

网页触发回测任务的服务层。

与前端回测面板、回测模型注册、结果展示页有关。

### `fundamental_data_service.py`

基本面数据服务。

通常与 `基本面/index.html`、`基本面/board_fundamental.js`、`api_server.py` 一起看。

### `daily_adjustment_service.py`

日频复权/调整相关服务。

如果页面显示前复权、后复权或价格调整相关逻辑异常，需要检查这里和对应数据路径。

### 独立研究服务

- `market_research_service.py`：市场集中度和 RSI 比值。
- `style_monitor_service.py`：风格模型组合曲线、摘要、持仓和交易查询。
- `style_monitor_job_service.py`：风格组合账本更新任务。
- `sector_research_service.py`：板块研究实体、报告和看板数据。
- `量化因子有效性检验/factor_validation_service.py`：因子检验计算、异步任务与记录。

---

## 页面之间的关系

主页面导航大致如下：

```text
量化因子/index.html
  -> 形态面/index.html
  -> 舆情面/index.html
  -> 基本面/index.html
  -> 市场研究/index.html
  -> 板块轮动/index.html
  -> 模型有效性/index.html
  -> 多维度分析/index.html
  -> 量化因子有效性检验/dashboard.html

量化因子/index.html
  -> 发起回测
  -> 结果展示/index.html
  -> 组合结果/index.html
  -> iframe: 组合图表/index.html
```

组合图表页不是普通主页面，它更像是一个嵌入组件。修改时要注意 iframe 场景下的 URL 参数、打印样式和跨页面状态。

---

## 修改建议

### 修改 K 线、因子副图、左拖历史

优先检查：

```text
量化因子/index.html
shared/chart_board_core.js
market_data_service.py
api_server.py
```

如果是形态、舆情、基本面页面上的 K 线或信息区，也要检查对应页面目录里的 JS。

### 修改回测按钮、模型列表、参数遍历

优先检查：

```text
shared/chart_board_backtest.js
backtest_job_service.py
api_server.py
../backtrader/model_registry.py
```

回测模型是否能在网页上出现，通常和 `backtrader/model_registry.py` 以及 `GET /api/backtest/models` 有关。

### 修改结果展示或组合结果页

优先检查：

```text
结果展示/index.html
组合结果/index.html
组合图表/index.html
shared/backtest_run_context.js
shared/chart_board_core.js
```

### 修改基本面页面

优先检查：

```text
基本面/index.html
基本面/board_fundamental.js
基本面/fundamental.css
fundamental_data_service.py
api_server.py
```

---

## 不要轻易做的事

1. 不要直接删除根目录 `.html` 跳转文件。
   - 它们是旧入口兼容层。
   - 删除前应全仓库搜索引用，并确认浏览器收藏、脚本、文档不再使用。

2. 不要把页面目录里的 `index.html` 当成重复文件删除。
   - 这些才是正式页面。

3. 不要把所有 JS 都合并进一个大文件。
   - 公共逻辑放 `shared/`。
   - 页面独有逻辑放页面自己的目录。

4. 不要无确认改 API 端口。
   - 前端通常默认 Web 端口 `8086`、API 端口 `8000`。
   - 改端口要同步批处理脚本和前端 API base 推导逻辑。

5. 不要随意改 `D:\database` 数据路径。
   - 路径改动需要全仓库搜索引用。
   - Notebook 字符串也要检查。

---

## 常用命令

从项目根目录运行：

```powershell
cd C:\Users\Administrator\Desktop\python_venv
可视化\start_all.bat
```

只启动 Web：

```powershell
可视化\start_web_server.bat
```

只启动 API：

```powershell
可视化\start_api_server.bat
```

直接用项目虚拟环境运行 API：

```powershell
.\.venv\Scripts\python.exe 可视化\api_server.py
```

---

## 给 Agent 的快速路由

| 任务 | 先看哪些文件 |
|------|--------------|
| 页面入口/导航/旧链接跳转 | 根目录 `.html`、各页面 `index.html`、`shared/edge_float_nav.js` |
| K 线主看板 | `量化因子/index.html`、`shared/chart_board_core.js` |
| 回测面板 | `shared/chart_board_backtest.js`、`backtest_job_service.py`、`api_server.py` |
| 回测结果列表 | `结果展示/index.html` |
| 组合结果/组合曲线 | `组合结果/index.html`、`组合图表/index.html`、`shared/backtest_run_context.js` |
| 基本面视图 | `基本面/index.html`、`基本面/board_fundamental.js`、`fundamental_data_service.py` |
| 舆情视图 | `舆情面/index.html`、`shared/chart_board_info_core.js` |
| 实盘视图 | `实盘面/index.html`、`实盘面/live_board.js` |
| 市场研究 | `市场研究/`、`market_research_service.py`、`api_server.py` |
| 板块轮动 | `板块轮动/`、`market_data_service.py`、`api_server.py` |
| 模型有效性 | `模型有效性/`、`style_monitor_service.py`、`style_monitor_job_service.py` |
| 多维度分析 | `多维度分析/index.html`、`sector_research_service.py` |
| 因子有效性检验 | `量化因子有效性检验/`、其 `factor_validation_service.py`、`api_server.py` |
| API 路由 | `api_server.py` |
| Parquet 行情/因子读取 | `market_data_service.py` |

---

## 判断某个 HTML 是否有用

可以按这个顺序判断：

1. 如果它在页面目录中，路径类似 `量化因子/index.html`，通常是正式页面。
2. 如果它在 `可视化/` 根目录，路径类似 `量化因子.html`，通常是旧入口跳转壳。
3. 如果它被 `rg` 搜到有引用，不能直接删。
4. 如果它只是跳转壳，也不代表没用；它可能保护旧链接。
5. 真要清理前，先全仓库搜索文件名。

示例：

```powershell
rg -n "量化因子\.html|量化因子/index\.html" C:\Users\Administrator\Desktop\python_venv
```

---

## 当前推荐维护原则

保留现在的结构：

```text
可视化/
  shared/
  量化因子/
  形态面/
  舆情面/
  基本面/
  实盘面/
  市场研究/
  板块轮动/
  模型有效性/
  多维度分析/
  量化因子有效性检验/
  结果展示/
  组合结果/
  组合图表/
  量化因子.html
  形态面.html
  舆情面.html
  基本面.html
  实盘面.html
  市场研究.html
  板块轮动.html
  模型有效性.html
  结果展示.html
  result.html
  index.html
```

新增功能时：

- 新页面建新目录。
- 页面独有代码放页面目录。
- 公共能力放 `shared/`。
- 旧入口跳转文件只在需要兼容时添加。
- 新文档、新链接尽量指向目录下的 `index.html`。
