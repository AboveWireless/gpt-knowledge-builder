from __future__ import annotations


def build_instructions(corpus_name: str, included_files: list[str]) -> str:
    return "\n".join(
        [
            f"Custom GPT Knowledge Package: {corpus_name}",
            "",
            "Use these files as a compact knowledge base, not as raw document dumps.",
            "Prioritize topic-oriented knowledge_core pages first, then exact reference facts, then procedures and glossary entries.",
            "Prefer precise facts, requirements, and explicit definitions over broad summaries.",
            "If the files do not provide enough evidence for an answer, say so clearly.",
            "",
            "File priority:",
            "1. <corpus>__knowledge_core__pNN.md for synthesized topic knowledge across the corpus.",
            "2. <corpus>__reference_facts.md for exact values, dates, identifiers, standards, and requirements.",
            "3. <corpus>__procedures.md for actionable instructions and checklists.",
            "4. <corpus>__glossary.md for high-confidence definitions and acronym expansions.",
            "5. <corpus>__entities.md for named organizations, products, systems, standards, and codes.",
            "",
            "Included files:",
            *[f"- {name}" for name in included_files],
        ]
    ).strip()
