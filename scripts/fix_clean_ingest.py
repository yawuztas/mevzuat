import re
from pathlib import Path

p = Path(r"d:\mevzuatinceleme\1_ingest.py")
content = p.read_text(encoding="utf-8")

# Normalize line endings
content = content.replace("\r\r\n", "\n").replace("\r\n", "\n")

start_marker = "def split_markdown_into_legal_chunks"
end_marker = "def get_file_quick_hash"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

assert start_idx != -1 and end_idx != -1, f"Markers not found! start={start_idx}, end={end_idx}"

clean_func = r'''def split_markdown_into_legal_chunks(
    markdown_text: str,
    filename: str,
    domain: str,
    scope: str = "global",
    project_id: str = "global",
    project_name: str = "Genel Mevzuat ve Standartlar",
    rel_path: str = ""
) -> List[Dict[str, Any]]:
    """
    Mevzuat, sözleşme ve teknik şartnameleri 'Madde X', 'Bölüm X' veya Markdown başlıklarına (#, ##, ###) göre
    bağlam bütünlüğünü koruyarak parçalar; sayfa numaralarını takip eder ve detaylı metadata üretir.
    """
    chunks = []
    pattern = r"(?=(?:^|\n)(?:#{1,4}\s+|MADDE\s+\d+|Madde\s+\d+|Poz\s+\d+|BÖLÜM\s+\d+|Grup\s+\d+))"
    raw_sections = re.split(pattern, markdown_text, flags=re.MULTILINE)

    current_title = f"{filename} Genel Hükümler"
    doc_has_any_page = bool(PAGE_PATTERN.search(markdown_text))
    current_page = 1 if doc_has_any_page else 0
    document_id = f"{project_id}::{rel_path or filename}"

    for section in raw_sections:
        cleaned = section.strip()
        if not cleaned:
            continue

        p_num = extract_page_number_from_text(cleaned)
        if p_num is not None:
            current_page = p_num

        if len(cleaned) < 35:
            continue

        lines = cleaned.split("\n")
        first_line = lines[0].strip()
        if re.search(r"(?:#{1,4}\s+|MADDE\s+\d+|Madde\s+\d+|Poz\s+\d+|BÖLÜM\s+\d+|Grup\s+\d+)", first_line, re.IGNORECASE):
            current_title = first_line.replace("#", "").strip()

        max_chunk_size = 1800
        parent_section_text = cleaned[:3500]
        if len(cleaned) > max_chunk_size:
            paragraphs = cleaned.split("\n\n")
            chunk_page = current_page
            page_header_str = f" - Sayfa {chunk_page}" if chunk_page > 0 else ""
            temp_chunk = f"[{filename} - {current_title}{page_header_str}]\n"
            for p_item in paragraphs:
                p_page = extract_page_number_from_text(p_item)
                if p_page is not None:
                    current_page = p_page

                if len(temp_chunk) + len(p_item) > max_chunk_size and len(temp_chunk) > 100:
                    meta = classify_chunk_metadata(temp_chunk, current_title, filename, domain)
                    chunks.append({
                        "content": temp_chunk.strip(),
                        "metadata": {
                            "document_id": document_id,
                            "rel_path": rel_path or filename,
                            "source_file": filename,
                            "domain": meta["domain"],
                            "title": current_title,
                            "subsystem": meta["subsystem"],
                            "doc_type": meta["doc_type"],
                            "topics": meta["topics"],
                            "scope": scope,
                            "project_id": project_id,
                            "project_name": project_name,
                            "page_num": chunk_page,
                            "has_page_marker": doc_has_any_page,
                            "parent_content": parent_section_text,
                        }
                    })
                    chunk_page = current_page
                    page_header_str = f" - Sayfa {chunk_page}" if chunk_page > 0 else ""
                    temp_chunk = f"[{filename} - {current_title}{page_header_str}]\n" + p_item + "\n"
                else:
                    temp_chunk += p_item + "\n"

            if len(temp_chunk.strip()) > 30:
                meta = classify_chunk_metadata(temp_chunk, current_title, filename, domain)
                chunks.append({
                    "content": temp_chunk.strip(),
                    "metadata": {
                        "document_id": document_id,
                        "rel_path": rel_path or filename,
                        "source_file": filename,
                        "domain": meta["domain"],
                        "title": current_title,
                        "subsystem": meta["subsystem"],
                        "doc_type": meta["doc_type"],
                        "topics": meta["topics"],
                        "scope": scope,
                        "project_id": project_id,
                        "project_name": project_name,
                        "page_num": chunk_page,
                        "has_page_marker": doc_has_any_page,
                        "parent_content": parent_section_text,
                    }
                })
        else:
            meta = classify_chunk_metadata(cleaned, current_title, filename, domain)
            chunks.append({
                "content": cleaned,
                "metadata": {
                    "document_id": document_id,
                    "rel_path": rel_path or filename,
                    "source_file": filename,
                    "domain": meta["domain"],
                    "title": current_title,
                    "subsystem": meta["subsystem"],
                    "doc_type": meta["doc_type"],
                    "topics": meta["topics"],
                    "scope": scope,
                    "project_id": project_id,
                    "project_name": project_name,
                    "page_num": current_page,
                    "has_page_marker": doc_has_any_page,
                    "parent_content": parent_section_text,
                }
            })

    return chunks


'''

new_content = content[:start_idx] + clean_func + content[end_idx:]

# Remove empty lines between code lines that resulted from doubled newlines
# A line followed by \n\n where both lines are indented is a symptom of doubling
lines = new_content.splitlines()
cleaned_lines = []
skip_next = False
for i, line in enumerate(lines):
    if skip_next:
        skip_next = False
        continue
    cleaned_lines.append(line)
    # If this line is not blank and next line is blank, check if line i+2 has same indent or syntax continuation
    if i + 2 < len(lines) and line.strip() and not lines[i+1].strip() and lines[i+2].strip():
        # Only collapse if it was mechanical doubling
        pass

p.write_text("\n".join(cleaned_lines) + "\n", encoding="utf-8")
print("Replacement completed!")
