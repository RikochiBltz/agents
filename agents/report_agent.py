"""
Report Agent

Pharmaceutical delegate field report assistant.
Handles visit-report writing tasks: reformulate notes, check structure,
identify missing sections, evaluate drafts, answer product questions.

RAG: FAISS index built from 22 product catalogue PPTXs for product-aware answers.
LLM: gpt-oss:20b-cloud via OpenAI-compatible API.
Fallback: keyword-based logic if LLM is unavailable or returns invalid JSON.
"""
from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

import config
from agents.data_agent import DataResult

# ── Optional FAISS / sentence-transformers ────────────────────────────
try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
    _FAISS_OK = True
except ImportError:
    _FAISS_OK = False


# ══════════════════════════════════════════════════════════════════════
# Language & intent detection
# ══════════════════════════════════════════════════════════════════════

def _detect_language(text: str) -> str:
    lower = text.lower()
    fr = sum(1 for m in [
        "bonjour", "comment", "rapport", "visite", "rédiger", "réécrire",
        "reformule", "structure", "manque", "aide", "pharmacien", "médecin",
        "produit", "évaluation", "prochaines actions", "intéressé",
        "kifeh", "chnowa", "na9es", "behi", "rayek", "7assen",
    ] if m in lower)
    en = sum(1 for m in [
        "hello", "how", "report", "visit", "rewrite", "reformulate",
        "structure", "missing", "help", "doctor", "pharmacist", "product",
        "evaluation", "next actions", "interested",
    ] if m in lower)
    return "fr" if fr >= en else "en"


def _looks_like_raw_notes(text: str, lang: str) -> bool:
    markers = (
        ["visite", "discussion", "intéressé", "cardiologue", "pharmacien",
         "omega 3", "doliprane", "panadol", "produit", "dosage"]
        if lang == "fr" else
        ["visited", "discussion", "interested", "cardiologist", "pharmacist",
         "omega 3", "doliprane", "panadol", "product", "dosage"]
    )
    return len(text.split()) <= 20 and sum(1 for m in markers if m in text) >= 2


def _detect_intents(text: str, lang: str) -> list[str]:
    lower = text.lower().strip()
    found: list[str] = []

    def add(n: str):
        if n not in found:
            found.append(n)

    if lang == "fr":
        if any(x in lower for x in ["structure", "comment rédiger", "comment rediger",
               "comment écrire", "rapport de visite", "modèle de rapport",
               "format du rapport", "kifeh nekteb", "exemple rapport"]):
            add("structure")
        if any(x in lower for x in ["exemple", "donne moi un exemple",
               "exemple de rapport"]):
            add("example")
        if any(x in lower for x in ["qu'est-ce qui manque", "que manque-t-il",
               "points manquants", "compléter mon rapport", "chnowa na9es", "chnowa nzid"]):
            add("missing_points")
        if any(x in lower for x in ["plus technique", "aide technique",
               "scientifique", "3atini afkar", "chnowa najm nzid"]):
            add("technical_help")
        if any(x in lower for x in ["évalue", "evalue", "est-ce que mon rapport est bon",
               "analyse mon rapport", "rapport behi", "9ayem", "rayek"]):
            add("evaluate")
        if any(x in lower for x in ["dosage", "posologie", "indication", "composition",
               "effets", "effet secondaire", "contre indication", "est-ce que",
               "c'est quoi", "chnowa", "combien", "quel", "quelle"]):
            add("question_answer")
        if any(x in lower for x in ["reformule", "réécris", "reecris", "corrige",
               "améliore cette phrase", "ameliore ce texte", "7assen", "sah7a"]):
            add("reformulate")
        if _looks_like_raw_notes(lower, lang):
            add("reformulate")
    else:
        if any(x in lower for x in ["report structure", "how do i write a report",
               "how to write a report", "report template", "visit report"]):
            add("structure")
        if any(x in lower for x in ["example", "give me an example", "example report"]):
            add("example")
        if any(x in lower for x in ["what is missing", "missing points",
               "what should i add", "complete my report"]):
            add("missing_points")
        if any(x in lower for x in ["make it more technical", "technical help",
               "what technical points"]):
            add("technical_help")
        if any(x in lower for x in ["evaluate my report", "is my report good",
               "review my report", "assess my report"]):
            add("evaluate")
        if any(x in lower for x in ["dosage", "dose", "indication", "composition",
               "side effects", "contraindication", "what is", "how much",
               "can you explain", "doctor asked"]):
            add("question_answer")
        if any(x in lower for x in ["reformulate", "rewrite", "correct this",
               "improve this sentence", "improve this text"]):
            add("reformulate")
        if _looks_like_raw_notes(lower, lang):
            add("reformulate")

    if not found:
        found.append("question_answer")

    order = ["structure", "example", "reformulate", "missing_points",
             "technical_help", "evaluate", "question_answer"]
    return [i for i in order if i in found]


