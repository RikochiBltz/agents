"""
Entity RAG — fast in-memory lookup for doctors and products.

Injected into the DataAgent system prompt so the LLM can resolve
entity references (doctor names, specialties, cities, product names)
without spending tool-call rounds on DB searches.

No ML dependencies — uses token-overlap scoring.
Doctors CSV  : ~31 000 rows  →  loaded once, queried in <5 ms
Products JSON: ~113 entries  →  brute-force is fine
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────

_STOPWORDS = {
    "dr", "docteur", "le", "la", "les", "de", "du", "des", "un", "une",
    "et", "en", "au", "aux", "par", "sur", "dans", "the", "of", "and",
}


def _tokens(text: str) -> set[str]:
    raw = set(re.findall(r"\w+", text.lower()))
    return {t for t in raw if len(t) >= 3 and t not in _STOPWORDS}


def _partial_overlap(q_tokens: set[str], item_tokens: set[str]) -> int:
    """
    Count tokens that are an exact match OR a prefix match (min 4 chars).
    E.g. 'cardiologue' matches 'cardiologie' because both start with 'cardiol'.
    """
    score = 0
    for qt in q_tokens:
        for it in item_tokens:
            if qt == it:
                score += 2          # exact match worth more
                break
            elif len(qt) >= 4 and (qt.startswith(it[:4]) or it.startswith(qt[:4])):
                score += 1
                break
    return score


# ── main class ────────────────────────────────────────────────────────

class EntityRAG:
    """
    Usage:
        rag = EntityRAG(doctors_csv="doctors.csv", products_json="prod_vital.json")
        context_block = rag.search("Dr. Ben Ali cardiologue Tunis")
        # inject context_block into DataAgent system prompt
    """

    def __init__(self, doctors_csv: str, products_json: str):
        self._doctors:  list[dict] = []
        self._products: list[dict] = []
        self._load_doctors(doctors_csv)
        self._load_products(products_json)

    # ── loaders ───────────────────────────────────────────────────────

    def _load_doctors(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                nom       = row.get("Nom", "").strip()
                prenom    = row.get("Prenom", "").strip()
                specialite= row.get("Specialite", "").strip()
                ville     = row.get("VilleAdresseCourrier", "").strip()
                crom      = row.get("CROM", "").strip()
                ordre     = row.get("NumeroOrdre", "").strip()
                self._doctors.append({
                    "nom":        nom,
                    "prenom":     prenom,
                    "specialite": specialite,
                    "ville":      ville,
                    "crom":       crom,
                    "ordre":      ordre,
                    "_tokens":    _tokens(f"{nom} {prenom} {specialite} {ville}"),
                })

    def _load_products(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for category, products in data.items():
            for prod in products:
                nom    = prod.get("nom", "").strip()
                forme  = prod.get("forme", "").strip()
                indics = prod.get("indications", [])
                if isinstance(indics, list):
                    indics_str = ", ".join(indics)
                else:
                    indics_str = str(indics)
                self._products.append({
                    "nom":         nom,
                    "forme":       forme,
                    "categorie":   category,
                    "indications": indics_str,
                    "_tokens":     _tokens(f"{nom} {category} {indics_str}"),
                })

    # ── public interface ──────────────────────────────────────────────

    def search(self, query: str, doctor_top_k: int = 5, product_top_k: int = 5) -> str:
        """
        Returns a formatted Markdown block with matching doctors and products.
        Empty string if nothing is relevant enough to be worth injecting.
        """
        q_tokens = _tokens(query)
        if not q_tokens:
            return ""

        doctor_hits  = self._rank(self._doctors,  q_tokens, min_score=2, top_k=doctor_top_k)
        product_hits = self._rank(self._products, q_tokens, min_score=1, top_k=product_top_k)

        if not doctor_hits and not product_hits:
            return ""

        lines = ["## KNOWN ENTITIES (resolved locally — use these to build precise filters)\n"]

        if doctor_hits:
            lines.append("### Doctors")
            for _, d in doctor_hits:
                name  = f"{d['nom']} {d['prenom']}".strip()
                parts = [f"**{name}**"]
                if d["specialite"]:
                    parts.append(f"Spécialité: {d['specialite']}")
                if d["ville"]:
                    parts.append(f"Ville: {d['ville']}")
                if d["crom"]:
                    parts.append(f"CROM: {d['crom']}")
                if d["ordre"]:
                    parts.append(f"N°Ordre: {d['ordre']}")
                lines.append("- " + " | ".join(parts))
            lines.append("")

        if product_hits:
            lines.append("### Products")
            for _, p in product_hits:
                parts = [f"**{p['nom']}**"]
                if p["forme"]:
                    parts.append(f"Forme: {p['forme']}")
                if p["categorie"]:
                    parts.append(f"Catégorie: {p['categorie']}")
                if p["indications"]:
                    parts.append(f"Indications: {p['indications']}")
                lines.append("- " + " | ".join(parts))
            lines.append("")

        return "\n".join(lines)

    @property
    def doctor_count(self) -> int:
        return len(self._doctors)

    @property
    def product_count(self) -> int:
        return len(self._products)

    # ── internal ──────────────────────────────────────────────────────

    @staticmethod
    def _rank(
        items: list[dict],
        q_tokens: set[str],
        min_score: int,
        top_k: int,
    ) -> list[tuple[int, dict]]:
        scored: list[tuple[int, dict]] = []
        for item in items:
            score = _partial_overlap(q_tokens, item["_tokens"])
            if score >= min_score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]
