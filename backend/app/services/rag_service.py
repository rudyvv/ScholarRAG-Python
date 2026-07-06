"""RAG conversation pipeline.

Provides the ``RAGService`` class that orchestrates document retrieval,
cross-encoder reranking, and LLM-based answer generation via the
SiliconFlow API.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.conversation import (
    ConversationMessage,
    ConversationSession,
    MessageRole,
)
from app.services import search_service
from app.services.embedding_service import generate_embedding
from app.services.http_client import get_http_client
from app.services.provider_service import (
    get_active_embedding_provider,
    get_active_llm_provider,
)
from app.services.reranker_service import rerank_chunks
from app.services.vector_store import MilvusClient

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_LLM_TIMEOUT = 60  # HTTP request timeout in seconds
_MAX_CONTEXT_CHUNKS = 5  # Number of chunks fed to the LLM
_TOP_K_RERANK_FEED = 20  # Number of RRF-fused chunks to rerank
_TOP_K_RETRIEVAL = 30  # 每个检索引擎取 top N，供 RRF 融合
_RRF_K = 60  # RRF 常量
_MAX_TOKENS = 2048
_TEMPERATURE = 0.3

_SYSTEM_PROMPT = (
    "你是智能文档助手，基于以下文档内容回答用户问题。"
    "如果文档内容不足以回答问题，请诚实地说明。"
)

# Intent detection — the LLM decides whether to retrieve or chat
_INTENT_SYSTEM_PROMPT = (
    "你是智能文档助手。你需要判断用户的问题是需要在知识库中查找文档内容，"
    "还是纯粹的闲聊。\n\n"
    "如果用户的问题与已上传的文档相关（询问具体信息、总结、查找细节、"
    "对比内容等），请调用 retrieve_documents 工具来搜索相关知识。\n\n"
    "注意对话历史中的上下文：如果用户说'它'、'这个'、'那个'、'上面'等指代词，"
    "或省略了主语，请结合历史判断是否需要检索。\n\n"
    "如果用户只是打招呼、闲聊、或问与文档无关的一般性问题，请直接回答。"
)

# Query rewriting — enrich the search query with conversation context
_QUERY_REWRITE_PROMPT = (
    "你是一个搜索查询优化助手。你的任务是根据对话历史，优化用户的当前问题，"
    "生成一个独立、完整、包含足够上下文的搜索查询。\n\n"
    "要求：\n"
    "1. 如果当前问题包含指代词（它、这个、那个、上面、他、她等），请结合历史将其替换为具体内容\n"
    "2. 如果当前问题省略了上下文（如只说了'继续说'、'具体讲讲'），请补充缺失的主题\n"
    "3. 提取核心关键词和概念，使搜索更容易命中相关文档\n"
    "4. 保持原问题的搜索意图，不要添加不存在的信息\n"
    "5. 直接输出优化后的查询文本，不要加引号或前缀"
)

# Tool definition for retrieval intent
_RETRIEVE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "retrieve_documents",
        "description": (
            "在知识库中搜索与用户问题相关的文档片段。"
            "当用户询问文档内容、要求总结文档、或询问文档中的具体信息时调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用于检索的优化搜索关键词，从用户问题中提取核心概念",
                },
            },
            "required": ["query"],
        },
    },
}


# ---------------------------------------------------------------------------
# RAGService
# ---------------------------------------------------------------------------


class RAGService:
    """Retrieval-Augmented Generation service.

    Searches document chunks relevant to a user query, builds an LLM
    prompt with the retrieved context, calls the SiliconFlow
    ``chat/completions`` endpoint, and optionally persists the
    conversation as ``ConversationMessage`` records.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        redis: Any = None,  # noqa: ANN401 — reserved for future use
    ) -> None:
        """Initialise the service.

        Args:
            db_session: An active SQLAlchemy async session.
            redis: Optional Redis manager (currently unused).
        """
        self.db = db_session
        self.redis = redis

    # ── Public API ───────────────────────────────────────────────────────────

    async def answer_question(
        self,
        query: str,
        user_id: int,
        session_id: int | None = None,
        doc_id: int | None = None,
    ) -> dict[str, Any]:
        """Answer a user question with intent-aware routing.

        Flow:
        1. Call LLM with ``retrieve_documents`` tool — model decides intent.
        2a. **Retrieval intent** → ``_call_with_tools`` returns a tool call →
            hybrid search → ``_call_llm`` with context → answer + sources.
        2b. **Chat intent** → ``_call_with_tools`` returns text directly →
            answer = that text, sources = [].

        Args:
            query: The user's question.
            user_id: The authenticated user's ID.
            session_id: Optional conversation session ID to persist
                messages into.
            doc_id: Optional document ID to restrict the search scope.

        Returns:
            A dict with keys:

            - ``answer``: The LLM-generated answer text.
            - ``sources``: List of source chunk dicts used as context
              (each contains ``chunk_id``, ``document_id``, ``filename``,
              ``content``, and ``score``), or ``[]`` for chat intent.
            - ``session_id``: The session ID (newly created if
              *session_id* was ``None``).
        """
        # ── 0. Load conversation history (last 6 turns) ──────────────
        history_text = await self._load_recent_history(
            user_id, session_id, max_turns=6
        )

        # ── 1. Intent detection via function calling ────────────────────
        intent = await self._call_with_tools(query, history=history_text)

        if intent["type"] == "tool_call":
            # ── 2a. Retrieval intent ───────────────────────────────────
            raw_search_query = intent["tool_args"].get("query", query)

            # ── 2b. Query rewriting — enrich with conversation context ─
            search_query = await self._rewrite_search_query(
                raw_search_query, history_text
            )
            logger.info(
                "Query rewritten: %r → %r", raw_search_query, search_query
            )

            # Hybrid retrieve → RRF → rerank → top K
            raw_chunks = await self._retrieve_chunks(
                search_query, doc_id, top_k=_TOP_K_RERANK_FEED,
            )
            reranked = await rerank_chunks(search_query, raw_chunks)
            top_chunks = reranked[:_MAX_CONTEXT_CHUNKS]

            context_parts: list[str] = []
            source_doc_ids: set[int] = set()
            for c in top_chunks:
                context_parts.append(f"【文档 {c['document_id']}】\n{c['content']}")
                source_doc_ids.add(c["document_id"])
            context_text = "\n\n---\n\n".join(context_parts)

            doc_map = await self._resolve_document_names(source_doc_ids)
            sources = [
                {
                    "chunk_id": c["chunk_id"],
                    "document_id": c["document_id"],
                    "filename": doc_map.get(c["document_id"], "unknown"),
                    "content": c["content"],
                    "score": c["score"],
                }
                for c in top_chunks
            ]

            answer = await self._call_llm(query, context_text)
        else:
            # ── 2b. Chat intent — use first response directly ──────────
            answer = intent["content"]
            sources = []

        # ── 3. Persist conversation ─────────────────────────────────────
        final_session_id = await self._persist_conversation(
            query=query,
            answer=answer,
            user_id=user_id,
            session_id=session_id,
        )

        return {
            "answer": answer,
            "sources": sources,
            "session_id": final_session_id,
        }

    # ── Streaming variant ─────────────────────────────────────────────────────

    async def answer_question_stream(
        self,
        query: str,
        user_id: int,
        session_id: int | None = None,
        doc_id: int | None = None,
    ):
        """Stream the RAG answer as SSE events.

        Yields dicts with keys:

        - ``{"type": "meta", "session_id": int}`` when a session is
          resolved or created.
        - ``{"type": "token", "token": "…"}`` for each text fragment
          from the LLM.
        - ``{"type": "sources", "sources": […]}`` with final source
          chunks.
        - ``{"type": "error", "message": "…"}`` on failure.
        - ``{"type": "done"}`` when the stream is complete.
        """
        # ── 0. Load conversation history ──────────────────────────────
        history_text = await self._load_recent_history(
            user_id, session_id, max_turns=6
        )

        # ── 1. Intent detection ───────────────────────────────────────
        intent = await self._call_with_tools(query, history=history_text)

        retrieval_context: dict[str, Any] = {
            "search_query": query,
            "sources": [],
            "context_text": "",
        }

        if intent["type"] == "tool_call":
            raw_search_query = intent["tool_args"].get("query", query)
            search_query = await self._rewrite_search_query(
                raw_search_query, history_text,
            )
            logger.info("Query rewritten: %r → %r", raw_search_query, search_query)
            retrieval_context["search_query"] = search_query

            raw_chunks = await self._retrieve_chunks(
                search_query, doc_id, top_k=_TOP_K_RERANK_FEED,
            )
            reranked = await rerank_chunks(search_query, raw_chunks)
            top_chunks = reranked[:_MAX_CONTEXT_CHUNKS]

            context_parts: list[str] = []
            source_doc_ids: set[int] = set()
            for c in top_chunks:
                context_parts.append(f"【文档 {c['document_id']}】\n{c['content']}")
                source_doc_ids.add(c["document_id"])
            context_text = "\n\n---\n\n".join(context_parts)

            doc_map = await self._resolve_document_names(source_doc_ids)
            retrieval_context["sources"] = [
                {
                    "chunk_id": c["chunk_id"],
                    "document_id": c["document_id"],
                    "filename": doc_map.get(c["document_id"], "unknown"),
                    "content": c["content"],
                    "score": c["score"],
                }
                for c in top_chunks
            ]
            retrieval_context["context_text"] = context_text
        else:
            # Chat intent — no retrieval needed, pass query directly
            retrieval_context["context_text"] = ""

        # ── 2. Persist conversation (save session first so we have an ID) ──
        # We create the session now so the ID can be yielded early.
        # The messages will be appended after the LLM call.
        if session_id is not None:
            stmt = select(ConversationSession).where(
                ConversationSession.id == session_id,
                ConversationSession.user_id == user_id,
            )
            result = await self.db.execute(stmt)
            session = result.scalar_one_or_none()
            if session is None:
                session_id = None

        if session_id is None:
            session = ConversationSession(
                user_id=user_id,
                title=query[:100],
            )
            self.db.add(session)
            await self.db.flush()
            session_id = session.id

        yield {"type": "meta", "session_id": session_id}

        # ── 3. LLM call — stream tokens ───────────────────────────────
        context_text = retrieval_context["context_text"]
        if intent["type"] == "tool_call" and not context_text.strip():
            yield {"type": "token", "token": "未找到相关的文档内容。请上传文档后再进行提问。"}
            yield {"type": "sources", "sources": []}
            yield {"type": "done"}
            return

        if intent["type"] == "tool_call":
            # Streaming generation with context
            answer_text = ""
            async for token_dict in self._call_llm_stream(query, context_text):
                if token_dict["type"] == "token":
                    answer_text += token_dict["token"]
                yield token_dict
                if token_dict["type"] == "error":
                    break
        else:
            # Chat intent — no context
            answer_text = intent.get("content", "")
            yield {"type": "token", "token": answer_text}

        # ── 4. Yield sources ──────────────────────────────────────────
        yield {"type": "sources", "sources": retrieval_context["sources"]}

        # ── 5. Persist messages ───────────────────────────────────────
        try:
            user_msg = ConversationMessage(
                session_id=session_id,
                role=MessageRole.USER,
                content=query,
            )
            self.db.add(user_msg)
            assistant_msg = ConversationMessage(
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=answer_text,
            )
            self.db.add(assistant_msg)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("Failed to persist streaming conversation")

        yield {"type": "done"}

    async def _call_llm_stream(
        self,
        query: str,
        context_text: str,
    ):
        """Call the LLM chat/completions API with ``stream=True``.

        Yields dicts:
        - ``{"type": "token", "token": "…"}`` per text delta.
        - ``{"type": "error", "message": "…"}`` on failure.
        """
        if not context_text.strip():
            yield {"type": "token", "token": "未找到相关的文档内容。请上传文档后再进行提问。"}
            return

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"基于以下文档内容回答问题。\n\n"
                    f"文档内容：\n{context_text}\n\n"
                    f"问题：{query}"
                ),
            },
        ]

        # ── Resolve provider config ──────────────────────────────────
        llm_provider = await get_active_llm_provider(self.db)
        if llm_provider is not None and llm_provider.api_key_ciphertext:
            from app.core.security import decrypt_api_key  # noqa: PLC0415

            llm_key = decrypt_api_key(llm_provider.api_key_ciphertext)
            llm_base_url = llm_provider.api_base_url
            llm_model = llm_provider.model_name or settings.LLM_MODEL
            if not llm_key:
                llm_key = settings.LLM_API_KEY
                llm_base_url = settings.LLM_API_BASE_URL
                llm_model = settings.LLM_MODEL
        else:
            llm_key = settings.LLM_API_KEY
            llm_base_url = settings.LLM_API_BASE_URL
            llm_model = settings.LLM_MODEL

        url = f"{llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {llm_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": llm_model,
            "messages": messages,
            "temperature": _TEMPERATURE,
            "max_tokens": _MAX_TOKENS,
            "stream": True,
        }

        try:
            import json  # noqa: PLC0415

            client = get_http_client()
            async with client.stream(
                "POST", url, json=payload, headers=headers, timeout=_LLM_TIMEOUT
            ) as response:
                if not response.is_success:
                    logger.warning(
                        "LLM streaming API returned %s", response.status_code,
                    )
                    yield {
                        "type": "error",
                        "message": "抱歉，大模型服务暂时不可用，请稍后重试。",
                    }
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if not data_str or data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield {"type": "token", "token": delta}
                    except json.JSONDecodeError:
                        continue

        except httpx.TimeoutException:
            logger.warning("LLM streaming API timed out")
            yield {"type": "error", "message": "抱歉，大模型服务响应超时，请稍后重试。"}
        except httpx.RequestError as exc:
            logger.warning("LLM streaming API request failed: %s", exc)
            yield {"type": "error", "message": "抱歉，大模型服务连接失败，请稍后重试。"}
        except Exception:
            logger.exception("Unexpected error in LLM streaming")
            yield {"type": "error", "message": "抱歉，大模型服务处理异常，请稍后重试。"}

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _load_recent_history(
        self,
        user_id: int,
        session_id: int | None,
        max_turns: int = 6,
    ) -> str:
        """Load recent conversation history as a formatted string.

        Args:
            user_id: The authenticated user ID (for ownership check).
            session_id: Optional session ID to load history from.
            max_turns: Maximum number of recent messages to include.

        Returns:
            A formatted string like::

                user: 上一轮的问题
                assistant: 上一轮的回答
                user: 当前的问题
        """
        if session_id is None:
            return ""

        try:
            from sqlalchemy import select as _select

            # Verify session ownership
            stmt = _select(ConversationSession).where(
                ConversationSession.id == session_id,
                ConversationSession.user_id == user_id,
            )
            result = await self.db.execute(stmt)
            session = result.scalar_one_or_none()
            if session is None:
                return ""

            # Load recent messages, newest first
            msg_stmt = (
                _select(ConversationMessage)
                .where(ConversationMessage.session_id == session_id)
                .order_by(ConversationMessage.created_at.desc())
                .limit(max_turns)
            )
            msg_result = await self.db.execute(msg_stmt)
            messages = list(reversed(msg_result.scalars().all()))

            if not messages:
                return ""

            lines = [f"{m.role}: {m.content}" for m in messages]
            return "\n".join(lines)

        except Exception:
            logger.exception("Failed to load conversation history")
            return ""

    async def _rewrite_search_query(
        self,
        raw_query: str,
        history: str,
    ) -> str:
        """Rewrite the search query using conversation context.

        Calls the LLM with ``_QUERY_REWRITE_PROMPT`` to resolve pronouns,
        fill in missing context, and extract core search terms.

        Args:
            raw_query: The original query from the user or intent detection.
            history: Formatted conversation history string.

        Returns:
            The rewritten query, or the original if the LLM call fails.
        """
        if not history.strip():
            return raw_query  # No context to enrich with

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _QUERY_REWRITE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"对话历史：\n{history}\n\n"
                    f"当前问题：{raw_query}"
                ),
            },
        ]

        # ── Resolve provider config ──────────────────────────────────
        llm_provider = await get_active_llm_provider(self.db)
        if llm_provider is not None and llm_provider.api_key_ciphertext:
            from app.core.security import decrypt_api_key  # noqa: PLC0415

            llm_key = decrypt_api_key(llm_provider.api_key_ciphertext)
            llm_base_url = llm_provider.api_base_url
            llm_model = llm_provider.model_name or settings.LLM_MODEL
            if not llm_key:
                llm_key = settings.LLM_API_KEY
                llm_base_url = settings.LLM_API_BASE_URL
                llm_model = settings.LLM_MODEL
        else:
            llm_key = settings.LLM_API_KEY
            llm_base_url = settings.LLM_API_BASE_URL
            llm_model = settings.LLM_MODEL

        url = f"{llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {llm_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": llm_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 200,
        }

        try:
            client = get_http_client()
            response = await client.post(
                url, json=payload, headers=headers, timeout=_LLM_TIMEOUT
            )
            if response.is_success:
                data = response.json()
                rewritten = data["choices"][0]["message"]["content"].strip()
                if rewritten:
                    # Remove surrounding quotes if the model added them
                    rewritten = rewritten.strip("\"'「」")
                    return rewritten
        except Exception:
            logger.exception("Query rewriting failed — using original query")

        return raw_query

    async def _retrieve_chunks(
        self,
        query: str,
        doc_id: int | None = None,
        top_k: int = _MAX_CONTEXT_CHUNKS,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant chunks via hybrid search (BM25 + vector).

        Pipeline:
        1. ES BM25 取 top ``_TOP_K_RETRIEVAL``
        2. Milvus 向量检索取 top ``_TOP_K_RETRIEVAL``，过滤相似度 < 0.5 的
        3. RRF（Reciprocal Rank Fusion, k=60）融合两个结果集
        4. 返回 top *top_k*

        Gracefully degrades to one backend if the other is unavailable.

        Args:
            query: The search query.
            doc_id: Optional document ID to restrict the search.
            top_k: Number of top results to return (default
                   ``_MAX_CONTEXT_CHUNKS`` = 5).

        Returns:
            A list of chunk dicts sorted by descending RRF score,
            limited to *top_k* items.
        """
        first_doc_id = doc_id

        # ── 1. Full-text search (BM25) — top N ────────────────────────
        ft_items: list[dict] = []
        try:
            result = await search_service.search_fulltext(
                query=query,
                page=1,
                size=_TOP_K_RETRIEVAL,
                doc_id=first_doc_id,
            )
            ft_items = result.get("results", [])
        except Exception:
            logger.exception("Full-text search failed during RAG retrieval")

        # ── 2. Vector search — top N, then filter low-similarity ──────
        vec_items: list[dict] = []
        try:
            embed_provider = await get_active_embedding_provider(self.db)
            embed_key = None
            embed_url = None
            embed_model = None
            if embed_provider is not None and embed_provider.api_key_ciphertext:
                from app.core.security import decrypt_api_key  # noqa: PLC0415

                embed_key = decrypt_api_key(embed_provider.api_key_ciphertext)
                embed_url = embed_provider.api_base_url
                embed_model = embed_provider.embedding_model

            embedding = await generate_embedding(
                query,
                api_key=embed_key,
                api_base_url=embed_url,
                model=embed_model,
            )
            client = MilvusClient()
            try:
                raw = await client.search(
                    embedding=embedding,
                    top_k=_TOP_K_RETRIEVAL,
                    doc_id=first_doc_id,
                )
                for item in raw:
                    item["document_id"] = item.pop("doc_id")
                # 过滤掉相似度 < 0.5 的（BGE-M3 用 IP 内积 = cosine similarity）
                vec_items = [it for it in raw if (it.get("score") or 0.0) >= 0.5]
            finally:
                client.close()
        except Exception:
            logger.warning(
                "Vector search unavailable (Milvus not reachable) "
                "— degrading to fulltext-only"
            )

        # ── 3. RRF fusion ─────────────────────────────────────────────
        if not ft_items and not vec_items:
            return []

        # 构建 chunk_id → rank 映射
        ft_ranks: dict[int, int] = {
            it["chunk_id"]: i + 1 for i, it in enumerate(ft_items)
        }
        vec_ranks: dict[int, int] = {
            it["chunk_id"]: i + 1 for i, it in enumerate(vec_items)
        }

        all_ids = set(ft_ranks) | set(vec_ranks)

        def _rrf_score(chunk_id: int) -> float:
            score = 0.0
            if chunk_id in ft_ranks:
                score += 1.0 / (_RRF_K + ft_ranks[chunk_id])
            if chunk_id in vec_ranks:
                score += 1.0 / (_RRF_K + vec_ranks[chunk_id])
            return score

        # 取一个代表条目来获取 document_id 和 content
        by_id: dict[int, dict[str, Any]] = {}
        for it in ft_items:
            by_id[it["chunk_id"]] = it
        for it in vec_items:
            by_id[it["chunk_id"]] = it  # 后写入的覆盖（内容相同无所谓）

        scored = []
        for cid in all_ids:
            entry = by_id[cid]
            scored.append(
                {
                    "chunk_id": cid,
                    "document_id": entry["document_id"],
                    "content": entry["content"],
                    "score": _rrf_score(cid),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def _call_with_tools(
        self,
        query: str,
        history: str = "",
    ) -> dict[str, Any]:
        """Call LLM with ``retrieve_documents`` tool for intent detection.

        The model either calls the tool (retrieval intent) or responds
        directly (chat intent).  We keep this call very cheap —
        ``max_tokens=150``, ``temperature=0.1``.

        Args:
            query: The user's question.
            history: Optional formatted conversation history for context.

        Returns:
            ``{"type": "tool_call", "tool_args": {…}}`` or
            ``{"type": "text", "content": "…"}``.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
        ]

        # Inject conversation history for context-aware intent detection
        if history.strip():
            messages.append({
                "role": "system",
                "content": f"以下是对话历史，请注意上下文和指代关系：\n{history}",
            })

        messages.append({"role": "user", "content": query})

        # ── Resolve provider config ──────────────────────────────────
        llm_provider = await get_active_llm_provider(self.db)
        if llm_provider is not None and llm_provider.api_key_ciphertext:
            from app.core.security import decrypt_api_key  # noqa: PLC0415

            llm_key = decrypt_api_key(llm_provider.api_key_ciphertext)
            llm_base_url = llm_provider.api_base_url
            llm_model = llm_provider.model_name or settings.LLM_MODEL
            if not llm_key:
                llm_key = settings.LLM_API_KEY
                llm_base_url = settings.LLM_API_BASE_URL
                llm_model = settings.LLM_MODEL
        else:
            llm_key = settings.LLM_API_KEY
            llm_base_url = settings.LLM_API_BASE_URL
            llm_model = settings.LLM_MODEL

        url = f"{llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {llm_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": llm_model,
            "messages": messages,
            "tools": [_RETRIEVE_TOOL],
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_tokens": 150,
        }

        try:
            client = get_http_client()
            response = await client.post(url, json=payload, headers=headers, timeout=_LLM_TIMEOUT)

            if not response.is_success:
                logger.warning(
                    "Intent LLM returned %s — falling back to fulltext",
                    response.status_code,
                )
                # Degrade gracefully: assume retrieval intent
                return {"type": "tool_call", "tool_args": {"query": query}}

            data = response.json()
            choice = data["choices"][0]["message"]

            # ── Tool call ────────────────────────────────────────────
            if tool_calls := choice.get("tool_calls"):
                for tc in tool_calls:
                    if tc["function"]["name"] == "retrieve_documents":
                        import json  # noqa: PLC0415

                        args = json.loads(tc["function"]["arguments"])
                        logger.info(
                            "Intent → retrieval (query=%s)", args.get("query", query)
                        )
                        return {"type": "tool_call", "tool_args": args}

            # ── Text response (chat intent) ──────────────────────────
            content = choice.get("content") or ""
            logger.info("Intent → chat (response=%.60s…)", content)
            return {"type": "text", "content": content}

        except Exception:
            logger.exception(
                "Intent detection LLM call failed — falling back to retrieval"
            )
            return {"type": "tool_call", "tool_args": {"query": query}}

    async def _resolve_document_names(
        self,
        doc_ids: set[int],
    ) -> dict[int, str]:
        """Resolve a set of document IDs to their filenames.

        Args:
            doc_ids: Set of document primary keys.

        Returns:
            A mapping of ``{document_id: filename}``.
        """
        if not doc_ids:
            return {}

        from app.models.document import Document  # noqa: PLC0415, I001 — avoid circular import

        result: dict[int, str] = {}
        try:
            stmt = select(Document.id, Document.filename).where(
                Document.id.in_(doc_ids)  # type: ignore[union-attr]
            )
            rows = await self.db.execute(stmt)
            for row in rows:
                result[row[0]] = row[1]
        except Exception:
            logger.exception("Failed to resolve document names")
        return result

    async def _call_llm(
        self,
        query: str,
        context_text: str,
    ) -> str:
        """Call the SiliconFlow chat/completions API.

        Args:
            query: The user's question.
            context_text: Retrieved document context.

        Returns:
            The model's answer text, or a fallback message on error.
        """
        if not context_text.strip():
            return "未找到相关的文档内容。请上传文档后再进行提问。"

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"基于以下文档内容回答问题。\n\n"
                    f"文档内容：\n{context_text}\n\n"
                    f"问题：{query}"
                ),
            },
        ]

        # ── Resolve provider config: DB first, env fallback ──────────
        llm_provider = await get_active_llm_provider(self.db)
        if llm_provider is not None and llm_provider.api_key_ciphertext:
            from app.core.security import decrypt_api_key  # noqa: PLC0415

            llm_key = decrypt_api_key(llm_provider.api_key_ciphertext)
            llm_base_url = llm_provider.api_base_url
            llm_model = llm_provider.model_name or settings.LLM_MODEL
            if not llm_key:
                llm_key = settings.LLM_API_KEY
                llm_base_url = settings.LLM_API_BASE_URL
                llm_model = settings.LLM_MODEL
        else:
            llm_key = settings.LLM_API_KEY
            llm_base_url = settings.LLM_API_BASE_URL
            llm_model = settings.LLM_MODEL

        url = f"{llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {llm_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": llm_model,
            "messages": messages,
            "temperature": _TEMPERATURE,
            "max_tokens": _MAX_TOKENS,
        }

        try:
            client = get_http_client()
            response = await client.post(url, json=payload, headers=headers, timeout=_LLM_TIMEOUT)

            if response.is_success:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning(
                    "LLM API returned %s: %s",
                    response.status_code,
                    response.text[:500],
                )
                return "抱歉，大模型服务暂时不可用，请稍后重试。"

        except httpx.TimeoutException:
            logger.warning("LLM API request timed out after %ss", _LLM_TIMEOUT)
            return "抱歉，大模型服务响应超时，请稍后重试。"
        except httpx.RequestError as exc:
            logger.warning("LLM API request failed: %s", exc)
            return "抱歉，大模型服务连接失败，请稍后重试。"
        except Exception:
            logger.exception("Unexpected error calling LLM API")
            return "抱歉，大模型服务处理异常，请稍后重试。"

    async def _persist_conversation(
        self,
        query: str,
        answer: str,
        user_id: int,
        session_id: int | None,
    ) -> int:
        """Persist the Q&A pair as conversation messages.

        If ``session_id`` is ``None`` a new ``ConversationSession`` is
        created automatically.

        Args:
            query: The user's question.
            answer: The assistant's answer.
            user_id: The authenticated user's ID.
            session_id: Optional existing session ID.

        Returns:
            The (possibly new) session ID.
        """
        # Ensure session exists
        if session_id is not None:
            # Verify the session belongs to the user
            stmt = select(ConversationSession).where(
                ConversationSession.id == session_id,
                ConversationSession.user_id == user_id,
            )
            result = await self.db.execute(stmt)
            session = result.scalar_one_or_none()
            if session is None:
                session_id = None  # fall through to create below

        if session_id is None:
            session = ConversationSession(
                user_id=user_id,
                title=query[:100],
            )
            self.db.add(session)
            await self.db.flush()
            session_id = session.id  # type: ignore[assignment]

        # Save user message
        user_msg = ConversationMessage(
            session_id=session_id,
            role=MessageRole.USER,
            content=query,
        )
        self.db.add(user_msg)

        # Save assistant message
        assistant_msg = ConversationMessage(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=answer,
        )
        self.db.add(assistant_msg)

        await self.db.commit()

        return session_id
