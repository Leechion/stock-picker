# 设计文档：模拟交易机器人

## 概述

基于现有量化多因子选股系统，构建一个模拟交易机器人。根据策略排名自动执行金字塔加仓、ATR动态止损、混合止盈，全程模拟交易，预留券商实盘接口。

## 核心参数

| 参数 | 值 |
|------|-----|
| 初始资金 | 50万元 |
| 最大持仓 | 10只 |
| 仓位分配 | 金字塔（排名越高仓位越大） |
| 买入时机 | 排名更新后次日开盘 |
| 调仓频率 | 每周一开盘 |
| 止损 | ATR(14) 动态止损 |
| 止盈 | +15%卖1/3，+30%再卖1/3，从高点回撤5%清仓 |
| 通知 | 企微全部通知（买卖止损止盈） |
| 模式 | 模拟交易，预留券商接口 |

## 数据模型

### TradingAccount（模拟账户）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| initial_capital | Float | 初始资金（默认500000） |
| cash | Float | 可用现金 |
| total_value | Float | 账户总市值（cash + 持仓市值） |
| is_active | Boolean | 机器人是否运行中 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### Position（持仓记录）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| account_id | Integer FK | 关联账户 |
| code | String(10) | 股票代码 |
| name | String(20) | 股票名称 |
| shares | Integer | 当前持仓股数 |
| avg_cost | Float | 持仓均价 |
| open_price | Float | 首次开仓价 |
| high_since_open | Float | 开仓以来最高价（追踪止盈用） |
| atr_at_buy | Float | 买入时ATR(14) |
| stop_loss_price | Float | 当前止损价（只上移不下移） |
| tier | Integer | 加仓层数（1/2/3） |
| created_at | DateTime | 开仓时间 |
| updated_at | DateTime | 最后更新 |

### TradeLog（交易日志）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| account_id | Integer FK | 关联账户 |
| code | String(10) | 股票代码 |
| name | String(20) | 股票名称 |
| action | String(20) | 操作类型：buy / sell / stop_loss / take_profit |
| shares | Integer | 交易股数 |
| price | Float | 成交价 |
| amount | Float | 成交金额 |
| pnl | Float | 盈亏金额（卖出时） |
| reason | String(200) | 操作原因 |
| created_at | DateTime | 交易时间 |

## 仓位分配（金字塔）

按排名权重分配资金：

| 排名区间 | 单只权重 | 小计 |
|----------|---------|------|
| 1-3 | 12% | 36% |
| 4-7 | 10% | 40% |
| 8-10 | 8% | 24% |

### 加仓机制

当某只持仓盈利达到条件时可追加投入：
- 第1次加仓：盈利 ≥ 8%，追加原始仓位的 50%
- 第2次加仓：盈利 ≥ 15%，再追加原始仓位的 50%
- 最多3层（初始 + 2次加仓）
- 每次加仓后更新 avg_cost、stop_loss_price、tier

## ATR 动态止损

1. **买入时**：取 ATR(14) 最新值作为 `atr_at_buy`
2. **初始止损价**：`买入价 - 2 × ATR(14)`
3. **每日更新**：`止损价 = 当日收盘价 - 2 × ATR(14)`
   - 只上移（新止损价 > 旧止损价），不下移
4. **触发条件**：当前价 ≤ 止损价 → 全部卖出

## 混合止盈

### 固定比例止盈
- 盈利 ≥ +15%：卖出 1/3 仓位（四舍五入取整手）
- 盈利 ≥ +30%：再卖出 1/3 仓位
- 剩余 1/3 仓位继续持有

### 追踪止盈
- 每日更新 `high_since_open`（开仓以来最高收盘价）
- 当 `当前价 ≤ high_since_open × 0.95`（回撤5%）→ 清仓全部剩余

### 触发优先级
- 每日收盘后检查，固定止盈和追踪止盈互不排斥
- 分批卖出后，剩余仓位继续追踪止盈

## 交易流程

### 每日调度（APScheduler）

| 时间 | 任务 | 说明 |
|------|------|------|
| 09:25 | pre_market_check | 开盘前检查：排名、新买入标的、调仓判断 |
| 每5分钟 (09:35-14:55) | realtime_check | 实时止损止盈检查（仅周一至周五） |
| 15:05 | post_market_update | 收盘后更新止损价、最高价、账户市值，发送通知 |

### pre_market_check 逻辑
```
1. 获取当日最新排名（使用当前激活策略）
2. 如果今天是周一（调仓日）：
   a. 检查所有持仓，排名跌出前15的标记为卖出
   b. 开盘后执行卖出
3. 检查排名前10但未持仓的股票，开盘后执行买入
4. 检查加仓条件，满足则开盘后加仓
```

