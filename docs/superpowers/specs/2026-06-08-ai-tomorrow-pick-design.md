# AI 明日选股推荐 — 设计文档

**日期**: 2026-06-08  
**状态**: 已确认

---

## 概述

每天下午 2:30，AI 基于当天实时市场行情，自主选出 0-5 只明天大概率上涨的股票。结果通过企微推送 + 前端页面展示，次日盘后自动回测追踪历史战绩。

## 核心原则

- **纯增量开发**，不修改任何现有业务逻辑代码
- 新增文件独立，数据模型独立，API 独立
- 仅在 `scheduler.py` 末尾新增 3 个 job 注册

## 一、架构

```
Scheduler (14:30)
  → ai_pick_service.collect_market_snapshot()  # 采集市场快照
  → ai_pick_service.build_prompt(snapshot)      # 构建 AI prompt
  → ai_pick_service.call_deepseek(prompt)       # 调 DeepSeek API
  → ai_pick_service.save_picks(result)          # 存储到 ai_picks 表
  → ai_pick_service.push_notification()         # 企微推送

次日 9:26  → backtest_ai_picks_open()   # 回填开盘价
次日 15:05 → backtest_ai_picks_close()  # 回填收盘价 + 计算涨跌幅
```

## 二、数据模型

新增 `ai_picks` 表：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| pick_date | DATE | 推荐日期 |
| code | VARCHAR(10) | 股票代码 |
| name | VARCHAR(50) | 股票名称 |
| reason | TEXT | AI 推荐理由 |
| confidence | VARCHAR(20) | high / medium / low |
| price_at_pick | FLOAT | 推荐时实时价格 |
| next_day_open | FLOAT | 次日开盘价 (盘后回填) |
| next_day_close | FLOAT | 次日收盘价 (盘后回填) |
| next_day_change_pct | FLOAT | 次日涨跌幅% (盘后回填) |
| backtest_at | DATETIME | 回测时间 |
| created_at | DATETIME | 创建时间 |

索引：`idx_ai_picks_date ON ai_picks(pick_date)`

## 三、市场行情数据采集

采集标准版数据（足够全面但不超过 context 限制）：

- 大盘指数：上证/深证/创业板/科创50 实时涨跌幅
- 板块涨跌榜 Top 10
- 涨跌分布：涨/平/跌家数
- 涨停/跌停家数
- 北向资金净流向
- 成交额 vs 前5日均值
- 龙虎榜活跃度 + 连板高度

## 四、DeepSeek Prompt 约束

- 传入市场快照 data
- 要求返回结构化 JSON：
  ```json
  {
    "market_summary": "一句话市场概况",
    "confidence": "high|medium|low",
    "picks": [
      {
        "code": "000001",
        "name": "平安银行",
        "reason": "银行板块今日资金持续流入...",
        "confidence": "high"
      }
    ]
  }
  ```
- picks 长度 0-5，AI 判断无机会时返回空数组
- 服务层做 JSON 解析校验，解析失败重试 1 次，仍失败则记录错误日志并跳过

## 五、定时任务

在 `register_scheduler()` 末尾新增（不改动已有 job）：

| 任务 | 时间 | 功能 |
|------|------|------|
| run_ai_pick_task | 14:30 mon-fri | 采集行情 → AI选股 → 存储 → 企微推送 |
| backtest_ai_picks_open | 9:26 mon-fri | 回填昨日推荐的开盘价 |
| backtest_ai_picks_close | 15:05 mon-fri | 回填收盘价 + 计算涨跌幅 |

## 六、API 路由

新增 `backend/app/api/ai_picks.py`，注册 prefix `/api`：

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/ai-picks/today` | 今日推荐（含 market_summary） |
| GET | `/api/ai-picks/history?page=1&page_size=20` | 历史推荐分页列表 |
| GET | `/api/ai-picks/stats` | 战绩统计：总次数、命中率、平均收益 |

## 七、企微推送格式

```
🤖 AI 明日选股推荐 (2026-06-08)

📊 市场概况：今日市场震荡上行，半导体板块领涨，北向资金净流入...

🏆 推荐标的 (AI 把握: 较高)

1. 600519 贵州茅台 — 当前价 ¥1,680
   消费板块龙头，北向资金连续3日净买入...

2. 000858 五粮液 — 当前价 ¥158
   ...

⚠️ 以上为 AI 基于实时行情数据的分析预测，仅供参考，不构成投资建议。
```

无推荐时：
```
🤖 AI 明日选股推荐 (2026-06-08)

📊 市场概况：今日市场普跌，情绪低迷，北向资金大幅流出...

⚠️ AI 判断今日不适合入场，建议观望。以上不构成投资建议。
```

## 八、前端页面

新增 `frontend/src/views/AIRecommendView.vue`，路由 `/ai-recommend`：

- 日期选择器（默认今天，可左右切换历史日期）
- 市场概况卡片
- 推荐标的列表（编号 + 代码 + 名称 + 理由 + 次日涨跌幅标记）
- 历史战绩统计卡片（总推荐次数、命中率、平均收益）
- 历史推荐表格（日期/推荐数/命中数/平均涨幅，点击跳转当日详情）

## 九、新增文件清单

| 文件 | 作用 | 类型 |
|------|------|------|
| `backend/app/models/ai_pick.py` | ai_picks 表模型 | 新增 |
| `backend/app/services/ai_pick_service.py` | 行情采集 + prompt + API调用 + 存储 + 推送 | 新增 |
| `backend/app/api/ai_picks.py` | API 路由 | 新增 |
| `backend/app/core/scheduler.py` | 新增 3 个 job（在文件末尾追加） | 修改 |
| `backend/app/main.py` | 注册 ai_picks router | 修改 |
| `frontend/src/views/AIRecommendView.vue` | 前端页面 | 新增 |
| `frontend/src/api/aiPicks.ts` | 前端 API 模块 | 新增 |
| `frontend/src/router/index.ts` | 新增路由 `/ai-recommend` | 修改 |

## 十、错误处理

- DeepSeek API 调用失败 → 记录日志，本次跳过，不影响其他定时任务
- JSON 解析失败 → 重试 1 次，仍失败则记录原始返回 + 错误日志
- 行情数据采集部分失败 → 能采多少采多少，在 prompt 中标明缺失项
- 次日回测找不到价格 → 标记为 null，前端显示 "-"
- 非交易日（节假日）无行情数据 → 静默跳过
