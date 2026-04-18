import os
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8081")

# ── Data Agent LLM (DeepSeek via Ollama) ─────────────────────────────
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "ollama")
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-v3.1:671b-cloud")

# ── Orchestrator LLM (gpt-oss:20b cloud via Ollama) ───────────────────
ORCHESTRATOR_BASE_URL: str = os.getenv("ORCHESTRATOR_BASE_URL", "http://localhost:11434/v1")
ORCHESTRATOR_API_KEY: str = os.getenv("ORCHESTRATOR_API_KEY", "ollama")
ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", "gpt-oss:20b-cloud")

# ── Analysis Agent LLM ────────────────────────────────────────────────
ANALYSIS_BASE_URL: str = os.getenv("ANALYSIS_BASE_URL", "http://localhost:11434/v1")
ANALYSIS_API_KEY: str = os.getenv("ANALYSIS_API_KEY", "ollama")
ANALYSIS_MODEL: str = os.getenv("ANALYSIS_MODEL", "gpt-oss:20b-cloud")

# ── Report Agent LLM ─────────────────────────────────────────────────
REPORT_BASE_URL: str = os.getenv("REPORT_BASE_URL", "http://localhost:11434/v1")
REPORT_API_KEY: str  = os.getenv("REPORT_API_KEY",  "ollama")
REPORT_MODEL: str    = os.getenv("REPORT_MODEL",    "gpt-oss:20b-cloud")

# FAISS catalog index built from product PPTXs
REPORT_FAISS_INDEX: str    = os.getenv(
    "REPORT_FAISS_INDEX",
    r"C:\Users\moham\Downloads\medimedi\report\rag\faiss_index\catalog.index",
)
REPORT_FAISS_METADATA: str = os.getenv(
    "REPORT_FAISS_METADATA",
    r"C:\Users\moham\Downloads\medimedi\report\rag\faiss_index\metadata.pkl",
)

# ── RAG ───────────────────────────────────────────────────────────────
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
PDF_PATH: str = os.getenv("PDF_PATH", "vital_dictionnaire_donnees_complet.pdf")

# ── Entity RAG (doctors + products) ──────────────────────────────────
ENTITY_DOCTORS_CSV: str   = os.getenv("ENTITY_DOCTORS_CSV",   r"C:\python pi\doctors.csv")
ENTITY_PRODUCTS_JSON: str = os.getenv("ENTITY_PRODUCTS_JSON", r"C:\python pi\prod_vital.json")

# ── Doctor Agent LLM (small local model) ─────────────────────────────
DOCTOR_BASE_URL: str = os.getenv("DOCTOR_BASE_URL", "http://localhost:11434/v1")
DOCTOR_API_KEY: str  = os.getenv("DOCTOR_API_KEY",  "ollama")
DOCTOR_MODEL: str    = os.getenv("DOCTOR_MODEL",    "llama3.1:8b")
