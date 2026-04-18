"""
Doctor Agent — Pipeline 3

Answers questions about doctor profiles using the national registry
(doctors.csv) and recommends relevant products based on their specialty.

Uses a small local LLM (llama3.1:8b) for formatting — no DB queries.
"""
from __future__ import annotations

from openai import OpenAI

import config
from agents.data_agent import DataResult
from core.entity_rag import EntityRAG


class DoctorAgent:
    def __init__(self, entity_rag: EntityRAG):
        self.entity_rag = entity_rag
        self._llm = OpenAI(
            base_url=config.DOCTOR_BASE_URL,
            api_key=config.DOCTOR_API_KEY,
        )

    def process(self, question: str) -> DataResult:
        result = DataResult(clarified_question=question)

        # ── 1. Lookup doctors from registry ──────────────────────────
        hits = self.entity_rag.get_doctor_hits(question, top_k=5)

        if not hits:
            result.analysis = (
                "Aucun médecin correspondant n'a été trouvé dans le registre national."
                if self._is_french(question)
                else "No matching doctor found in the national registry."
            )
            return result

        # ── 2. Get specialty product recommendations ──────────────────
        specialty_products: dict[str, list[dict]] = {}
        seen_specs: set[str] = set()
        for d in hits:
            spec = d["specialite"]
            if spec and spec not in seen_specs:
                seen_specs.add(spec)
                prods = self.entity_rag._products_for_specialty(spec, top_k=4)
                if prods:
                    specialty_products[spec] = prods

        # ── 3. Build LLM prompt ───────────────────────────────────────
        lang = "fr" if self._is_french(question) else "en"
        system, user_msg = self._build_prompt(question, hits, specialty_products, lang)

        try:
            resp = self._llm.chat.completions.create(
                model=config.DOCTOR_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_msg},
                ],
            )
            result.analysis = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            # Fallback: plain text from registry data
            result.analysis = self._fallback(hits, specialty_products, lang)

        return result

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _is_french(text: str) -> bool:
        french_markers = {"dr", "médecin", "docteur", "info", "donne", "donne-moi",
                          "sur", "quel", "quelle", "qui", "est", "les", "des", "une"}
        words = set(text.lower().split())
        return bool(words & french_markers)

    def _build_prompt(
        self,
        question: str,
        hits: list[dict],
        specialty_products: dict[str, list[dict]],
        lang: str,
    ) -> tuple[str, str]:
        if lang == "fr":
            system = (
                "Tu es un assistant CRM médical. Tu reçois des informations sur un ou plusieurs "
                "médecins issues du registre national tunisien, ainsi que les produits recommandés "
                "selon leur spécialité. Présente ces informations de façon claire et structurée. "
                "Réponds en français. Sois concis — pas de fioritures."
            )
        else:
            system = (
                "You are a medical CRM assistant. You receive doctor information from the Tunisian "
                "national registry along with recommended products for their specialty. "
                "Present this information clearly and concisely in English."
            )

        # Build doctor block
        doctor_lines = []
        for d in hits:
            name = f"{d['nom']} {d['prenom']}".strip()
            parts = [f"**{name}**"]
            if d["specialite"]: parts.append(f"Spécialité: {d['specialite']}")
            if d["ville"]:      parts.append(f"Ville: {d['ville']}")
            if d["crom"]:       parts.append(f"CROM: {d['crom']}")
            if d["ordre"]:      parts.append(f"N°Ordre: {d['ordre']}")
            doctor_lines.append(" | ".join(parts))

        # Build product block
        product_lines = []
        for spec, prods in specialty_products.items():
            product_lines.append(f"\n**{spec}**")
            for p in prods:
                name = p["nom"] + (f" ({p['forme']})" if p["forme"] else "")
                product_lines.append(f"  - {name}: {p['indications']}")

        user_msg_parts = [
            f"Question: {question}\n",
            "Doctors found in registry:",
            *doctor_lines,
        ]
        if product_lines:
            user_msg_parts.append("\nRecommended products by specialty:")
            user_msg_parts.extend(product_lines)

        return system, "\n".join(user_msg_parts)

    @staticmethod
    def _fallback(
        hits: list[dict],
        specialty_products: dict[str, list[dict]],
        lang: str,
    ) -> str:
        lines = []
        if lang == "fr":
            lines.append("## Résultats du registre national\n")
            for d in hits:
                name = f"{d['nom']} {d['prenom']}".strip()
                lines.append(f"**{name}**")
                if d["specialite"]: lines.append(f"- Spécialité : {d['specialite']}")
                if d["ville"]:      lines.append(f"- Ville : {d['ville']}")
                if d["crom"]:       lines.append(f"- CROM : {d['crom']}")
                if d["ordre"]:      lines.append(f"- N°Ordre : {d['ordre']}")
                lines.append("")
            if specialty_products:
                lines.append("## Produits recommandés\n")
                for spec, prods in specialty_products.items():
                    lines.append(f"**{spec}**")
                    for p in prods:
                        lines.append(f"- {p['nom']}: {p['indications']}")
                    lines.append("")
        else:
            lines.append("## National Registry Results\n")
            for d in hits:
                name = f"{d['nom']} {d['prenom']}".strip()
                lines.append(f"**{name}**")
                if d["specialite"]: lines.append(f"- Specialty: {d['specialite']}")
                if d["ville"]:      lines.append(f"- City: {d['ville']}")
                if d["ordre"]:      lines.append(f"- Order No: {d['ordre']}")
                lines.append("")
            if specialty_products:
                lines.append("## Recommended Products\n")
                for spec, prods in specialty_products.items():
                    lines.append(f"**{spec}**")
                    for p in prods:
                        lines.append(f"- {p['nom']}: {p['indications']}")
                    lines.append("")
        return "\n".join(lines)