# ══════════════════════════════════════════════════════════════════════
# FAISS catalog RAG
# ══════════════════════════════════════════════════════════════════════

class _CatalogRAG:
    def __init__(self, index_path: str, metadata_path: str):
        self._ready = False
        self._index = None
        self._metadata: list = []
        self._model = None

        if not _FAISS_OK:
            return
        try:
            ip, mp = Path(index_path), Path(metadata_path)
            if ip.exists() and mp.exists():
                self._index = faiss.read_index(str(ip))
                with mp.open("rb") as f:
                    self._metadata = pickle.load(f)
                self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
                self._ready = True
        except Exception:
            pass

    @property
    def ready(self) -> bool:
        return self._ready

    def search(self, query: str, top_k: int = 4) -> list[dict]:
        if not self._ready or not query.strip():
            return []
        emb = self._model.encode([query], convert_to_numpy=True).astype("float32")
        distances, indices = self._index.search(emb, top_k)
        results = []
        for idx, dist in zip(indices[0], distances[0]):
            if 0 <= idx < len(self._metadata):
                chunk = self._metadata[idx].copy()
                chunk["score"] = float(dist)
                results.append(chunk)
        return results


# ══════════════════════════════════════════════════════════════════════
# Keyword fallbacks (no LLM needed)
# ══════════════════════════════════════════════════════════════════════

_STRUCTURE_FR = [
    {"title": "Date",                                  "description": "Indiquer la date de la visite."},
    {"title": "Client",                                "description": "Nom du médecin ou pharmacien visité."},
    {"title": "Spécialité",                            "description": "Spécialité du professionnel de santé."},
    {"title": "Lieu",                                  "description": "Endroit où la visite a eu lieu."},
    {"title": "Objectif de la visite",                 "description": "Pourquoi la visite a été faite."},
    {"title": "Produits discutés",                     "description": "Produits présentés ou discutés."},
    {"title": "Discussion scientifique ou commerciale","description": "Points importants : bénéfices, dosage, indications."},
    {"title": "Réaction du professionnel de santé",    "description": "Intéressé, neutre, non convaincu."},
    {"title": "Résultat / opportunité",                "description": "Résultat obtenu et opportunité identifiée."},
    {"title": "Prochaines actions",                    "description": "Suivi : envoyer brochure, planifier 2ème visite…"},
]

_STRUCTURE_EN = [
    {"title": "Date",                              "description": "Write the date of the visit."},
    {"title": "Client",                            "description": "Name of the doctor or pharmacist visited."},
    {"title": "Specialty",                         "description": "Healthcare professional's specialty."},
    {"title": "Location",                          "description": "Where the visit took place."},
    {"title": "Visit objective",                   "description": "Why the visit was made."},
    {"title": "Products discussed",                "description": "Products presented or discussed."},
    {"title": "Scientific or commercial discussion","description": "Key points: benefits, dosage, indications."},
    {"title": "Healthcare professional reaction",  "description": "Interested, neutral, not convinced."},
    {"title": "Outcome / opportunity",             "description": "Visit outcome and opportunity identified."},
    {"title": "Next actions",                      "description": "Follow-up: send brochure, plan 2nd visit…"},
]


def _fb_structure(lang: str) -> list[dict]:
    return _STRUCTURE_FR if lang == "fr" else _STRUCTURE_EN


