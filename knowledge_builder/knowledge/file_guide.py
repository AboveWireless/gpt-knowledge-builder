from __future__ import annotations


def build_file_guide(files: list[str]) -> str:
    lines = ["Knowledge Package File Guide", ""]
    for file_name in files:
        lines.append(f"- {file_name}: {_describe_file(file_name)}")
    return "\n".join(lines).strip()


def _describe_file(file_name: str) -> str:
    normalized = file_name.lower()
    if "__knowledge_core__" in normalized:
        return "Topic-based synthesized knowledge for answering questions across the corpus."
    if "__reference_facts" in normalized:
        return "High-precision facts, requirements, identifiers, dates, and thresholds."
    if "__glossary" in normalized:
        return "High-confidence terminology, definitions, and acronym expansions."
    if "__procedures" in normalized:
        return "Actionable steps, workflows, and checklist-style instructions."
    if "__entities" in normalized:
        return "Named organizations, standards, products, systems, documents, and codes."
    if normalized == "instructions.txt":
        return "Guidance telling the GPT how to use the package."
    if normalized == "file_guide.txt":
        return "Short description of each file in the package."
    return "Knowledge file."
