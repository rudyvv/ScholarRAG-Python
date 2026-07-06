# Paismart RAG — 代码与文档差异记录

> 记录代码实现与文档/脚本之间发现的全部不一致项，以及确认的修复方案。
> 创建日期: 2025-07

---

## ✅ 已确认并修复

### 1. Celery 消息代理：文档误标为 Redis，实为 RabbitMQ

**问题**：`REASONIX.md` 写的是 `Celery — task queue with Redis broker`，但代码实际使用 RabbitMQ 作为 broker，Redis 仅作 result backend。

**修复**：更新 REASONIX.md 描述为 RabbitMQ broker。

**涉及文件**：
- `REASONIX.md`

---

### 2. Elasticsearch 分词器：代码误用 `standard`，应为 IK

**问题**：`backend/app/services/search_service.py` 中 `INDEX_MAPPINGS` 的 content 字段 analyzer 设置为 `"standard"`，但项目使用 IK 中文分词器（`docker/elasticsearch/Dockerfile` 已安装 `analysis-ik` 插件），init 脚本也使用 `ik_max_word`。

**修复**：将 search_service.py 中的 analyzer 改为 `"ik_max_word"`，与基础设施保持一致。

**涉及文件**：
- `backend/app/services/search_service.py`

---

### 3. Milvus 初始化脚本：向量维度与字段结构不匹配代码

**问题**：`scripts/init-milvus.sh` 有两处核心不匹配：

| 项目 | init-milvus.sh（旧） | vector_store.py（代码） |
|---|---|---|
| 向量维度 | 2048 | 1024 |
| 主键字段 | `id` (auto_id=True) | `chunk_id` (auto_id=False) |
| 文档 ID 字段 | `document_id` (VARCHAR) | `doc_id` (INT64) |
| 额外字段 | 有 `metadata` (JSON) | 无 metadata 字段 |
| 缺少字段 | 无 `chunk_index` | 有 `chunk_index` (INT64) |

**修复**：统一 init-milvus.sh 的 schema 定义与 vector_store.py 一致。

**涉及文件**：
- `scripts/init-milvus.sh`

---

### 4. ES 索引名：init 脚本建 `knowledge_base`，代码用 `document_chunks`

**结论**：`scripts/init-es.sh` 创建的 `knowledge_base` 索引代码完全不使用，代码启动时由 `init_search_index()` 自动创建 `document_chunks` 索引。**确认不做修改**，init-es.sh 可视为历史残留。

---

## ⏳ 待修复建议

### 5. Makefile `build-backend` / `build-frontend` 指向不存在的 Dockerfile

**问题**：
- `make build-backend` → `docker build -f docker/backend/Dockerfile ...` ❌ 不存在
- `make build-frontend` → `docker build -f docker/frontend/Dockerfile ...` ❌ 不存在

实际的 Dockerfile 位置：
- `backend/Dockerfile` — 构建 Celery Worker 镜像（`paismart-backend`）
- `docker/elasticsearch/Dockerfile` — 构建带 IK 插件的 ES 镜像

**建议修复方案**：
```makefile
build-backend: _check-env
	docker build -f backend/Dockerfile -t $(PROJECT_NAME)-backend:latest backend

build-frontend:
	docker build -f frontend/Dockerfile -t $(PROJECT_NAME)-frontend:latest frontend
```
（需先创建 `frontend/Dockerfile`，当前不存在）

或者直接删除这两个 target（如果不需要 Docker 化部署）。

---

### 6. `make migrate` 未 cd 到 backend/ 目录

**问题**：Makefile 中 `migrate` target 直接执行 `alembic upgrade head`，但 `alembic.ini` 和 `alembic/` 目录在 `backend/` 下。从项目根执行会报错。

**建议修复方案**：
```makefile
migrate: _check-env
	cd backend && alembic upgrade head
```

---

### 7. `make init` 的实际有效性

**问题**：`make init` 依次调用 4 个脚本，但实际效果：

| 脚本 | 有效性 |
|---|---|
| `init-db.sh` | ✅ 有效 — 建库 + 跑 migration |
| `init-es.sh` | ❌ 无效 — 建 `knowledge_base`，代码用 `document_chunks` |
| `init-milvus.sh` | ❌ 无效 — 建 2048 维 schema，代码用 1024 维（已修复） |
| `init-admin.sh` | ⚠️ 依赖后端已启动（循环依赖） |

**建议**：
- ES 初始化：删除 `init-es.sh`，依赖代码 `init_search_index()` 自动创建
- Milvus 初始化：使用已修复后的脚本（字段匹配代码）
- Admin 初始化：改为通过 bootstrap_service 在应用启动时自动完成（已实现），去掉 shell 脚本依赖

---

### 8. 管理员默认邮箱不一致

**问题**：

| 文件 | 默认值 |
|---|---|
| `scripts/init-admin.sh:38` | `ADMIN_EMAIL="${ADMIN_EMAIL:-admin@paismart.**ai**}"` |
| `backend/app/services/bootstrap_service.py:25` | `_ADMIN_EMAIL = getattr(settings, "ADMIN_EMAIL", "admin@paismart.**com**")` |

**建议**：统一为同一值，建议全用 `settings.ADMIN_EMAIL` 作为唯一来源。在 `.env.example` 中添加 `ADMIN_EMAIL=admin@paismart.com` 显式声明。

---

### 9. 文档未列出的文件/脚本

| 文件 | 说明 | 建议 |
|---|---|---|
| `backend/scripts/init.py` | Python 版 bootstrap（等效 `init-admin.sh`） | 在 REASONIX.md 中提及，或删除 |
| `scripts/start-dev.ps1` | Windows PowerShell 启动脚本 | 在 REASONIX.md 开发命令中补充 |
| `scripts/milvus_standalone.bat` | Windows 独立启动 Milvus 脚本 | 在 REASONIX.md 中提及 |
| `main.py`（项目根） | uv 生成的占位文件，仅 print | 删除或补充说明 |

---

### 10. 前端 baseURL 硬编码 /api/v1

**问题**：`frontend/src/api/client.ts:7` 中 `baseURL: '/api/v1'` 硬编码。虽然在开发模式和标准部署中通常可用，但如果是非根路径部署会有问题。

**建议**：通过 VITE_API_BASE_URL 环境变量配置。

---

## 📊 优先级矩阵

| 优先级 | 项目 | 影响面 |
|---|---|---|
| 🔴 P0（已修） | ES 分词器 standard → IK | 中文搜索完全不可用 |
| 🔴 P0（已修） | Milvus schema 不匹配 | 向量入库必失败 |
| 🟡 P1 | Dockerfile 路径错误 | 构建 CI/CD 失败 |
| 🟡 P1 | `make migrate` cwd 问题 | 本地开发卡住 |
| 🟢 P2 | `make init` 有效性 | 初始化流程混乱 |
| 🟢 P2 | 文档遗漏 / 邮箱默认值 | 体验问题 |