### realtime_check 逻辑
```
1. 对每只持仓拉取实时行情
2. 检查止损：当前价 ≤ stop_loss_price → 卖出并通知
3. 更新 high_since_open
4. 检查追踪止盈：回撤 ≥ 5% → 卖出并通知
5. 检查固定止盈：盈利达 +15% 或 +30% → 分批卖出并通知
```

### post_market_update 逻辑
```
1. 拉取当日收盘价
2. 更新 high_since_open（当日最高价比较）
3. 重新计算 ATR(14)，更新 stop_loss_price（只上移）
4. 计算账户总市值
5. 生成今日汇总，发送企微通知
```

## 模拟交易引擎

### Broker 接口（预留实盘扩展）

```python
class BaseBroker(ABC):
    @abstractmethod
    async def buy(self, code, shares, price) -> TradeResult: ...
    @abstractmethod
    async def sell(self, code, shares, price) -> TradeResult: ...

class SimBroker(BaseBroker):
    """模拟券商：本地记录，按传入价格成交"""
    ...

# 预留实盘券商
class TongDaXinBroker(BaseBroker):
    """通达信接口（TODO）"""
    ...
```

### 核心操作

```python
async def execute_buy(account, code, name, rank, price, atr):
    """按金字塔计算仓位，执行模拟买入"""
    weight = pyramid_weight(rank)
    amount = account.initial_capital * weight
    shares = int(amount / price / 100) * 100  # A股整手
    stop_loss = price - 2 * atr
    account.cash -= shares * price
    create_position(account_id, code, name, shares, price, stop_loss, atr)
    log_trade(account_id, code, name, "buy", shares, price, ...)
    notify_wechat(f"买入 {name}({code}) {shares}股 @ {price}")

async def execute_sell(position, price, reason, action="sell"):
    """卖出全部或部分仓位"""
    amount = position.shares * price
    pnl = (price - position.avg_cost) * position.shares
    account.cash += amount
    log_trade(..., pnl=pnl, reason=reason)
    notify_wechat(f"卖出 {position.name} 盈亏 {pnl:.0f} 原因: {reason}")
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/trading/account` | 获取账户信息（资金、市值、盈亏） |
| GET | `/api/trading/positions` | 当前持仓列表 |
| GET | `/api/trading/logs` | 交易日志（分页，?page=&page_size=） |
| POST | `/api/trading/start` | 启动交易机器人 |
| POST | `/api/trading/stop` | 停止交易机器人 |
| POST | `/api/trading/reset` | 重置模拟账户（清空持仓和日志） |

## 前端页面

新增「模拟交易」菜单项，路由 `/trading`。

### 页面布局

```
┌─────────────────────────────────────────────────┐
│ 账户概览卡片                                      │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ │
│ │ 总资产   │ │ 可用资金 │ │ 今日盈亏 │ │ 总盈亏  │ │
│ │ 512,340 │ │ 180,000 │ │ +2,340  │ │+12,340  │ │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ │
│ [启动] [停止] [重置]                              │
├─────────────────────────────────────────────────┤
│ 当前持仓（表格）                                   │
│ 代码 | 名称 | 持仓数 | 成本价 | 现价 | 盈亏% | 止损价 │
├─────────────────────────────────────────────────┤
│ 交易日志（表格，分页）                              │
│ 时间 | 操作 | 股票 | 价格 | 数量 | 金额 | 原因     │
└─────────────────────────────────────────────────┘
```

## 文件清单

### 后端新增文件
- `app/models/trading.py` — TradingAccount, Position, TradeLog 模型
- `app/services/trading_service.py` — 交易引擎核心逻辑
- `app/api/trading.py` — 交易 API 路由

### 后端修改文件
- `app/models/__init__.py` — 导入新模型
- `app/core/scheduler.py` — 添加交易调度任务
- `app/main.py` — 注册 trading 路由

### 前端新增文件
- `src/views/TradingView.vue` — 模拟交易页面
- `src/api/trading.ts` — 交易 API 调用

### 前端修改文件
- `src/router/index.ts` — 添加 /trading 路由
- `src/App.vue` — 菜单中添加「模拟交易」入口

## 实施顺序

1. **数据模型** — 创建 trading.py 模型，注册到数据库
2. **交易服务层** — 模拟券商、仓位管理、止损止盈引擎
3. **API 路由** — trading.py 端点
4. **调度集成** — APScheduler 添加交易任务
5. **前端页面** — TradingView.vue + trading.ts API
6. **菜单路由** — 注册到 App.vue 菜单和 router
