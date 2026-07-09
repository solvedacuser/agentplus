from collections.abc import Callable

from app.core.config import get_settings
from app.rag.embeddings import embed_documents, embed_query
from app.rag.pdf_loader import load_pdfs_from_directory
from app.rag.text_splitter import split_pages
from app.rag.vector_store import LocalVectorStore, VectorRecord
from app.schemas.rag import IndexSummary, RetrievedContext


def index_pdfs(pdf_dir: str | None = None) -> IndexSummary:
    settings = get_settings()
    target_pdf_dir = pdf_dir or settings.pdf_dir

    pages = load_pdfs_from_directory(target_pdf_dir)
    chunks = split_pages(
        pages=pages,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    embeddings = embed_documents([chunk.text for chunk in chunks])

    records = [
        VectorRecord(chunk=chunk, embedding=embedding)
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]

    store = LocalVectorStore(settings.vector_store_path)
    store.save(records)

    return IndexSummary(
        pdf_count=len({page.source for page in pages}),
        page_count=len(pages),
        chunk_count=len(chunks),
        vector_store_path=settings.vector_store_path,
    )


def retrieve_context(query: str, top_k: int | None = None) -> list[RetrievedContext]:
    settings = get_settings()
    query_embedding = embed_query(query)
    store = LocalVectorStore(settings.vector_store_path)

    return store.search(
        query_embedding=query_embedding,
        top_k=top_k or settings.rag_top_k,
    )


def is_vector_store_ready() -> bool:
    settings = get_settings()
    store = LocalVectorStore(settings.vector_store_path)
    try:
        return len(store.load()) > 0
    except Exception:
        return False


def get_retriever(top_k: int | None = None) -> Callable[[str], list[RetrievedContext]]:
    def retriever(query: str) -> list[RetrievedContext]:
        return retrieve_context(query=query, top_k=top_k)

    return retriever