def _fb_example(lang: str) -> str:
    if lang == "fr":
        return (
            "Date : 01/04/2026\n"
            "Client : Dr Ahmed Ben Ali — Cardiologue, Tunis\n"
            "Objectif : Présenter Omega 3 et recueillir le retour du médecin.\n"
            "Produits discutés : Omega 3\n"
            "Discussion : Bénéfices cardiovasculaires, dosage et profil patients discutés.\n"
            "Réaction : Intéressé, souhaite de la documentation complémentaire.\n"
            "Résultat : Échange positif, opportunité de prescription identifiée.\n"
            "Prochaines actions : Envoyer brochure + planifier une 2ème visite."
        )
    return (
        "Date: 01/04/2026\n"
        "Client: Dr Ahmed Ben Ali — Cardiologist, Tunis\n"
        "Objective: Present Omega 3 and collect doctor feedback.\n"
        "Products discussed: Omega 3\n"
        "Discussion: Cardiovascular benefits, dosage, patient profile.\n"
        "Reaction: Interested, requested additional documentation.\n"
        "Outcome: Positive discussion, prescription opportunity identified.\n"
        "Next actions: Send brochure + schedule a 2nd visit."
    )


def _fb_missing(text: str, lang: str) -> list[str]:
    lower = (text or "").lower()
    if lang == "fr":
        checks = [
            (["date", "01/", "02/", "2025", "2026"],                      "Date manquante"),
            (["client", "dr", "médecin", "pharmacien"],                    "Client manquant"),
            (["cardiologue", "dermatologue", "pharmacien", "spécialité"],  "Spécialité manquante"),
            (["lieu", "tunis", "sfax", "sousse", "gabes"],                 "Lieu manquant"),
            (["objectif", "but", "présentation", "suivi"],                 "Objectif de la visite manquant"),
            (["produit", "médicament", "omega", "vitamine"],               "Produits discutés manquants"),
            (["discussion", "dosage", "bénéfice", "indication"],           "Discussion scientifique manquante"),
            (["réaction", "intéress", "objection", "positif"],             "Réaction du professionnel manquante"),
            (["résultat", "opportunité", "issue"],                         "Résultat / opportunité manquant"),
            (["prochaine", "suivi", "planifier", "envoyer"],               "Prochaines actions manquantes"),
        ]
    else:
        checks = [
            (["date", "01/", "2025", "2026"],                              "Date is missing"),
            (["client", "dr", "doctor", "pharmacist"],                     "Client is missing"),
            (["cardiologist", "specialty", "pharmacist"],                  "Specialty is missing"),
            (["location", "tunis", "sfax"],                                "Location is missing"),
            (["objective", "purpose", "presentation", "follow-up"],        "Visit objective is missing"),
            (["product", "omega", "vitamin"],                              "Products discussed are missing"),
            (["discussion", "dosage", "benefit", "indication"],            "Scientific discussion is missing"),
            (["reaction", "interested", "objection"],                      "Healthcare professional reaction is missing"),
            (["outcome", "opportunity", "result"],                         "Outcome / opportunity is missing"),
            (["next action", "follow-up", "send", "plan"],                 "Next actions are missing"),
        ]
    return [label for kws, label in checks if not any(k in lower for k in kws)]


def _fb_evaluate(text: str, lang: str) -> dict:
    missing = _fb_missing(text, lang)
    lower = (text or "").lower()
    if lang == "fr":
        if   len(missing) <= 2: verdict = "Rapport globalement bon, quelques améliorations possibles."
        elif len(missing) <= 5: verdict = "Rapport correct mais manque encore plusieurs éléments."
        else:                   verdict = "Rapport encore trop incomplet."
        strengths = (
            ["Produit identifiable"] if ("omega" in lower or "vitamine" in lower) else []
        ) + (["Réaction visible"] if "intéress" in lower else [])
        if not strengths:
            strengths = ["Base exploitable"]
    else:
        if   len(missing) <= 2: verdict = "Report is overall good, a few improvements possible."
        elif len(missing) <= 5: verdict = "Report is acceptable but missing several elements."
        else:                   verdict = "Report is still too incomplete."
        strengths = (
            ["Product is identifiable"] if ("omega" in lower or "vitamin" in lower) else []
        ) + (["Reaction is visible"] if "interested" in lower else [])
        if not strengths:
            strengths = ["Provides a usable starting point"]
    return {
        "overall_assessment": verdict,
        "strengths": strengths,
        "improvements": missing[:5] or (["Aucune amélioration majeure"] if lang == "fr" else ["No major improvement"]),
    }


