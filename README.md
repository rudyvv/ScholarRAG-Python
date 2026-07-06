<p align="center">
  <img src="docs/logo.png" alt="ScholarRAG" width="200"/>
</p>

<h1 align="center">ScholarRAG</h1>

<p align="center">
  <em>面向高校实验室的多租户 RAG 智能知识库平台</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python" alt="Python 3.11"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Vue_3-4FC08D?logo=vuedotjs" alt="Vue 3"/>
  <img src="https://img.shields.io/badge/Celery-37814A?logo=celery" alt="Celery"/>
  <img src="https://img.shields.io/badge/Elasticsearch-8-005571?logo=elasticsearch" alt="Elasticsearch 8"/>
  <img src="https://img.shields.io/badge/Milvus-2.4-00A1EA?logo=milvus" alt="Milvus 2.4"/>
</p>

---

## 目录

- [项目简介](#项目简介)
- [系统架构](#系统架构)
- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [开发指南](#开发指南)

---

## 项目简介

**ScholarRAG** 是一个面向高校实验室场景的多租户 RAG 智能知识库平台。平台支持上传论文、项目资料、实验报告、课题文档等非结构化资料，构建实验室私域知识库，实现从 **文档上传 -> 文档解析 -> 文本分块 -> 向量化 -> 混合检索 -> 大模型生成** 的完整 RAG 流程。

平台围绕实验室常见的知识管理与科研问答需求设计，支持多格式资料解析、异步文档处理、关键词与语义双路检索、Cross-Encoder 重排序、基于来源片段的问答生成、多轮会话上下文管理以及组织标签维度的数据访问控制。

### 核心能力

| 能力 | 说明 |
|------|------|
| 多格式文档解析 | 支持 PDF、DOCX、XLSX、PPTX、CSV、Markdown、文本及多种代码文件解析 |
| 自适应文本分块 | 针对 Markdown、代码、PDF、通用文本采用不同分块策略，保留片段元数据 |
| 混合检索 | Elasticsearch BM25 全文检索 + Milvus 向量检索 + RRF 融合 + Cross-Encoder 重排序 |
| RAG 智能问答 | 基于 Function Calling 思路进行意图识别、查询改写和检索增强生成 |
| 异步文档处理 | Celery + RabbitMQ 处理解析、分块、索引构建和向量入库任务 |
| 多租户管理 | JWT 认证、组织标签、文档公开状态与后台用户管理 |
| 流式交互体验 | 基于 SSE 实现回答流式输出，并展示引用来源片段 |

---

## 系统架构

```text
┌─────────────────────────────────────────────────────────┐
│                     用户 Web 端                         │
├─────────────────────────────────────────────────────────┤
│                 Vue 3 + TypeScript + Naive UI           │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP / SSE
┌───────────────────────▼─────────────────────────────────┐
│                    FastAPI 服务层                        │
├───────────┬──────────┬──────────┬───────────────────────┤
│  Auth API │  Doc API │ Search   │ Chat / Ask Stream     │
│  认证鉴权 │ 文档管理 │ 混合检索 │ RAG 问答与流式输出     │
└───────────┴──────────┴──────────┴───────────────────────┘
             │            │                  │
    ┌────────┴────────┐  │      ┌───────────┴───────────┐
    │  MySQL 8.0      │  │      │   OpenAI 兼容模型服务  │
    │  用户/文档/会话  │  │      ├───────────────────────┤
    └─────────────────┘  │      │  Qwen3-8B Chat         │
    ┌─────────────────┐  │      │  BGE-M3 Embedding      │
    │  Redis 7        │  │      │  BGE Reranker          │
    │  上传状态/缓存   │  │      └───────────────────────┘
    └─────────────────┘  │
    ┌─────────────────┐  │       ┌──────────────────────┐
    │  MinIO          │  │       │  Celery Worker       │
    │  原始文件存储    │  │       │  文档解析/向量化      │
    └─────────────────┘  │       └──────┬───────────────┘
                         │              │ RabbitMQ
    ┌─────────────────┐  │              │
    │ Elasticsearch 8 │◄─┘              │
    │ BM25 + IK 分词  │                 │
    └─────────────────┘                 │
    ┌─────────────────┐                 │
    │ Milvus 2.4      │◄────────────────┘
    │ IVF_FLAT + IP   │
    └─────────────────┘
```

### RAG 问答流程

```text
用户提问
  ↓
读取最近会话上下文
  ↓
LLM Function Calling 判断是否需要检索知识库
  ↓
需要检索时结合历史对话进行查询改写
  ↓
Elasticsearch BM25 关键词召回 + Milvus 向量语义召回
  ↓
RRF 融合双路结果
  ↓
BGE-reranker-v2-m3 Cross-Encoder 重排序
  ↓
构造带来源片段的 Prompt
  ↓
大模型生成回答并通过 SSE 流式返回
```

---

## 核心功能

### 大文件上传与异步处理

- 基于 MinIO Multipart Upload 实现文件分片上传，分片大小默认为 5 MiB。
- 使用 Redis 记录上传会话、已接收分片和分片 ETag，支持上传进度查询与断点续传。
- 上传完成后创建文档记录，并投递异步任务进行解析、分块、全文索引构建和向量入库。
- Celery Worker 使用独立队列处理文档解析与向量化任务，避免长耗时流程阻塞接口响应。

### 多格式文档解析与自适应分块

| 文件类型 | 解析方式 | 分块策略 |
|----------|----------|----------|
| PDF | LangChain PDF Loader / pypdf | 按段落边界切分 |
| DOCX | LangChain DOCX Loader / docx2txt | 通用递归分块 |
| XLSX / XLS | pandas 读取多 Sheet | 表格文本化后递归分块 |
| PPTX | python-pptx 提取幻灯片文本 | 幻灯片文本化后递归分块 |
| Markdown | 文本读取 | 按标题层级切分 |
| CSV | pandas 读取表格内容 | 表格文本化后递归分块 |
| 代码文件 | 文本读取 | 按函数、类、结构体等定义边界切分 |
| 通用文本 | UTF-8 文本读取 | 递归字符分块，默认 512 字符、128 字符重叠 |

每个片段会保留文件类型、字符数、语言提示、片段序号和分块策略等元数据，便于后续检索、展示和来源追溯。

### 混合检索与重排序

- **全文检索**：基于 Elasticsearch 8 和 IK 中文分词构建文档片段索引，使用 BM25 进行关键词召回。
- **向量检索**：基于 BGE-M3 生成 1024 维文本向量，写入 Milvus，使用 IVF_FLAT + IP 进行近似最近邻检索。
- **结果融合**：使用 RRF 对关键词召回与向量召回结果进行融合，减少单一路径检索偏差。
- **语义重排序**：调用 BGE-reranker-v2-m3 Cross-Encoder 对候选片段重新打分，筛选更适合进入生成上下文的 Top 片段。

### Agent 化 RAG 编排

- 将知识库检索封装为大模型可调用工具，由模型先判断当前问题是普通闲聊还是知识库问题。
- 知识库相关问题自动触发查询改写、混合检索、重排序和检索增强生成。
- 普通问题直接返回模型回复，减少不必要的检索调用。
- 查询改写会结合最近会话历史，补全指代词和省略主题，提升多轮追问场景下的召回质量。

### 记忆与上下文管理

- 使用 MySQL 持久化会话与消息记录，支持会话创建、重命名、删除和消息列表查询。
- RAG 问答前读取最近上下文，用于意图判断和查询改写。
- 回答结果附带引用片段、来源文档和相关度分数，方便用户核验答案依据。

### 多租户与后台管理

- 基于 JWT Access Token / Refresh Token 实现登录认证。
- 支持普通用户与管理员角色，管理员可管理用户、邀请码和平台统计数据。
- 文档支持组织标签和公开状态，普通用户默认访问自己的文档及符合规则的公开文档。
- 支持模型供应商配置，API Key 加密存储，并可测试模型服务连通性。

---

## 技术栈

### 后端

| 技术 | 用途 |
|------|------|
| Python 3.11 | 后端运行时 |
| FastAPI | 异步 Web 框架 |
| SQLAlchemy 2.0 | ORM 与数据库访问 |
| Alembic | 数据库迁移 |
| MySQL 8 | 用户、文档、会话等关系数据存储 |
| Redis 7 | 上传状态、缓存、限流支撑 |
| Celery | 异步任务队列 |
| RabbitMQ | Celery 消息代理 |
| MinIO | S3 兼容对象存储 |
| Elasticsearch 8 | 全文检索 |
| Milvus 2.4 | 向量数据库 |
| LangChain | 文档加载与通用文本分块能力 |
| httpx | 异步模型服务调用 |

### 前端

| 技术 | 用途 |
|------|------|
| Vue 3 | 前端框架 |
| TypeScript | 类型安全 |
| Vite | 开发与构建工具 |
| Naive UI | UI 组件库 |
| Pinia | 状态管理 |
| UnoCSS | 原子化 CSS |
| markdown-it / highlight.js | Markdown 渲染与代码高亮 |

### AI 模型

| 模型/服务 | 用途 |
|-----------|------|
| Qwen3-8B | 问答生成与意图判断 |
| BGE-M3 | 文本向量化 |
| BGE-reranker-v2-m3 | 检索结果重排序 |
| SiliconFlow API | OpenAI 兼容模型接口 |

---

## 快速开始

### 前置条件

- Docker & Docker Compose
- Python 3.11+
- Node.js 18+
- uv

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，补充数据库密码、对象存储密码、模型 API Key 等配置。

### 2. 启动基础设施

```bash
make up
```

该命令会启动 MySQL、Redis、MinIO、Elasticsearch、RabbitMQ、Milvus 和 Celery Worker 等依赖服务。

### 3. 初始化数据库与向量集合

```bash
make init
make migrate
```

### 4. 启动后端服务

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

### 5. 启动前端服务

```bash
cd frontend
npm install
npx vite
```

### 6. 访问地址

- 前端应用：http://localhost:5173
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

---

## 项目结构

```text
ScholarRAG/
├── backend/                  # FastAPI 后端服务
│   ├── app/
│   │   ├── api/v1/           # 认证、文档、检索、问答、管理接口
│   │   ├── core/             # 配置、安全、依赖注入、异常处理、限流
│   │   ├── db/               # 数据库连接与会话
│   │   ├── models/           # SQLAlchemy ORM 模型
│   │   ├── schemas/          # Pydantic 请求/响应模型
│   │   ├── services/         # 文档、检索、RAG、向量库、存储等业务逻辑
│   │   ├── tasks/            # Celery 异步任务
│   │   └── main.py           # FastAPI 应用入口
│   ├── alembic/              # 数据库迁移
│   └── tests/                # 后端测试
├── frontend/                 # Vue 3 前端应用
│   └── src/
│       ├── api/              # API 客户端
│       ├── layouts/          # 页面布局
│       ├── pages/            # 登录、知识库、聊天、管理页面
│       ├── router/           # 路由配置
│       └── stores/           # Pinia 状态
├── docker/                   # 自定义 Dockerfile
├── docs/                     # 项目文档与资源
├── scripts/                  # 初始化脚本
├── docker-compose.yml        # 基础设施编排
├── docker-compose.dev.yml    # 开发环境覆盖配置
├── Makefile                  # 常用开发命令
└── README.md
```

---

## 开发指南

### 常用命令

```bash
make up         # 启动基础设施
make down       # 停止基础设施
make init       # 初始化数据库和 Milvus
make migrate    # 执行数据库迁移
make test       # 运行后端测试
```

### 后端代码质量

```bash
cd backend
ruff check .
ruff format .
mypy .
```

### 前端构建

```bash
cd frontend
npm run build
```

### 代码规范

- Python 使用 Ruff 和 mypy，目标版本 Python 3.11。
- 后端接口统一挂载在 `/api/v1` 前缀下。
- 前端使用 Vue 3 `<script setup>`、TypeScript、Naive UI 和 UnoCSS。
- 新增后端依赖写入 `backend/pyproject.toml`，新增前端依赖写入 `frontend/package.json`。
- 不提交 `.venv/`、`node_modules/`、缓存目录和本地生成文件。

---

## 许可证

MIT License
