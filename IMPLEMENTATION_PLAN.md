## 股票量化多因子选股系统 - 实施计划

> 版本: v0.1 | 最后更新: 2026-05-24

---

## 系统架构

```
┌──────────────────────────────────────────────────────────┐
│                    前端 (Vue 3 + Element Plus)              │
│  StockRanking | StockList | StockDetail | FactorAnalysis   │
└────────────────────┬─────────────────────────────────────┘
                     │ axios → /api/*
                     ▼
┌──────────────────────────────────────────────────────────┐
│               后端 (FastAPI + SQLAlchemy Async)             │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ data_svc │→ │factor_engine │→ │ ranking_service     │  │
│  └────┬─────┘  └──────┬───────┘  └──────────┬──────────┘  │
│       │               │                      │            │
│  AKShare  pandas    standardized factors    rankings     │
│       │               │                      │            │
│  ┌────┴───────────────┴──────────────────────┴──────────┐  │
│  │              PostgreSQL / SQLite (async)               │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## 因子体系 (15个因子)

### 技术面 (6个)
| #   | 因子名称      | 计算方法                         | 方向   |
|-----|-------------|----------------------------------|--------|
| T1  | MA Crossover | MA5 > MA20 > MA60: bull 1; MA5<MA20<MA60: bear -1; else 0 | 双向   |
| T2  | MACD Histogram | DIF(12,26,9) → 柱状图趋势       | 多头   |
| T3  | RSI-14      | 14日RSI → 0-1标准化             | 双向   |
| T4  | KDJ         | 933 KDJ → J<10多头, J>90空头   | 双向   |
| T5  | Bollinger Position | (Close-Lower)/(Upper-Lower)  | 多头 breakout |
| T6  | Volume Ratio | Vol_5MA / Vol_20MA              | 多头放量 |

### 基本面 (6个)
| #   | 因子名称           | 计算方法                    | 方向   |
|-----|------------------|----------------------------|--------|
| F1  | PE Score         | 行业PE TTM百分位反序         | 低PE好 |
| F2  | PB Score         | 行业PB百分位反序             | 低PB好 |
| F3  | ROE Score        | ROE(TTM)标准化              | 高ROE好|
| F4  | Revenue Growth   | 营收同比增速                 | 高增长好|
| F5  | Profit Growth    | 净利润同比增速               | 高增长好|
| F6  | Debt Ratio       | 资产负债率 → 适中最优        | 倒U型  |

### 情绪面 (3个)
| #   | 因子名称        | 计算方法                     | 方向   |
|-----|---------------|------------------------------|--------|
| S1  | Turnover Rate | 换手率Z-score                | 适度好 |
| S2  | Capital Flow  | 主力资金净流入率              | 净流入好|
| S3  | Momentum      | 5日/20日收益率加权            | 多头   |

### 评分权重
- 技术面: 0.4
- 基本面: 0.4
- 情绪面: 0.2

---

## 文件清单

### 后端 (/backend)
```
backend/
├── pyproject.toml          [x] 已有
├── .env.example            [x] 已有
├── .gitignore              [x] 已有
├── app/
│   ├── main.py             [x] 骨架
│   ├── core/
│   │   ├── config.py       [x] pydantic-settings
│   │   ├── database.py     [x] async SQLAlchemy
│   │   └── logging.py      [x] loguru
│   ├── models/
│   │   └── stock.py        [x] ORM models
│   ├── schemas/
│   │   └── stock.py        [x] Pydantic
│   ├── services/
│   │   ├── data_service.py [x]
│   │   ├── factor_engine.py [x]
│   │   ├── scoring.py      [x]
│   │   └── ranking_service.py [x]
│   ├── api/
│   │   ├── health.py       [x] 骨架
│   │   ├── stocks.py       [x] 骨架
│   │   ├── factors.py      [x] 骨架
│   │   └── ranking.py      [x] 骨架
│   └── tasks/
│       └── scheduler.py    [x]
├── tests/
│   └── test_health.py      [x]
└── alembic/                [] 已有
```

### 前端 (/frontend)
```
frontend/
├── package.json            [x] 已有
├── vite.config.ts          [x] 已有
├── tsconfig.json           [x] 已有
├── index.html              [x] 已有
├── src/
│   ├── main.ts             [x]
│   ├── App.vue             [x]
│   ├── router/             [x]
│   ├── api/                [x]
│   ├── store/              [x]
│   ├── views/              [x]
│   ├── components/         [x]
│   └── utils/              [x]
└── .gitignore              [x] 已有
```

---

## 任务分配

| 任务ID | Agent | 状态 | 负责内容 |
|--------|-------|------|---------|
| bg_0d4f7236 | unspecified-high | ✅ 已完成 | 后端: data_service, ranking, API路由, 调度器, 测试 |
| bg_0a631066 | unspecified-high | ✅ 已完成 | 前端: Vue页面, 组件, ECharts, Pinia |
| bg_e51b1359 | ultrabrain | ✅ 已完成 | 因子引擎: 15个因子计算, 标准化, 打分 |

---

## 后续步骤

1. ✅ 项目骨架搭建 (backend + frontend)
2. 🔄 等待三个并行任务完成
3. 🔍 审查/集成生成的代码
4. 🔧 编写 Docker 配置
5. 🧪 设置 CI/CD
6. 📝 编写使用文档
7. 🚀 部署测试