# ══════════════════════════════════════════════════════════════════════
# Prompt builder
# ══════════════════════════════════════════════════════════════════════

def _build_prompt(raw_text: str, lang: str, intent: str, catalog_ctx: str = "") -> str:
    ctx = ""
    if catalog_ctx:
        ctx = (
            f"\nContexte catalogue (utilise seulement si pertinent) :\n{catalog_ctx}\n"
            if lang == "fr" else
            f"\nCatalogue context (use only if relevant):\n{catalog_ctx}\n"
        )

    if lang == "fr":
        if intent == "structure":
            return (
                "Le délégué demande la structure d'un rapport de visite.\n"
                "Réponds STRICTEMENT en JSON : "
                "{\"answer\": [{\"title\": \"...\", \"description\": \"...\"}, ...]}"
            )
        if intent == "example":
            return (
                "Donne un exemple clair et professionnel de rapport de visite pharmaceutique.\n"
                "Réponds STRICTEMENT en JSON : {\"answer\": \"exemple complet\"}"
            )
        if intent == "reformulate":
            return (
                f"Reformule ce texte de façon professionnelle et factuelle.{ctx}\n"
                "Ne pas inventer d'informations. Retourne uniquement le texte reformulé.\n"
                f"Réponds STRICTEMENT en JSON : {{\"answer\": \"texte reformulé\"}}\n\nTexte :\n\"\"\"{raw_text}\"\"\""
            )
        if intent == "missing_points":
            return (
                f"Identifie les points manquants dans ce rapport de visite.{ctx}\n"
                "Liste uniquement ce qui manque, sans reformuler.\n"
                f"Réponds STRICTEMENT en JSON : {{\"answer\": [\"point 1\", \"point 2\"]}}\n\nTexte :\n\"\"\"{raw_text}\"\"\""
            )
        if intent == "technical_help":
            return (
                f"Donne des suggestions techniques et commerciales pour enrichir ce texte.{ctx}\n"
                "Réponse concrète et professionnelle. Ne pas inventer.\n"
                f"Réponds STRICTEMENT en JSON : {{\"answer\": [\"suggestion 1\", \"suggestion 2\"]}}\n\nTexte :\n\"\"\"{raw_text}\"\"\""
            )
        if intent == "evaluate":
            return (
                f"Évalue brièvement ce rapport : points forts et points à améliorer.\n"
                "Réponds STRICTEMENT en JSON : "
                "{\"answer\": {\"overall_assessment\": \"...\", \"strengths\": [...], \"improvements\": [...]}}\n"
                f"\nTexte :\n\"\"\"{raw_text}\"\"\""
            )
        # question_answer (default)
        return (
            f"Réponds directement à la question du délégué.{ctx}\n"
            "Réponse professionnelle et claire. Ne pas inventer.\n"
            f"Réponds STRICTEMENT en JSON : {{\"answer\": \"réponse\"}}\n\nQuestion :\n\"\"\"{raw_text}\"\"\""
        )

    # English
    if intent == "structure":
        return (
            "The delegate is asking for the structure of a visit report.\n"
            "Return STRICTLY valid JSON: "
            "{\"answer\": [{\"title\": \"...\", \"description\": \"...\"}, ...]}"
        )
    if intent == "example":
        return (
            "Give a clear and professional example of a pharmaceutical visit report.\n"
            "Return STRICTLY valid JSON: {\"answer\": \"complete example\"}"
        )
    if intent == "reformulate":
        return (
            f"Reformulate this text in a professional and factual way.{ctx}\n"
            "Do not invent information. Return only the rewritten text.\n"
            f"Return STRICTLY valid JSON: {{\"answer\": \"rewritten text\"}}\n\nText:\n\"\"\"{raw_text}\"\"\""
        )
    if intent == "missing_points":
        return (
            f"Identify the missing points in this visit report.{ctx}\n"
            "List only what is missing, do not rewrite.\n"
            f"Return STRICTLY valid JSON: {{\"answer\": [\"point 1\", \"point 2\"]}}\n\nText:\n\"\"\"{raw_text}\"\"\""
        )
    if intent == "technical_help":
        return (
            f"Give technical and commercial suggestions to enrich this text.{ctx}\n"
            "Be concrete and professional. Do not invent.\n"
            f"Return STRICTLY valid JSON: {{\"answer\": [\"suggestion 1\", \"suggestion 2\"]}}\n\nText:\n\"\"\"{raw_text}\"\"\""
        )
    if intent == "evaluate":
        return (
            f"Briefly evaluate this report: strengths and improvements.\n"
            "Return STRICTLY valid JSON: "
            "{\"answer\": {\"overall_assessment\": \"...\", \"strengths\": [...], \"improvements\": [...]}}\n"
            f"\nText:\n\"\"\"{raw_text}\"\"\""
        )
    return (
        f"Answer the delegate's question directly.{ctx}\n"
        "Be professional and clear. Do not invent.\n"
        f"Return STRICTLY valid JSON: {{\"answer\": \"response\"}}\n\nQuestion:\n\"\"\"{raw_text}\"\"\""
    )


