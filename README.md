# A股量化多因子选股系统

一个基于 FastAPI + Vue 3 的生产级 A 股量化选股平台。

## 功能

- **多因子选股**：技术面 + 基本面 + 情绪面 15+ 因子综合评分
- **实时行情**：通过 AKShare 免费获取 A 股数据
- **智能排名**：因子标准化、加权打分、行业中性化
- **可视化分析**：K 线图、因子雷达图、行业分布
- **定时更新**：每日收盘后自动更新数据

## 快速开始

```bash
# 1. 克隆并安装后端
cd backend
poetry install
cp .env.example .env
python -m app.main

# 2. 安装前端
cd ../frontend
npm install
npm run dev
```

访问 http://localhost:5173

## 项目结构

```
stock-picker/
├── backend/              # FastAPI 后端
│   ├── app/
│   │   ├── core/         # 配置、日志、安全
│   │   ├── models/       # 数据库模型
│   │   ├── schemas/      # Pydantic 模型
│   │   ├── services/     # 业务逻辑
│   │   │   ├── data/     # 数据获取、存储
│   │   │   ├── factor/   # 因子计算引擎
│   │   │   └── ranking/  # 评分与排名
│   │   ├── api/          # 路由
│   │   └── main.py       # 入口
│   ├── alembic/          # 数据库迁移
│   ├── tests/
│   └── pyproject.toml
├── frontend/             # Vue 3 + Element Plus
│   ├── src/
│   │   ├── api/          # API 客户端
│   │   ├── assets/       # 静态资源
│   │   ├── components/   # 通用组件
│   │   ├── views/        # 页面
│   │   ├── store/        # Pinia 状态管理
│   │   └── router/       # 路由
│   └── package.json
```

## 技术栈

- **后端**: FastAPI + SQLAlchemy 2.0 + SQLite/PostgreSQL
- **前端**: Vue 3 + Vite + Element Plus + Pinia + ECharts
- **数据**: AKShare (免费 A 股数据源)
- **任务调度**: APScheduler
- **部署**: Docker + docker-compose