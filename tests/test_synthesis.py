from pathlib import Path

from knowledge_builder.compiler_models import BuildOptions
from knowledge_builder.gpt_compiler import compile_gpt_knowledge_pack
from knowledge_builder.knowledge.facts import extract_fact_candidates
from knowledge_builder.knowledge.glossary import extract_glossary_candidates
from knowledge_builder.knowledge.procedures import extract_procedure_candidates
from knowledge_builder.synthesis import (
    build_entities,
    build_glossary,
    build_knowledge_core_pages,
    build_procedures,
    build_reference_facts,
    build_source_knowledge,
    clean_text_for_knowledge,
)


def test_glossary_fragment_rejection():
    raw = "TERM - broken fragment\nTM\nABC DEF\nGrounding means intentional connection to earth.\n"
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("glossary.txt"), "txt", "Glossary", raw, clean)

    terms = [term for term, _definition in knowledge.glossary]
    assert "Grounding" in terms
    assert "TERM" not in terms


def test_procedure_fragment_rejection():
    raw = (
        "Procedure Overview\n\n"
        "1. Install bracket.\n"
        "2. Tighten bolts.\n"
        "3. Verify bond continuity.\n"
        "1. Broken\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("procedure.txt"), "txt", "Procedure", raw, clean)

    procedures_text = build_procedures([knowledge])
    assert "Install bracket." in procedures_text
    assert "Verify bond continuity." in procedures_text
    assert "1. Broken" not in procedures_text


def test_fact_dedupe():
    raw = (
        "The installer shall verify grounding continuity.\n"
        "The installer shall verify grounding continuity.\n"
        "Voltage: 48 V.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("facts.txt"), "txt", "Facts", raw, clean)

    facts_text = build_reference_facts([knowledge])
    assert facts_text.count("verify grounding continuity") == 1
    assert "48 V" in facts_text


def test_topic_based_knowledge_core_grouping():
    raw1 = (
        "# Grounding\n\n"
        "Grounding means the intentional connection to earth.\n\n"
        "The installer shall bond the cabinet to the grounding bus.\n"
    )
    raw2 = (
        "# Grounding\n\n"
        "Grounding conductor resistance should remain within the specified range.\n\n"
        "# Safety\n\n"
        "WARNING: Disconnect power before service.\n"
    )
    item1 = build_source_knowledge(Path("doc1.txt"), "txt", "Doc One", raw1, clean_text_for_knowledge(raw1))
    item2 = build_source_knowledge(Path("doc2.txt"), "txt", "Doc Two", raw2, clean_text_for_knowledge(raw2))

    pages = build_knowledge_core_pages([item1, item2], target_words=500)
    combined = "\n\n".join(pages)

    assert "## Grounding" in combined
    assert "Sources: doc1.txt, doc2.txt" in combined or "Sources: doc2.txt, doc1.txt" in combined
    assert "## Doc One" not in combined


def test_candidate_extractors_return_scored_items():
    raw = (
        "Grounding means intentional connection to earth.\n"
        "1. Remove cover.\n"
        "2. Tighten lug.\n"
        "The installer shall verify torque is 45 Nm.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("doc.txt"), "txt", "Doc", raw, clean)

    assert extract_glossary_candidates(knowledge.chunks)
    assert extract_procedure_candidates(knowledge.chunks)
    assert extract_fact_candidates(knowledge.chunks)

    assert build_glossary([knowledge]).startswith("# Glossary")


def test_drawing_boilerplate_is_rejected_from_glossary_and_knowledge_core():
    raw = (
        "REVISION 3\n"
        "SHEET NO A1.01\n"
        "ISSUED FOR PERMIT\n"
        "ENGINEER SEAL\n"
        "Copyright 2025 Example Engineers\n"
        "Phone 555-1212 Fax 555-3434 www.example.com\n\n"
        "GEC: Grounding electrode conductor.\n\n"
        "Grounding conductor shall be bonded to the grounding bus.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("drawing.txt"), "txt", "Drawing", raw, clean)

    glossary_text = build_glossary([knowledge])
    core_text = "\n\n".join(build_knowledge_core_pages([knowledge], target_words=500))

    assert "## GEC" in glossary_text
    assert "AS SOON AS A PO" not in glossary_text
    assert "ENGINEER SEAL" not in core_text
    assert "ISSUED FOR PERMIT" not in core_text
    assert "Copyright 2025" not in core_text


def test_general_note_lists_do_not_promote_as_procedures():
    raw = (
        "GENERAL NOTES\n\n"
        "1. Contractor shall coordinate with owner.\n"
        "2. Contractor shall verify field conditions.\n"
        "3. Drawings are diagrammatic only.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("notes.txt"), "txt", "General Notes", raw, clean)

    procedures_text = build_procedures([knowledge])
    assert procedures_text == ""


def test_empty_reference_fact_pages_are_not_emitted(tmp_path: Path):
    input_dir = tmp_path / "Construction Drawings"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "drawing.txt").write_text(
        "REVISION 2\nSHEET NO A2.01\nISSUED FOR CONSTRUCTION\nENGINEER SEAL\nCopyright 2025 Example\n",
        encoding="utf-8",
    )

    result = compile_gpt_knowledge_pack(
        BuildOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            pack_name="construction_drawings",
        )
    )

    package_files = sorted(path.name for path in result.package_dir.iterdir())
    assert not any("__reference_facts" in name for name in package_files)


def test_glossary_rejects_generic_note_headings_and_fragments():
    raw = (
        "NOTE: Contractor shall verify field conditions.\n"
        "ALL CONSTRUCTION - coordinate with owner.\n"
        "GEC: Grounding electrode conductor.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("glossary_notes.txt"), "txt", "Glossary Notes", raw, clean)

    glossary_text = build_glossary([knowledge])
    assert "## GEC" in glossary_text
    assert "## NOTE" not in glossary_text
    assert "## ALL CONSTRUCTION" not in glossary_text


def test_glossary_rejects_generic_labels_and_coordinates():
    raw = (
        "DESCRIPTION: Tower layout.\n"
        "LEGAL: Copyright notice.\n"
        "Option 1: Alternate route.\n"
        "LAT: 32.1234\n"
        "GEC: Grounding electrode conductor.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("glossary_noise.txt"), "txt", "Glossary Noise", raw, clean)

    glossary_text = build_glossary([knowledge])
    assert "## GEC" in glossary_text
    assert "## DESCRIPTION" not in glossary_text
    assert "## LEGAL" not in glossary_text
    assert "## Option 1" not in glossary_text
    assert "## LAT" not in glossary_text


def test_entities_filter_false_positives_from_drawing_noise():
    raw = (
        "NECESSARY\n"
        "SHALL\n"
        "QTY\n"
        "SIZE\n"
        "ANSI/TIA-222-H\n"
        "OpenAI Tower System\n"
        "Model: ABC-1234\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("entities.txt"), "txt", "Entities", raw, clean)

    entities_text = build_entities([knowledge])
    assert "NECESSARY" not in entities_text
    assert "SHALL" not in entities_text
    assert "QTY" not in entities_text
    assert "SIZE" not in entities_text
    assert "ANSI/TIA-222-H" in entities_text
    assert "ABC-1234" in entities_text
    assert "ANSI (" not in entities_text
    assert "TIA (" not in entities_text
    assert "## Document" not in entities_text


def test_entities_reject_more_generic_admin_words():
    raw = (
        "ISOLATED\n"
        "NUMBERS/TAGS\n"
        "DESCRIPTION\n"
        "SITE\n"
        "NUMBER\n"
        "Model: ZX-9000\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("entity_noise.txt"), "txt", "Entity Noise", raw, clean)

    entities_text = build_entities([knowledge])
    assert "ISOLATED" not in entities_text
    assert "NUMBERS/TAGS" not in entities_text
    assert "DESCRIPTION" not in entities_text
    assert "SITE" not in entities_text
    assert "NUMBER" not in entities_text
    assert "ZX-9000" in entities_text


def test_knowledge_core_rejects_sheet_label_anchor_without_substantive_body():
    raw = (
        "# TITLE PAGE\n\n"
        "Prepared for 123 Main Street Project Number 55.\n\n"
        "# Grounding System\n\n"
        "The grounding bus shall bond tower steel, coax entry panels, and surge protection devices.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("topic.txt"), "txt", "Topic", raw, clean)

    core_text = "\n\n".join(build_knowledge_core_pages([knowledge], target_words=500))
    assert "## TITLE PAGE" not in core_text
    assert "## Grounding System" in core_text or "Grounding" in core_text


def test_knowledge_core_rejects_site_number_and_description_admin_sections():
    raw = (
        "# SITE NUMBER\n\n"
        "SITE NUMBER: 1001\nJOB NUMBER: 77\nDESCRIPTION: North Tower\n\n"
        "# Grounding and Bonding\n\n"
        "The grounding bus shall bond coax entry panels, surge protection devices, and tower steel.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("topic_admin.txt"), "txt", "Topic Admin", raw, clean)

    core_text = "\n\n".join(build_knowledge_core_pages([knowledge], target_words=500))
    assert "## SITE NUMBER" not in core_text
    assert "JOB NUMBER" not in core_text
    assert "DESCRIPTION: North Tower" not in core_text
    assert "Grounding and Bonding" in core_text or "Grounding" in core_text


def test_knowledge_core_fallback_does_not_reuse_admin_summary_text():
    raw = (
        "SITE NUMBER: 1001\n"
        "JOB NUMBER: 77\n"
        "PROJECT #: 55\n"
        "DESCRIPTION: North Tower\n"
        "LEGAL: Copyright notice\n"
        "The grounding bus shall bond coax entry panels, surge protection devices, and tower steel.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("fallback.txt"), "txt", "Latest", raw, clean)

    core_text = "\n\n".join(build_knowledge_core_pages([knowledge], target_words=500))
    assert "SITE NUMBER" not in core_text
    assert "JOB NUMBER" not in core_text
    assert "DESCRIPTION: North Tower" not in core_text
    assert "grounding bus shall bond" in core_text.lower()


def test_reference_facts_reject_admin_blob_lines():
    raw = (
        "Project No: 55, Sheet A1.01, Rev 3, Drawn By AB, Checked By CD, www.example.com\n"
        "The installer shall verify grounding continuity.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("facts_blob.txt"), "txt", "Facts Blob", raw, clean)

    facts_text = build_reference_facts([knowledge])
    assert "verify grounding continuity" in facts_text
    assert "Project No: 55" not in facts_text


def test_reference_facts_cluster_duplicate_note_style_facts_across_sources():
    raw = "Ground lug torque: 45 Nm.\n"
    item1 = build_source_knowledge(Path("a.txt"), "txt", "Doc A", raw, clean_text_for_knowledge(raw))
    item2 = build_source_knowledge(Path("b.txt"), "txt", "Doc B", raw, clean_text_for_knowledge(raw))

    facts_text = build_reference_facts([item1, item2])
    assert facts_text.count("Ground lug torque: 45 Nm.") == 1
    assert "[sources: a.txt, b.txt]" in facts_text or "[sources: b.txt, a.txt]" in facts_text


def test_reference_facts_reject_generic_note_style_admin_requirements():
    raw = (
        "Contractor shall coordinate with owner.\n"
        "Verify field conditions before installation.\n"
        "Ground lug torque: 45 Nm.\n"
    )
    clean = clean_text_for_knowledge(raw)
    knowledge = build_source_knowledge(Path("facts_notes.txt"), "txt", "Facts Notes", raw, clean)

    facts_text = build_reference_facts([knowledge])
    assert "coordinate with owner" not in facts_text
    assert "Verify field conditions" not in facts_text
    assert "45 Nm" in facts_text
