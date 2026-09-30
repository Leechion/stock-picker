# QuantBlade 架构说明

> 本文档描述 2026-09 重构后的模块边界与协作契约。重构目标是消除重复实现、
> 让长任务可控可观测，**技术栈保持不变**（FastAPI + SQLite + APScheduler）。

## 1. 分层结构

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (Vue 3)                                            │
│    REST 查询/启动   +   WS /ws/monitor (job_progress)        │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│  API 层   app/api/*.py                                       │
│    只做：参数校验 → 调用 pipeline/job → 序列化响应             │
│    禁止：编排多步骤、直接写业务 SQL、asyncio.gather 重活       │
├──────────────────────────────────────────────────────────────┤
│  Pipeline 层   app/pipelines/*.py     ← 唯一的编排入口        │
│    职责：步骤顺序、进度上报、取消检查、事务边界                │
│    factor_pipeline / full_pipeline                           │
│    依赖 services + core，**不依赖 FastAPI**                   │
├──────────────────────────────────────────────────────────────┤
│  Domain 层   app/services/*.py                               │
│    纯计算与数据访问；不感知 HTTP / WS / 调度器                 │
├──────────────────────────────────────────────────────────────┤
│  基础设施   app/core/*.py                                    │
│    database · jobs(任务管理) · websocket · scheduler · config │
└──────────────────────────────────────────────────────────────┘
```

**依赖方向单向向下**，`app/pipelines` 与 `app/services` 均不得 import `app.api`。

## 2. 为什么要有 Pipeline 层

重构前，同一套「算因子 → 算排名 → 发预警」流程存在**三份各自演化的副本**：

| 位置 | 并发方式 | 缺陷 |
|---|---|---|
| `api/ranking.py::compute_ranking` | `gather` + Semaphore(10)，**共用一个 session** | `IllegalStateChangeError` 崩溃 |
| `api/factors.py::compute_factors` | **完全串行** `for code in codes` | 最慢的一份 |
| `core/scheduler.py::run_daily_ranking` | `gather` + Semaphore(20)，每协程独立 session | 只有这份被修过 |

三份代码里只有一份被修好，另外两份继续带着 bug 运行。现在三处全部委托给
`app.pipelines`，`tests/test_architecture.py` 用源码断言防止再次分裂。

## 3. 长任务模型：Job

### 3.1 契约

| 动作 | 接口 | 说明 |
|---|---|---|
| 启动 | `POST /api/jobs/{job_type}` | **立即**返回 `job_id`，不阻塞 |
| 查询 | `GET  /api/jobs/{job_id}` | 状态 + 进度（UI 轮询用） |
| 列表 | `GET  /api/jobs/` | 最近任务，支持 `job_type` 过滤 |
| 取消 | `POST /api/jobs/{job_id}/cancel` | 协作式取消，下一检查点停止 |
| 进度推送 | WS 频道 `job_progress` | 实时推送，无需轮询 |

兼容入口：`POST /api/rankings/compute` 与 `POST /api/factors/compute`
现在都是 `job_type=full_ranking` 的薄封装。

### 3.2 状态机

```
pending ──► running ──┬──► succeeded
                      ├──► failed      (含 traceback)
                      └──► cancelled   (协作式)
```

终态集合见 `app/models/job.py::TERMINAL_STATUSES`。

### 3.3 进度语义

`full_ranking` 把 0–100 切成三段，UI 进度条单调递增：

| 阶段 | 区间 | 内容 |
|---|---|---|
| 因子计算 | 0–70 | 每 25 只股票上报一次 |
| 排名计算 | 70–95 | 逐策略上报（3 个策略） |
| 预警检查 | 95–100 | best-effort，失败不影响任务成功 |

> 单独调用 `factors` / `rankings` 时各自使用 0–100。

### 3.4 三个关键设计约束

**① 每个协程独立 session。** `AsyncSession` 不可跨 `asyncio.gather` 共享。
`_compute_one` 内部 `async with AsyncSessionLocal()` 自开自关。

**② 取消检查必须在信号量之内。** 所有 worker 协程在启动时就全部创建，
若只在进入前检查一次，取消信号到达时它们早已全部通过检查。
实测：只检查一次时，cancel 在 15% 发出仍跑到 100%；在
`async with sem` 之后补检查后，cancel 能立即止损（475/3018 处停住）。

**③ 进度写入使用独立短会话。** 进度回调在工作协程内触发，不能复用
pipeline 自己的 session（会交错 commit），因此 `_update_progress` 每次
自开一个 session。且进度写失败**绝不允许**杀死任务。

## 4. 数据库访问约定

```python
# app/core/database.py
engine = create_async_engine(_db_url, echo=settings.sql_echo, ...)
```

- **`echo` 由 `SQL_ECHO` 控制，默认关闭**，与 `DEBUG` 解耦。
  重构前 `echo=settings.debug`，在 `DEBUG=true` 下跑因子任务会刷出
  **8.5 MB 日志 / 16 分钟**，I/O 本身成为主要耗时。
- `autoflush=False`：长任务循环加载数千行，避免隐式 flush 开销。
- 数据库迁移用 Alembic（`backend/migrations/`）。

### 迁移操作

```bash
cd backend
.venv/bin/python -m alembic upgrade head     # 空库建表
.venv/bin/python -m alembic stamp head       # 线上已有库：只打标记，不建表
```

> ⚠️ **环境注意**：本机 `.venv/bin/alembic`、`.venv/bin/pytest` 等入口脚本的
> shebang 指向项目移动前的旧路径，直接执行会报 `bad interpreter`。
> 请统一使用 `.venv/bin/python -m alembic` / `-m pytest`。
> 根治办法是重建 venv。

## 5. 可观测性

- **WebSocket 频道**：`positions` `account` `trades` `market` `system`
  `alerts` `sync_progress` `job_progress`
- **任务持久化**：`jobs` 表记录参数、进度、结果、错误栈，重启后可追溯
- **异常不再静默**：原先 21 处裸 `except Exception: pass` 已补日志；
  只有明确的 best-effort 路径（Redis 不可用、外部行情源超时）才吞异常，
  且必定留痕

## 6. 已知限制

| 限制 | 影响 | 正解方向 |
|---|---|---|
| 进程内取消注册表 | 多 uvicorn worker 下，A 进程的取消无法停止 B 进程的任务 | 注册表移入 Redis；job 行仍是唯一事实来源 |
| 下单锁为进程内 `asyncio.Lock` | 多 worker 下超卖防护失效 | `SELECT ... FOR UPDATE` 行锁或 Redis 分布式锁 |
| SQLite 单写者 | 并发写会串行化 | 数据量增长后迁 PostgreSQL |
| 无鉴权体系 | 所有 API 开放；WS 鉴权默认关闭 | 引入统一认证；`WS_AUTH_ENABLED=true` 启用现有开关 |
| `main.py` 仍用 `create_all` | 与 Alembic 双写 schema 可能漂移 | 改为启动时 `alembic upgrade head` |

## 7. 测试布局

| 文件 | 覆盖 |
|---|---|
| `test_architecture.py` | **结构守卫**：禁止 API/调度器重新实现 pipeline |
| `test_jobs.py` | 任务生命周期：立即返回、进度、取消、失败、清理 |
| `test_factor_pipeline.py` | 并发隔离、取消**在信号量内**生效、取消时不写库 |
| `test_sync_cancel.py` | 数据同步取消语义（不谎报完成） |
| `test_trading_concurrency.py` | 下单并发不超卖、WS 鉴权 |
| `test_migrations.py` | 迁移覆盖 ORM 全部表、可升降级 |
| `test_ranking_search.py` | 搜索 SQL 括号正确性、空串防护 |
| `test_ai_pick_backtest.py` | 回测按真实交易日、幂等、可重试 |

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

## 8. 新增一个长任务的步骤

1. 在 `app/pipelines/` 写 pipeline，签名固定为 `(ctx: JobContext, **params)`
2. 在函数体内用 `ctx.report(current, total, message)` 上报进度
3. 在每个步骤边界与**并发 worker 内部**调用 `ctx.raise_if_cancelled()`
4. 在 `app/api/jobs.py::_resolve_runner` 注册 `job_type`
5. 需要定时触发则在 `app/core/scheduler.py` 调用同一 pipeline
6. 补测试：`test_architecture.py` 的结构守卫会自动覆盖边界检查
