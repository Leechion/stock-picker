<div align="center">

<img src="frontend/public/icon.svg" width="64" height="64" alt="StockPicker" />

# QuantBlade

**量剑 — A 股量化多因子选股平台**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![Vue](https://img.shields.io/badge/Vue.js-3-4FC08D?logo=vuedotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?logo=typescript&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

多因子量化选股 · AI 明日推荐 · 模拟交易引擎 · WebSocket 实时监控 · 企微机器人交互

[快速开始](#-快速开始) · [系统架构](#-系统架构) · [AI 明日推荐](#-ai-明日推荐) · [策略详解](#-多因子策略) · [模拟交易](#-模拟交易引擎) · [API 文档](#-api-接口)

</div>

---

## 功能概览

<table>
<tr>
<td width="50%">

### 多因子选股
- 16 个量化因子，3 大维度综合评分
- 技术面 (MA/MACD/RSI/KDJ/布林带/量比)
- 基本面 (PE/PB/ROE/营收增长/利润增长/资产负债率)
- 情绪面 (换手率/资金流向/5日动量/20日动量)
- 3 套内置策略 + YAML 自定义策略

</td>
<td width="50%">

### 模拟交易引擎
- 50 万虚拟资金，最多 10 只持仓
- 金字塔仓位管理 (排名越高仓位越重)
- ATR(14) 动态追踪止损 (只升不降)
- 阶梯止盈 (+15% → +30% → 追踪回撤)
- 盘前/盘中/盘后全自动调度

</td>
</tr>
<tr>
<td width="50%">

### WebSocket 实时监控
- 持仓行情、账户盈亏、交易事件实时推送
- 3 秒更新频率，前端无刷新
- 断线自动重连 (指数退避)
- 按频道订阅 (positions/account/trades)

</td>
<td width="50%">

### AI 明日推荐
- 每日 14:30 自动采集全市场实时行情
- DeepSeek 大模型分析市场，自主选出 0-5 只明日标的
- 企微群自动推送，前端历史战绩可回溯
- 次日盘后自动回测涨跌幅，统计命中率

</td>
</tr>
<tr>
<td width="50%">

### AI 智能分析 & 企微机器人
- DeepSeek 大模型生成个股深度点评
- 企业微信 @机器人即时查询
- `000001` 查行情，`600519 评分` 查因子
- `600519 分析` 触发 AI 深度分析
- 群消息自动推送 (Webhook)

</td>
<td width="50%">

### 预警提醒
- 自定义价格/涨跌幅/排名变动预警
- 触发后自动推送到企微群
- 支持多条件组合

</td>
</tr>
</table>

---

## 系统架构

```mermaid
graph TB
    subgraph Frontend["<b>前端 Vue 3</b>"]
        UI["Element Plus UI<br/>ECharts K线图"]
        Store["Pinia 状态管理"]
        WS_Client["WebSocket 客户端<br/>自动重连 · 指数退避"]
    end

    subgraph Backend["<b>后端 FastAPI</b>"]
        API["API 路由层<br/>10 个模块"]
        Services["业务服务层"]
        Scheduler["APScheduler<br/>定时任务引擎"]
        WS_Hub["MonitorHub<br/>频道广播"]

        subgraph Services_Detail["服务模块"]
            DataService["数据服务<br/>akshare 数据源"]
            FactorEngine["因子引擎<br/>16 因子计算"]
            RankingService["排名服务<br/>加权评分排序"]
            TradingEngine["交易引擎<br/>买卖 · 仓位 · 止损"]
            AIReport["AI 分析<br/>DeepSeek 接口"]
            AIPick["AI 选股<br/>明日推荐"]
            WeChatBot["企微机器人<br/>回调 · 解密 · 应答"]
        end
    end

    subgraph Storage["<b>存储层</b>"]
        DB[("SQLite / PostgreSQL")]
        Redis[("Redis 缓存<br/>实时价格")]
    end

    subgraph External["<b>外部服务</b>"]
        AkShare["akshare<br/>A 股数据源"]
        DeepSeek_API["DeepSeek API<br/>AI 分析 · 选股"]
        WeChat_API["企业微信 API<br/>消息推送 · 机器人"]
    end

    UI --> API
    WS_Client <-->|实时数据| WS_Hub
    API --> Services
    Services --> DataService & FactorEngine & RankingService & TradingEngine & AIPick & AIReport & WeChatBot
    DataService --> AkShare
    AIPick --> DeepSeek_API
    AIReport --> DeepSeek_API
    WeChatBot --> WeChat_API
    Services --> DB
    TradingEngine --> Redis
    Scheduler --> DataService & TradingEngine & AIPick
```

---

## 数据流

```mermaid
sequenceDiagram
    participant Cron as 定时任务
    participant DS as 数据服务
    participant FE as 因子引擎
    participant RS as 排名服务
    participant TE as 交易引擎
    participant WS as WebSocket
    participant WX as 企微通知

    Note over Cron, WX: 每日数据刷新 (13:05, 15:05)
    Cron->>DS: 拉取全市场行情
    DS->>FE: 原始数据入库
    FE->>RS: 计算 16 个因子
    RS->>RS: 加权评分 → 行业中性化 → 排名
    RS-->>WX: 推送 Top 10 排名

    Note over Cron, WS: 盘中每 5 分钟 (09:35-14:55)
    Cron->>TE: 检查止损 / 止盈
    TE->>WS: 广播交易事件
    WS-->>Frontend: 实时更新持仓

    Note over Cron, WX: 盘后更新 (15:05)
    Cron->>TE: 更新 ATR 止损线
    TE->>WS: 推送当日盈亏
    TE-->>WX: 发送当日交易总结

    Note over Cron, WX: AI 明日推荐 (14:30)
    Cron->>DS: 采集实时市场快照
    DS->>DS: DeepSeek 分析选股
    DS-->>WX: 推送明日推荐标的
```

---

## AI 明日推荐

每日 14:30 自动触发，AI 基于当天实时行情选出次日可能上涨的标的。

```mermaid
sequenceDiagram
    participant Cron as 定时任务 (14:30)
    participant Snap as 行情采集
    participant DS as DeepSeek API
    participant DB as 数据库
    participant WX as 企微推送
    participant BT as 次日回测

    Note over Cron, BT: 14:30 选股流程
    Cron->>Snap: 采集市场快照
    Snap->>Snap: 大盘指数 · 板块涨跌 · 涨跌分布
    Snap->>Snap: 涨停板 · 成交量 · 活跃个股
    Snap->>DS: 构建 Prompt → AI 分析
    DS-->>Cron: 0-5 只推荐标的 (JSON)
    Cron->>DB: 存储推荐结果
    Cron-->>WX: 推送推荐到企微群

    Note over Cron, BT: 次日 9:26 / 15:05 回测
    BT->>DB: 回填开盘价 / 收盘价
    BT->>DB: 计算涨跌幅 → 更新战绩
```

### 数据采集范围

| 维度 | 内容 |
|------|------|
| 大盘指数 | 上证 / 深证 / 创业板 / 科创50 实时涨跌幅 |
| 板块表现 | 行业板块涨跌榜 |
| 涨跌分布 | 上涨 / 平盘 / 下跌家数，涨停 / 跌停家数 |
| 成交量 | 今日成交额 vs 前 5 日均值 |
| 活跃个股 | 各行业成交量前列个股（按行业分组） |
| 涨停板 | 当日涨停个股（按行业分组） |

### 前端页面

访问 `/ai-recommend` 查看：
- 今日推荐列表 + AI 市场概况
- 历史战绩统计（命中率、平均收益）
- 按日期回溯历史推荐

---

## 模拟交易引擎

```mermaid
stateDiagram-v2
    [*] --> 待机

    待机 --> 盘前检查: 09:25

    state 盘前检查 {
        [*] --> 获取排名
        获取排名 --> 检查调仓: 周一
        获取排名 --> 识别新买: 非周一
        检查调仓 --> 卖出掉出排名股票
        卖出掉出排名股票 --> 识别新买
        识别新买 --> 下单买入
        下单买入 --> [*]
    }

    盘前检查 --> 盘中监控: 09:35

    state 盘中监控 {
        [*] --> 检查止损
        [*] --> 检查止盈
        检查止损 --> 价格触及止损线: 触发
        价格触及止损线 --> 全仓卖出
        检查止盈 --> 涨幅达15%: 触发
        涨幅达15% --> 卖出1/3
        检查止盈 --> 涨幅达30%: 触发
        涨幅达30% --> 再卖1/3
        检查止盈 --> 从高点回撤5%: 触发
        从高点回撤5% --> 清仓剩余
        全仓卖出 --> 记录交易
        卖出1/3 --> 记录交易
        清仓剩余 --> 记录交易
        记录交易 --> WebSocket推送
    }

    盘中监控 --> 盘后更新: 15:05

    state 盘后更新 {
        [*] --> 更新最高价记录
        更新最高价记录 --> 重算ATR止损
        重算ATR止损 --> 计算账户净值
        计算账户净值 --> 推送微信总结
        推送微信总结 --> [*]
    }

    盘后更新 --> 待机
```

### 仓位管理规则

| 排名区间 | 初始仓位 | 资金占比 | 加仓条件 |
|---------|---------|---------|---------|
| #1 - #3 | Tier 1 | 12% | +8% → Tier 2 (+50%)，+15% → Tier 3 (+50%) |
| #4 - #7 | Tier 1 | 10% | 同上 |
| #8 - #10 | Tier 1 | 8% | 同上 |

- **止损**: `close - 2×ATR(14)`，只升不降的棘轮机制
- **止盈**: +15% 卖 1/3，+30% 卖 1/3，从最高点回撤 5% 清仓
- **调仓**: 每周一检查，排名跌出 Top 15 则卖出

---

## 多因子策略

### 因子体系

```mermaid
graph LR
    subgraph 技术面["<b>技术面</b>"]
        MA["均线交叉<br/>MA Crossover"]
        MACD["MACD"]
        RSI["RSI"]
        KDJ["KDJ"]
        BOL["布林带<br/>Bollinger"]
        VOL["量比<br/>Volume"]
    end

    subgraph 基本面["<b>基本面</b>"]
        PE["市盈率<br/>PE"]
        PB["市净率<br/>PB"]
        ROE["净资产收益率<br/>ROE"]
        REV["营收增长<br/>Revenue"]
        PROF["利润增长<br/>Profit"]
        DEBT["资产负债率<br/>Debt"]
    end

    subgraph 情绪面["<b>情绪面</b>"]
        TURN["换手率<br/>Turnover"]
        FLOW["资金流向<br/>Capital Flow"]
        M5["5日动量<br/>Momentum 5d"]
        M20["20日动量<br/>Momentum 20d"]
    end

    综合评分["<b>综合评分</b><br/>加权求和"]
    MA & MACD & RSI & KDJ & BOL & VOL --> 技术面评分
    PE & PB & ROE & REV & PROF & DEBT --> 基本面评分
    TURN & FLOW & M5 & M20 --> 情绪面评分
    技术面评分 --> 综合评分
    基本面评分 --> 综合评分
    情绪面评分 --> 综合评分
```

### 策略权重对比

<details>
<summary><b>均衡策略</b> — 技术 40% + 基本面 40% + 情绪 20%（点击展开）</summary>

| 维度 | 因子 | 权重 | 说明 |
|------|------|------|------|
| **技术 40%** | 均线交叉 | 0.25 | MA5/MA10/MA20 多周期交叉 |
| | MACD | 0.25 | DIF/DEA 金叉死叉 + 柱状变化 |
| | RSI | 0.20 | 超买超卖判断 |
| | KDJ | 0.15 | J 线拐点识别 |
| | 布林带 | 0.10 | 价格相对通道位置 |
| | 量比 | 0.05 | 成交量异动 |
| **基本面 40%** | ROE | 0.25 | 盈利能力核心指标 |
| | PE | 0.20 | 估值合理度 |
| | 营收增长 | 0.20 | 收入扩张速度 |
| | PB | 0.15 | 资产价值评估 |
| | 利润增长 | 0.15 | 盈利成长性 |
| | 资产负债率 | 0.05 | 财务健康度 |
| **情绪 20%** | 资金流向 | 0.35 | 主力资金进出 |
| | 换手率 | 0.25 | 市场活跃度 |
| | 5日动量 | 0.20 | 短期趋势强度 |
| | 20日动量 | 0.20 | 中期趋势强度 |

</details>

<details>
<summary><b>动量策略</b> — 技术 45% + 基本面 20% + 情绪 35%（点击展开）</summary>

| 维度 | 因子 | 权重 | 说明 |
|------|------|------|------|
| **技术 45%** | 均线交叉 | 0.30 | 趋势识别权重最高 |
| | MACD | 0.30 | 动量确认 |
| | RSI | 0.15 | 避免追高 |
| | KDJ | 0.10 | |
| | 布林带 | 0.10 | |
| | 量比 | 0.05 | |
| **基本面 20%** | 利润增长 | 0.25 | 成长股筛选 |
| | 营收增长 | 0.20 | |
| | ROE | 0.20 | |
| | PE | 0.15 | |
| | PB | 0.10 | |
| | 资产负债率 | 0.10 | |
| **情绪 35%** | 资金流向 | 0.40 | 跟踪主力动向 |
| | 换手率 | 0.30 | 量能配合 |
| | 5日动量 | 0.15 | |
| | 20日动量 | 0.15 | |

</details>

<details>
<summary><b>价值策略</b> — 技术 20% + 基本面 65% + 情绪 15%（点击展开）</summary>

| 维度 | 因子 | 权重 | 说明 |
|------|------|------|------|
| **技术 20%** | 均线交叉 | 0.30 | 仅确认趋势方向 |
| | MACD | 0.25 | |
| | RSI | 0.20 | |
| | KDJ | 0.10 | |
| | 布林带 | 0.10 | |
| | 量比 | 0.05 | |
| **基本面 65%** | ROE | 0.30 | 高 ROE 为核心 |
| | PE | 0.25 | 低估值筛选 |
| | PB | 0.20 | 破净机会 |
| | 营收增长 | 0.10 | |
| | 利润增长 | 0.10 | |
| | 资产负债率 | 0.05 | |
| **情绪 15%** | 资金流向 | 0.30 | |
| | 5日动量 | 0.25 | |
| | 20日动量 | 0.25 | |
| | 换手率 | 0.20 | |

</details>

### 自定义策略

在 `backend/strategies/` 下新建 YAML 文件即可：

```yaml
name: "我的策略"
description: "自定义因子权重"
categories:
  technical:
    weight: 0.5
    factors:
      ma_crossover: 0.30
      macd: 0.30
      rsi: 0.20
      kdj: 0.10
      bollinger: 0.05
      volume_ratio: 0.05
  fundamental:
    weight: 0.3
    factors:
      pe_score: 0.25
      pb_score: 0.15
      roe_score: 0.25
      revenue_growth_score: 0.15
      profit_growth_score: 0.15
      debt_ratio_score: 0.05
  sentiment:
    weight: 0.2
    factors:
      turnover_score: 0.25
      capital_flow_score: 0.35
      momentum_5d_score: 0.20
      momentum_20d_score: 0.20
```

---

## 企业微信机器人

### 配置流程

```mermaid
graph LR
    A[创建自建应用] --> B[获取 Corp ID / AgentId / Secret]
    B --> C[配置回调 URL]
    C --> D[设置 Token + AES Key]
    D --> E[填写 .env]
    E --> F[群内 @机器人 测试]

    style A fill:#4A90D9,color:#fff
    style F fill:#27AE60,color:#fff
```

### 指令列表

| 指令 | 示例 | 说明 |
|------|------|------|
| `帮助` | `@机器人 帮助` | 显示所有可用指令 |
| `<代码>` | `@机器人 000001` | 查询实时行情 + 因子评分 |
| `<名称>` | `@机器人 平安银行` | 模糊搜索股票 |
| `<代码> 评分` | `@机器人 600519 评分` | 详细因子评分 |
| `<代码> 分析` | `@机器人 600519 分析` | AI 深度分析 (DeepSeek) |

### 对话示例

```
用户: @盗劫 000001
机器人:  平安银行 (000001)
        当前价: 10.68  🔴 +0.00%
        成交量: 66万手  成交额: 0.00亿
        ---
        因子评分: 60.5 (排名 #600)
          技术面: 1.8  基本面: 19.4  情绪面: -0.3
        ---
        发送 "000001 分析" 获取 AI 深度点评
```

---

## 快速开始

### 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | >= 3.11 | 后端运行 |
| Node.js | >= 18 | 前端构建 |
| Redis | 可选 | 实时价格缓存 |
| PostgreSQL | 可选 | 生产级数据库 |

### 一键启动

```bash
git clone <your-repo-url>
cd shares
python3 scripts/run.py
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| 后端 API | http://localhost:8000 |
| Swagger 文档 | http://localhost:8000/api/docs |
| ReDoc 文档 | http://localhost:8000/api/redoc |

### 手动启动

```bash
# 后端
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env        # 编辑 .env 配置
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端 (新终端)
cd frontend
npm install
npm run dev
```

### Docker 部署

```bash
cd scripts
docker-compose -f docker-compose.dev.yml up -d

# 服务
#   web:      http://localhost:8000  (后端 + PostgreSQL)
#   frontend: http://localhost:5173  (前端 Vite dev)
#   db:       localhost:5432         (PostgreSQL)
```

---

## 环境变量

`backend/.env` 配置说明：

```bash
# ===== 基础配置 =====
APP_ENV=development          # 环境: development / production
DEBUG=true                   # 调试模式
HOST=0.0.0.0                 # 监听地址
PORT=8000                    # 监听端口

# ===== 数据库 =====
# SQLite (默认)
DATABASE_URL=sqlite+aiosqlite:///./stock_picker.db
# PostgreSQL (生产推荐)
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/stock_picker

REDIS_URL=redis://localhost:6379/0

# ===== 数据刷新 =====
DATA_REFRESH_HOURS=13,15     # CST 时间，逗号分隔
DATA_REFRESH_MINUTES=5,5     # 对应分钟
CACHE_TTL=3600               # 缓存过期秒数

# ===== 微信群通知 =====
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY
NOTIFICATION_TOP_N=10        # 推送排名前 N

# ===== AI 分析 (DeepSeek) =====
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# ===== 企业微信机器人 =====
WECHAT_CORP_ID=ww-your-corp-id
WECHAT_APP_AGENT_ID=1000002
WECHAT_APP_SECRET=your-secret
WECHAT_TOKEN=your-token
WECHAT_ENCODING_AES_KEY=your-aes-key
```

---

## API 接口

| 模块 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 健康检查 | `GET` | `/api/health` | 服务状态 |
| **股票数据** | | | |
| | `GET` | `/api/stocks/` | 股票列表 (分页) |
| | `GET` | `/api/stocks/search` | 搜索股票 |
| | `GET` | `/api/stocks/{code}` | 股票详情 |
| | `GET` | `/api/stocks/{code}/kline` | K 线数据 |
| **因子分析** | | | |
| | `POST` | `/api/factors/compute` | 计算因子 |
| | `GET` | `/api/factors/{code}` | 获取因子值 |
| **排名** | | | |
| | `GET` | `/api/ranking/` | 策略排名列表 |
| | `GET` | `/api/ranking/{strategy}` | 指定策略排名 |
| **策略** | | | |
| | `GET` | `/api/strategy/` | 可用策略列表 |
| **行业** | | | |
| | `GET` | `/api/sectors/` | 行业板块数据 |
| | `GET` | `/api/sectors/{code}/stocks` | 板块内股票 |
| **回测** | | | |
| | `POST` | `/api/backtest/run` | 运行回测 |
| **模拟交易** | | | |
| | `GET` | `/api/trading/account` | 账户状态 |
| | `GET` | `/api/trading/positions` | 当前持仓 |
| | `GET` | `/api/trading/logs` | 交易日志 |
| | `POST` | `/api/trading/start` | 启动交易 |
| | `POST` | `/api/trading/stop` | 停止交易 |
| | `POST` | `/api/trading/reset` | 重置账户 |
| **实时监控** | | | |
| | `WS` | `/api/ws/monitor` | WebSocket 实时推送 |
| **AI 推荐** | | | |
| | `GET` | `/api/ai-picks/today` | 今日推荐 |
| | `GET` | `/api/ai-picks/history` | 历史推荐 (分页) |
| | `GET` | `/api/ai-picks/stats` | 战绩统计 |
| **实时监控** | | | |
| | `WS` | `/api/ws/monitor` | WebSocket 实时推送 |
| **企业微信** | | | |
| | `GET` | `/api/wechat/callback` | 回调验证 |
| | `POST` | `/api/wechat/callback` | 消息接收 |

> 完整接口文档: http://localhost:8000/api/docs (Swagger) 或 http://localhost:8000/api/redoc

---

## 项目结构

```
shares/
├── backend/                     # 后端服务
│   ├── app/
│   │   ├── api/                 # API 路由层
│   │   │   ├── health.py        #   健康检查
│   │   │   ├── stocks.py        #   股票数据
│   │   │   ├── factors.py       #   因子分析
│   │   │   ├── ranking.py       #   排名查询
│   │   │   ├── strategy.py      #   策略管理
│   │   │   ├── sectors.py       #   行业板块
│   │   │   ├── backtest.py      #   回测
│   │   │   ├── trading.py       #   模拟交易
│   │   │   ├── monitor.py       #   WebSocket 监控
│   │   │   ├── wechat.py        #   企微机器人回调
│   │   │   └── ai_picks.py      #   AI 明日推荐
│   │   ├── core/
│   │   │   ├── config.py        #   配置 (Pydantic Settings)
│   │   │   ├── database.py      #   数据库连接
│   │   │   ├── scheduler.py     #   定时任务
│   │   │   ├── websocket.py     #   MonitorHub 广播
│   │   │   ├── logging.py       #   日志 (Loguru)
│   │   │   ├── cache.py         #   缓存
│   │   │   └── redis.py         #   Redis 连接
│   │   ├── models/              # SQLAlchemy 数据模型
│   │   │   ├── stock.py         #   股票 · 日线 · 因子 · 排名
│   │   │   ├── trading.py       #   账户 · 持仓 · 交易日志
│   │   │   ├── alert.py         #   预警规则 · 预警记录
│   │   │   └── ai_pick.py       #   AI 选股记录
│   │   ├── schemas/             # Pydantic 请求/响应
│   │   ├── services/            # 业务逻辑
│   │   │   ├── data_service.py  #   数据同步 (21KB)
│   │   │   ├── factor_engine.py #   因子计算引擎 (25KB)
│   │   │   ├── ranking_service.py # 评分排名 (18KB)
│   │   │   ├── trading_service.py # 交易引擎 (27KB)
│   │   │   ├── wechat_bot.py    #   企微机器人 (11KB)
│   │   │   ├── ai_report_service.py # AI 分析
│   │   │   ├── backtest.py      #   回测引擎
│   │   │   ├── capital_flow.py  #   资金流向
│   │   │   ├── sector_service.py # 板块分析
│   │   │   ├── strategy_loader.py # 策略加载器
│   │   │   ├── notification_service.py # 微信通知
│   │   │   ├── ai_pick_service.py #   AI 选股 + 回测
│   │   │   └── data_providers/  #   数据源抽象
│   │   └── tasks/               # 定时任务定义
│   ├── strategies/              # YAML 策略配置
│   │   ├── default.yaml         #   均衡策略
│   │   ├── momentum.yaml        #   动量策略
│   │   └── value.yaml           #   价值策略
│   └── tests/                   # 单元测试
├── frontend/                    # Vue 3 前端
│   └── src/
│       ├── views/               # 页面视图
│       │   ├── StockList.vue    #   股票列表
│       │   ├── StockRanking.vue #   策略排名
│       │   ├── StockDetail.vue  #   个股详情 + K线
│       │   ├── FactorAnalysis.vue # 因子分析
│       │   ├── SectorRanking.vue # 行业排名
│       │   ├── TradingView.vue  #   模拟交易
│       │   ├── AIRecommendView.vue # AI 明日推荐
│       │   ├── AlertView.vue    #   智能预警
│       │   └── Settings.vue     #   设置
│       ├── components/          # 公共组件
│       ├── store/               # Pinia 状态
│       ├── api/                 # HTTP 封装
│       ├── utils/               # 工具 (WebSocket 客户端)
│       └── types/               # TypeScript 类型
├── data/                        # 数据库文件
├── docs/                        # 设计文档
└── scripts/                     # 启动 / 部署脚本
    ├── run.py                   #   一键启动
    ├── run.sh
    ├── deploy.sh
    └── docker-compose.dev.yml
```

---

## 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| **后端框架** | FastAPI + Uvicorn | 异步 Web 框架，自动 OpenAPI 文档 |
| **ORM** | SQLAlchemy 2.0 + aiosqlite | 异步数据库操作 |
| **数据库** | SQLite (开发) / PostgreSQL (生产) | 数据持久化 |
| **缓存** | Redis | 实时价格缓存 |
| **数据源** | akshare | 免费 A 股行情数据 |
| **调度** | APScheduler | 定时数据刷新、盘中监控 |
| **AI** | DeepSeek API | 个股智能分析 |
| **加密** | PyCryptodome | 企微 AES-128-CBC 消息加解密 |
| **HTTP** | httpx | 异步 HTTP 客户端 |
| **日志** | Loguru | 结构化日志 |
| **前端框架** | Vue 3 + TypeScript | 响应式 SPA |
| **UI 组件** | Element Plus | 表格、表单、弹窗 |
| **图表** | ECharts | K 线图、雷达图、因子分布 |
| **状态管理** | Pinia | 全局状态 |
| **构建** | Vite | 快速 HMR |
| **部署** | Docker + docker-compose | 容器化部署 |

---

## License

MIT
