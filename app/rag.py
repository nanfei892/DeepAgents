from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.schemas import WorkerResult

class PolicyRAG:
    def __init__(self) -> None:
        # Embedding 负责“召回”， 把问题和文档映射到同一向量空间
        self.embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
        self.store: Chroma | None = None
        self.reranker = None

    def initialize(self) -> None:
        # 已有持久化索引时直接加载，避免每次启动都重新切分和向量化
        if settings.chroma_dir.exists():
            self.store = Chroma(persist_directory=str(settings.chroma_dir), embedding_function=self.embeddings)
            return
        documents: list[Document] = []   # 原始政策文档列表
        for path in settings.knowledge_base_dir.glob("*.md"):
            # metadata 用户 Chroma filter，也会作为最终答案的可追溯来源。
            documents.append(Document(page_content=path.read_text(encoding="utf-8"), metadata={"source": path.name, "category": "policy"}))
        # overlap 保留相邻语义，避免政策条件刚好被切到两个 Chunk 中。
        chunks = RecursiveCharacterTextSplitter(chunk_size=450, chunk_overlap=80).split_documents(documents)

    def ask(self, question: str) -> WorkerResult:
        # assert 在开发期间尽早暴漏 “忘记 initialize” 这一生命周期错误
        assert self.store is not None,  "请先 initialize()"
        # 先宽召回 6 条， 阈值过滤明显无关的资料，category 防止未来混入其他知识域
        matches = self.store.similarity_search_with_relevance_scores(question, k=6, score_threshold=0.35, filter={"category": "policy"})
        if not matches:
            # RAG 的正确降级是 “承认不知道”，不是让模型编造
            return WorkerResult(answer="当前政策资料中没有足够的依据回答该问题，我已建议转人工确认。", confidence = 0.2, risk_level = "medium", action="create_ticket", handoff_reason="知识库无可靠依据")
        # 两阶段检索：向量召回 top-6 ，再用过 CrossEncoder 精排 top 3
        # 首次调用会下载模型，生产中应在应用启动阶段预热。
        if self.reranker is None:
            from sentence_transformers import CrossEncoder
            self.reranker = CrossEncoder(settings.reranker_model)
        # CrossEncoder 直接同时读取 “问题 + 文档 ”，精度高于只比较两个向量
        pairs = [(question, doc.page_content) for doc, _ in matches]
        rerank_scores = self.reranker.predict(pairs)
        # 根据精排分从高到低选前三条，注意 score 已不再是向量相似度
        reranked = sorted(zip(rerank_scores, matches), key=lambda item: item[0], reverse=True)
        sources = [
            {"source": doc.metadata["source"], "content": doc.page_content[:180], "score": round(float(score), 3)}
            for score, (doc, _) in reranked[:3]
        ]
        # 教学版直接拼接证据：生产环境可以再调用“仅依据 context 回答”的 LLM 链
        answer = "根据现有政策：\n" + "\n".join(f"- {item['content']}" for item in sources)
        return WorkerResult(answer = answer, confidence = matches[0][1], risk_level="low", citations = sources)