# ══════════════════════════════════════════════════════════════════════
# Result → markdown formatter
# ══════════════════════════════════════════════════════════════════════

def _to_markdown(parts: dict[str, Any], lang: str) -> str:
    lines: list[str] = []

    if "structure" in parts:
        hdr = "## Structure du rapport de visite" if lang == "fr" else "## Visit Report Structure"
        lines.append(hdr)
        sections = parts["structure"]
        if isinstance(sections, list):
            for s in sections:
                if isinstance(s, dict):
                    lines.append(f"**{s.get('title','')}** — {s.get('description','')}")
        lines.append("")

    if "example" in parts:
        hdr = "## Exemple de rapport" if lang == "fr" else "## Report Example"
        lines.append(hdr)
        lines.append("```")
        lines.append(str(parts["example"]))
        lines.append("```")
        lines.append("")

    if "reformulate" in parts:
        hdr = "## Texte reformulé" if lang == "fr" else "## Reformulated Text"
        lines.append(hdr)
        lines.append(str(parts["reformulate"]))
        lines.append("")

    if "missing_points" in parts:
        hdr = "## Points manquants" if lang == "fr" else "## Missing Points"
        lines.append(hdr)
        pts = parts["missing_points"]
        if isinstance(pts, list):
            for p in pts:
                lines.append(f"- {p}")
        else:
            lines.append(str(pts))
        lines.append("")

    if "technical_help" in parts:
        hdr = "## Suggestions techniques" if lang == "fr" else "## Technical Suggestions"
        lines.append(hdr)
        sugs = parts["technical_help"]
        if isinstance(sugs, list):
            for s in sugs:
                lines.append(f"- {s}")
        else:
            lines.append(str(sugs))
        lines.append("")

    if "evaluate" in parts:
        hdr = "## Évaluation du rapport" if lang == "fr" else "## Report Evaluation"
        lines.append(hdr)
        ev = parts["evaluate"]
        if isinstance(ev, dict):
            lines.append(f"**{ev.get('overall_assessment','')}**")
            if ev.get("strengths"):
                lines.append("")
                lines.append("Points forts :" if lang == "fr" else "Strengths:")
                for s in ev["strengths"]:
                    lines.append(f"- {s}")
            if ev.get("improvements"):
                lines.append("")
                lines.append("À améliorer :" if lang == "fr" else "Improvements:")
                for s in ev["improvements"]:
                    lines.append(f"- {s}")
        else:
            lines.append(str(ev))
        lines.append("")

    if "question_answer" in parts:
        hdr = "## Réponse" if lang == "fr" else "## Answer"
        lines.append(hdr)
        lines.append(str(parts["question_answer"]))
        lines.append("")

    return "\n".join(lines).strip()


# ══════════════════════════════════════════════════════════════════════
# Main agent class
# ══════════════════════════════════════════════════════════════════════

