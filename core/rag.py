"""
PDF-based RAG for table discovery.

Parses vital_dictionnaire_donnees_complet.pdf, splits it into 129 per-table
chunks, embeds them with nomic-embed-text via Ollama, and stores them in a
persistent ChromaDB collection.

At query time, search() returns the top-k most semantically relevant table
descriptions for a given user question.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

import chromadb
import pdfplumber
from chromadb import EmbeddingFunction, Documents, Embeddings
from openai import OpenAI

import config

COLLECTION_NAME = "medinote_tables"
INDEX_DIR = Path(__file__).parent.parent / ".rag_index"  # project root

# Matches "Table 12/129 - ca_tot_vente"
_TABLE_HEADER = re.compile(r"Table\s+\d+/129\s+-\s+(\w+)", re.IGNORECASE)


class _OllamaEmbedFn(EmbeddingFunction):
    """ChromaDB embedding function backed by Ollama nomic-embed-text."""

    def __init__(self):
        self._client = OpenAI(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
        )

    def __call__(self, input: Documents) -> Embeddings:
        response = self._client.embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=list(input),
        )
        return [item.embedding for item in response.data]


class TableRAG:
    def __init__(self):
        self._db = chromadb.PersistentClient(path=str(INDEX_DIR))
        self._ef = _OllamaEmbedFn()
        self._col = None

    # ── Public ────────────────────────────────────────────────────────

    @property
    def is_built(self) -> bool:
        try:
            return self._db.get_collection(COLLECTION_NAME).count() > 0
        except Exception:
            return False

    def build(self, pdf_path: str) -> int:
        """
        Parse PDF, embed every table chunk, persist to ChromaDB.
        Returns number of tables indexed.
        Safe to call multiple times — recreates the collection.
        """
        chunks = self._parse_pdf(pdf_path)
        if not chunks:
            raise ValueError("No table chunks extracted from PDF.")

        # Drop and recreate so we can safely rebuild
        try:
            self._db.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

        col = self._db.create_collection(
            name=COLLECTION_NAME,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

        # Upsert in batches of 20 (Ollama embedding limit)
        tables   = [c["table"]   for c in chunks]
        modules  = [c["module"]  for c in chunks]
        texts    = [c["text"]    for c in chunks]

        batch = 20
        for i in range(0, len(chunks), batch):
            col.add(
                ids=tables[i:i+batch],
                documents=texts[i:i+batch],
                metadatas=[{"table": t, "module": m}
                           for t, m in zip(tables[i:i+batch], modules[i:i+batch])],
            )

        self._col = col
        return len(chunks)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Return the top-k most relevant table descriptions for a query.
        Each result: {table, module, text, score}
        """
        col = self._get_collection()
        results = col.query(query_texts=[query], n_results=top_k)

        out = []
        for i, doc in enumerate(results["documents"][0]):
            meta  = results["metadatas"][0][i]
            score = results["distances"][0][i]
            out.append({
                "table":  meta["table"],
                "module": meta["module"],
                "text":   doc,
                "score":  round(score, 4),
            })
        return out

    # ── Parsing ───────────────────────────────────────────────────────

    def _parse_pdf(self, path: str) -> list[dict]:
        """Extract full text and split into per-table chunks."""
        full_text = self._extract_text(path)
        return self._split_by_table(full_text)

    @staticmethod
    def _extract_text(path: str) -> str:
        parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def _split_by_table(text: str) -> list[dict]:
        """
        Find every "Table N/129 - tablename" header and slice the text
        between consecutive headers into one chunk per table.
        """
        matches = list(_TABLE_HEADER.finditer(text))
        chunks = []

        for i, match in enumerate(matches):
            table_name = match.group(1).lower()
            start = match.start()
            end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[start:end].strip()

            # Extract module line if present
            module = ""
            for line in chunk.splitlines()[:6]:
                if "module" in line.lower():
                    module = line.split(":", 1)[-1].strip()
                    break

            chunks.append({
                "table":  table_name,
                "module": module,
                "text":   chunk[:1200],   # cap at ~1200 chars per chunk
            })

        return chunks

    # ── Internal ──────────────────────────────────────────────────────

    def _get_collection(self):
        if self._col is None:
            self._col = self._db.get_collection(
                name=COLLECTION_NAME,
                embedding_function=self._ef,
            )
        return self._col
