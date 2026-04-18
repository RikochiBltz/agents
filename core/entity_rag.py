"""
Entity RAG — fast in-memory lookup for doctors and products.

Injected into the DataAgent system prompt so the LLM can resolve
entity references (doctor names, specialties, cities, product names)
without spending tool-call rounds on DB searches.

When a doctor is matched, products relevant to their specialty are
automatically included so the LLM can recommend them.

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
    Exact match (score +2) or 4-char prefix match (score +1).
    E.g. 'cardiologue' matches 'cardiologie' via shared prefix 'card'.
    """
    score = 0
    for qt in q_tokens:
        for it in item_tokens:
            if qt == it:
                score += 2
                break
            elif len(qt) >= 4 and (qt.startswith(it[:4]) or it.startswith(qt[:4])):
                score += 1
                break
    return score


# ── specialty → product keyword expansions ────────────────────────────
# Maps a specialty prefix (lowercase) to French keywords that appear in
# product indications. Used to find relevant products for a given doctor.

_SPECIALTY_EXPANSIONS: dict[str, list[str]] = {
    # Cardiology → cholesterol / cardiovascular products
    "cardio": [
        "cholesterol", "cholestérol", "cardiovasculaire", "circulation",
        "coenzyme", "antioxydant", "graisse",
    ],
    # Pediatrics → full PEDIAKIDS range
    "pédiatr": [
        "enfant", "bébé", "nourrisson", "croissance", "pediakids",
        "toux", "gorge", "respiratoires", "sommeil", "digestion", "gaz",
        "vitamines", "calcium",
    ],
    # Dermatology → skin / hair / nail products
    "dermatol": [
        "peau", "ongles", "cheveux", "acné", "taches", "épiderme",
        "éclaircissant", "hydratation", "sébum", "pellicules",
    ],
    # Gynecology / Obstetrics / Maternity
    "gynécol": [
        "grossesse", "ménopause", "allaitement", "hormonal", "féminin",
        "ovulation", "menstruel", "dysménorrhée", "préconception", "fertilité",
    ],
    "obstétr": ["grossesse", "allaitement", "enceinte", "fer"],
    "maternit": ["grossesse", "allaitement", "enceinte", "fer"],
    # Pulmonology / ENT / Respiratory
    "pneumol": [
        "respiratoires", "toux", "bronchite", "expectorant", "gorge",
        "encombremen", "poumons",
    ],
    "orl": [
        "gorge", "nasal", "rhinite", "toux", "respiratoires", "antiseptique",
    ],
    # Neurology / Psychiatry / Psychology
    "neurolog": [
        "mémoire", "concentration", "cérébral", "cerébral", "omega",
        "sommeil", "stress",
    ],
    "psychiatr": [
        "stress", "anxiété", "humeur", "sommeil", "fatigue", "adaptogène",
        "millepertuis", "ashwagandha",
    ],
    "psycholog": ["stress", "anxiété", "humeur", "sommeil", "millepertuis"],
    # Rheumatology / Sports medicine
    "rhumato": [
        "articulaire", "musculaire", "douleurs", "inflammatoire",
        "traumatismes", "contusions", "arnica",
    ],
    "sport": ["musculaire", "articulaire", "préparation", "relaxant", "sportifs"],
    # Gastroenterology / Hepatology
    "gastro": [
        "digestif", "transit", "ballonnement", "digestion", "flatulences",
        "cholestérol", "intestin", "colon", "foie",
    ],
    # Endocrinology / Metabolism / Obesity
    "endocrin": [
        "cholestérol", "glycémie", "obésité", "poids", "graisse",
        "minceur", "appétit",
    ],
    "diabétol": ["glycémie", "diabétiques", "cholestérol"],
    "obésit": ["poids", "minceur", "coupe-faim", "graisse"],
    # Stomatology / Dentistry
    "stomato": ["gencives", "buccale", "dentaire", "haleine", "antiseptique"],
    "dentist": ["gencives", "buccale", "dentaire", "haleine"],
    # Trichology / Dermatology (hair)
    "tricholog": ["cheveux", "ongles", "pellicules", "repousse", "chute"],
    "capillair": ["cheveux", "pellicules", "repousse", "brillance"],
    # Oncology / Palliative
    "oncolog": [
        "immunostimulant", "fortifiant", "antioxydant", "vieillissement",
        "cellulaire", "spiruline", "convalescence",
    ],
    # Allergology / Immunology
    "allergol": ["allergènes", "immunitaire", "rhinite", "anticorps"],
    "immunolog": ["immunostimulant", "immunité", "anticorps", "défenses"],
    # Sexology / Andrology / Fertility
    "sexolog": ["sexuelles", "libido", "fertilité", "sperme", "performances"],
    "androlog": ["fertilité", "sperme", "performances", "libido"],
    # Ophthalmology
    "ophtalmol": ["yeux", "vision", "omega"],
    # Urology / Nephrology
    "urolog": ["prostate", "urinaire", "drainage"],
    "néphrol": ["drainage", "draineur", "urinaire"],
    # General medicine / Family medicine / Internal medicine
    "générale": [
        "fortifiant", "immunité", "fatigue", "vitalité", "tonus",
        "vitamines", "surmenage",
    ],
    "famille": [
        "fortifiant", "immunité", "fatigue", "vitalité", "tonus",
        "vitamines", "surmenage",
    ],
    "interne": [
        "fortifiant", "immunité", "fatigue", "vitalité", "convalescence",
    ],
    # Senior / Geriatrics
    "gériatr": [
        "sénior", "mémoire", "asthénie", "antioxydant", "vieillissement",
        "défenses",
    ],
    # Pediatric nutrition / diet
    "nutriti": ["poids", "appétit", "croissance", "vitamines", "nutritifs"],
}


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
                nom        = row.get("Nom", "").strip()
                prenom     = row.get("Prenom", "").strip()
                specialite = row.get("Specialite", "").strip()
                ville      = row.get("VilleAdresseCourrier", "").strip()
                crom       = row.get("CROM", "").strip()
                ordre      = row.get("NumeroOrdre", "").strip()
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

    @staticmethod
    def _is_person_lookup(query: str) -> bool:
        """
        Returns True when the query is directly about finding/showing a person
        (not about analysing their sales, visits, or products).
        In that case specialty product recommendations are skipped — they add
        noise without value for a simple person-lookup.
        """
        q = query.lower()
        lookup_signals = [
            # French
            "qui est", "cherche", "trouve", "info sur", "information sur",
            "fiche", "coordonnées", "numéro", "téléphone", "email", "adresse",
            "existe", "existe-t-il", "montre", "donne moi", "parle moi",
            "dis moi", "profil", "détails sur", "renseigne",
            # English
            "who is", "find", "search", "info about", "information about",
            "tell me about", "give me information", "details about",
            "show me", "look up", "lookup", "profile of",
        ]
        analysis_signals = [
            "vente", "ca ", "chiffre", "visite", "commande", "solde",
            "produit", "analyse", "comparaison", "performance",
        ]
        has_lookup   = any(s in q for s in lookup_signals)
        has_analysis = any(s in q for s in analysis_signals)
        # If explicit analysis signals → not a pure lookup
        if has_analysis:
            return False
        return has_lookup

    def get_doctor_hits(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Returns raw doctor records matching the query (without formatting).
        Used by DataAgent to build a direct registry result.
        """
        q_tokens = _tokens(query)
        if not q_tokens:
            return []
        hits = self._rank(self._doctors, q_tokens, min_score=2, top_k=top_k)
        return [d for _, d in hits]

    def doctor_result(self, query: str, top_k: int = 5) -> dict | None:
        """
        Returns a DataAgent-compatible result dict built from registry data.
        Returns None if no doctors match.
        Used to short-circuit DB lookup for doctor profile queries.
        """
        hits = self.get_doctor_hits(query, top_k=top_k)
        if not hits:
            return None
        columns = ["nom", "prenom", "specialite", "ville", "crom", "ordre"]
        rows = [
            {
                "nom":        d["nom"],
                "prenom":     d["prenom"],
                "specialite": d["specialite"],
                "ville":      d["ville"],
                "crom":       d["crom"],
                "ordre":      d["ordre"],
            }
            for d in hits
        ]
        return {
            "source":     "national_registry",
            "totalRows":  len(rows),
            "totalPages": 1,
            "columns":    columns,
            "rows":       rows,
        }

    def search(self, query: str, doctor_top_k: int = 5, product_top_k: int = 5) -> str:
        """
        Returns a formatted Markdown block with:
          - Matched doctors
          - Products relevant to those doctors' specialties (skipped for person-lookups)
          - Products directly matched by the query (if any)
        Returns empty string if nothing relevant is found.
        """
        q_tokens = _tokens(query)
        if not q_tokens:
            return ""

        doctor_hits  = self._rank(self._doctors,  q_tokens, min_score=2, top_k=doctor_top_k)
        product_hits = self._rank(self._products, q_tokens, min_score=1, top_k=product_top_k)

        # Specialty products are only useful for visit/sales/analysis queries
        person_lookup = self._is_person_lookup(query)

        # Collect specialty-based product recommendations from matched doctors
        specialty_products: dict[str, list[dict]] = {}  # specialty → product list
        seen_product_keys: set[str] = set()

        if doctor_hits and not person_lookup:
            # Track which products were directly query-matched to avoid duplicates
            for _, p in product_hits:
                seen_product_keys.add(f"{p['nom']}|{p['forme']}")

            # For each unique specialty among matched doctors, find relevant products
            seen_specialties: set[str] = set()
            for _, d in doctor_hits:
                spec = d["specialite"]
                if not spec or spec in seen_specialties:
                    continue
                seen_specialties.add(spec)

                rec = self._products_for_specialty(spec, top_k=5, exclude=seen_product_keys)
                if rec:
                    specialty_products[spec] = rec
                    for p in rec:
                        seen_product_keys.add(f"{p['nom']}|{p['forme']}")

        if not doctor_hits and not product_hits:
            return ""

        lines = [
            "## KNOWN ENTITIES (resolved from national registry)\n",
            "> These records come from an external registry, NOT from the CRM database.",
            "> Use the exact **Nom/Prénom** listed here for any DB name filters",
            "> — it is the canonical spelling.",
            "> The CRM data (sales, visits, balances) is still in the database and must be queried.\n",
        ]

        # ── Doctors ──────────────────────────────────────────────────
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

        # ── Specialty product recommendations ─────────────────────────
        if specialty_products:
            lines.append("### Recommended products by specialty")
            for specialty, prods in specialty_products.items():
                lines.append(f"\n**{specialty}**")
                for p in prods:
                    parts = [f"- **{p['nom']}**"]
                    if p["forme"]:
                        parts[0] += f" ({p['forme']})"
                    if p["categorie"]:
                        parts.append(f"Catégorie: {p['categorie']}")
                    if p["indications"]:
                        parts.append(f"Indications: {p['indications']}")
                    lines.append("  " + " | ".join(parts))
            lines.append("")

        # ── Directly matched products (by query, not specialty) ───────
        if product_hits:
            lines.append("### Products matching query")
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

    def _products_for_specialty(
        self,
        specialty: str,
        top_k: int = 5,
        exclude: set[str] | None = None,
    ) -> list[dict]:
        """
        Find products relevant to a medical specialty.
        Uses keyword expansion to bridge medical jargon and product indications.
        """
        spec_lower = specialty.lower()

        # Build expanded token set from expansion map
        extra_keywords: list[str] = []
        for prefix, keywords in _SPECIALTY_EXPANSIONS.items():
            if spec_lower.startswith(prefix) or prefix in spec_lower:
                extra_keywords.extend(keywords)

        # Combine specialty tokens with expanded keywords
        spec_tokens = _tokens(specialty) | _tokens(" ".join(extra_keywords))

        if not spec_tokens:
            return []

        exclude = exclude or set()
        candidates: list[tuple[int, dict]] = []
        for p in self._products:
            key = f"{p['nom']}|{p['forme']}"
            if key in exclude:
                continue
            score = _partial_overlap(spec_tokens, p["_tokens"])
            if score >= 1:
                candidates.append((score, p))

        candidates.sort(key=lambda x: x[0], reverse=True)

        # Deduplicate by product name (keep highest-scored form)
        seen_names: set[str] = set()
        result: list[dict] = []
        for _, p in candidates:
            if p["nom"] not in seen_names:
                seen_names.add(p["nom"])
                result.append(p)
            if len(result) >= top_k:
                break
        return result

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
