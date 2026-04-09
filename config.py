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

# ── Auth ──────────────────────────────────────────────────────────────
BACKEND_EMAIL: str = os.getenv("BACKEND_EMAIL", "")
BACKEND_PASSWORD: str = os.getenv("BACKEND_PASSWORD", "")

# ── RAG ───────────────────────────────────────────────────────────────
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
PDF_PATH: str = os.getenv("PDF_PATH", "vital_dictionnaire_donnees_complet.pdf")