class ReportAgent:
    def __init__(self):
        self._llm = OpenAI(
            base_url=config.REPORT_BASE_URL,
            api_key=config.REPORT_API_KEY,
        )
        self._rag: _CatalogRAG | None = None

    # ── Public interface ──────────────────────────────────────────────

    def process(self, question: str) -> DataResult:
        result = DataResult(clarified_question=question)
        try:
            lang    = _detect_language(question)
            intents = _detect_intents(question, lang)
            parts: dict[str, Any] = {}

            for intent in intents:
                catalog_ctx = ""
                if self._should_use_rag(intent, question):
                    rag = self._get_rag()
                    if rag.ready:
                        chunks      = rag.search(question, top_k=4)
                        catalog_ctx = self._fmt_catalog(chunks, lang)

                parts[intent] = self._call_llm(question, lang, intent, catalog_ctx)

            result.analysis = _to_markdown(parts, lang)
        except Exception as e:
            result.error = f"Report Agent error: {e}"
        return result

    # ── RAG helpers ───────────────────────────────────────────────────

    def _get_rag(self) -> _CatalogRAG:
        if self._rag is None:
            self._rag = _CatalogRAG(
                config.REPORT_FAISS_INDEX,
                config.REPORT_FAISS_METADATA,
            )
        return self._rag

    def _should_use_rag(self, intent: str, text: str) -> bool:
        if intent not in ("technical_help", "question_answer", "reformulate"):
            return False
        lower = text.lower()
        return any(m in lower for m in [
            "omega 3", "omega-3", "omevie", "ferbiotic", "bactol", "calmoss",
            "cosmopharma", "hydra", "minciligne", "mincivit", "oligovit",
            "pediakids", "phytol", "phytophane", "phytothera", "plantherapie",
            "tidol", "uniderm", "vitonic", "vitosine", "healthcare",
            "magnésium", "magnesium", "vitamine", "vitamin",
            "probiotique", "probiotic",
        ])

    def _fmt_catalog(self, chunks: list[dict], lang: str) -> str:
        if not chunks:
            return ""
        hdr = "Contexte catalogue produit :" if lang == "fr" else "Product catalogue context:"
        lines = [hdr]
        for i, c in enumerate(chunks, 1):
            lines.append(
                f"[{i}] Gamme: {c.get('gamme','')} | "
                f"Titre: {c.get('title','')} | "
                f"{c.get('content','')}"
            )
        return "\n\n".join(lines)

    # ── LLM call + JSON parse ─────────────────────────────────────────

    def _call_llm(self, text: str, lang: str, intent: str, catalog_ctx: str = "") -> Any:
        prompt = _build_prompt(text, lang, intent, catalog_ctx)
        try:
            resp = self._llm.chat.completions.create(
                model=config.REPORT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional assistant for pharmaceutical delegates. "
                            "Always respond with valid JSON exactly as requested."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            content = (resp.choices[0].message.content or "").strip()
            # Strip markdown code fence if model wraps the JSON
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content.strip())
            parsed  = json.loads(content)
            return parsed.get("answer", parsed)
        except Exception:
            return self._fallback(text, lang, intent)

    def _fallback(self, text: str, lang: str, intent: str) -> Any:
        if intent == "structure":      return _fb_structure(lang)
        if intent == "example":        return _fb_example(lang)
        if intent == "missing_points": return _fb_missing(text, lang)
        if intent == "evaluate":       return _fb_evaluate(text, lang)
        if intent == "reformulate":    return text
        if intent == "technical_help":
            lower = (text or "").lower()
            if lang == "fr":
                tips = ["Préciser l'objectif exact", "Mentionner le dosage discuté",
                        "Ajouter le profil patient", "Décrire les objections éventuelles"]
                if "omega" in lower: tips.append("Mentionner les bénéfices cardiovasculaires")
            else:
                tips = ["Specify exact visit objective", "Mention dosage discussed",
                        "Add patient profile", "Describe any objections raised"]
                if "omega" in lower: tips.append("Mention cardiovascular benefits")
            return tips
        return ("Précisez votre demande." if lang == "fr"
                else "Please clarify your request.")
