import re
from pathlib import Path

# ==============================================================================
# 1. Update 1_ingest.py
# ==============================================================================
ingest_path = Path(r"d:\mevzuatinceleme\1_ingest.py")
content = ingest_path.read_text(encoding="utf-8")
norm = content.replace("\r\n", "\n")

# Update split_markdown_into_legal_chunks definition and implementation
old_chunk_func_pattern = re.compile(
    r"def split_markdown_into_legal_chunks\(.*?\n\s+return chunks\n",
    re.DOTALL
)

new_chunk_func = '''def split_markdown_into_legal_chunks(
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
            for p in paragraphs:
                p_page = extract_page_number_from_text(p)
                if p_page is not None:
                    current_page = p_page

                if len(temp_chunk) + len(p) > max_chunk_size and len(temp_chunk) > 100:
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
                    temp_chunk = f"[{filename} - {current_title}{page_header_str}]\n" + p + "\n"
                else:
                    temp_chunk += p + "\n"

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

norm = old_chunk_func_pattern.sub(lambda m: new_chunk_func, norm, count=1)

# Pass rel_path to split_markdown_into_legal_chunks in 1_ingest loop
old_call = '''            chunks = split_markdown_into_legal_chunks(
                markdown_text=markdown_text,
                filename=filename,
                domain=domain,
                scope=scope,
                project_id=project_id,
                project_name=project_name
            )'''

new_call = '''            try:
                rel_path = file_path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
            except Exception:
                rel_path = filename

            chunks = split_markdown_into_legal_chunks(
                markdown_text=markdown_text,
                filename=filename,
                domain=domain,
                scope=scope,
                project_id=project_id,
                project_name=project_name,
                rel_path=rel_path
            )'''

assert old_call in norm, "old_call not found in 1_ingest.py!"
norm = norm.replace(old_call, new_call)

ingest_path.write_text(norm.replace("\n", "\r\n"), encoding="utf-8")
print("1_ingest.py updated with rel_path and document_id!")

# ==============================================================================
# 2. Update 2_agents_graph.py (Citation Verifier page label)
# ==============================================================================
ag_path = Path(r"d:\mevzuatinceleme\2_agents_graph.py")
ag_content = ag_path.read_text(encoding="utf-8")
ag_norm = ag_content.replace("\r\n", "\n")

old_vf_rows = '''        if matched_chunk:
            src = matched_chunk.get("source_file", "Bilinmeyen Belge")
            p_val = matched_chunk.get("page_num", 1)
            verification_rows.append(f"| `{clause_clean}` | <span style='color:green'>✔ DOĞRULANDI (Çekilen Madde)</span> | `{src}` (Sayfa {p_val}) |")
            verified_count += 1
            continue

        # Öncelik 2: Genel veritabanında var mı? (YALNIZCA ilgili proje veya global mevzuat taranır)
        found_in_db = None
        for doc, meta in zip(all_docs, all_metas):
            src = meta.get("source_file", "").lower()
            scope = meta.get("scope", "")
            meta_proj = meta.get("project_id", "")
            if current_project_id and scope != "global" and meta_proj != current_project_id:
                continue
            if law_filter and law_filter not in src:
                continue
            if clause_pat.search(doc) or clause_pat.search(meta.get("title", "")):
                found_in_db = meta
                break

        if found_in_db:
            src = found_in_db.get("source_file", "Veritabanı Dokümanı")
            p_val = found_in_db.get("page_num", 1)
            verification_rows.append(f"| `{clause_clean}` | <span style='color:blue'>✔ DOĞRULANDI (Veritabanında Mevcut)</span> | `{src}` (Sayfa {p_val}) |")
            verified_count += 1'''

new_vf_rows = '''        if matched_chunk:
            src = matched_chunk.get("source_file", "Bilinmeyen Belge")
            p_val = matched_chunk.get("page_num", 0)
            page_desc = f"Sayfa {p_val}" if p_val and p_val > 0 else "Fiziksel sayfa bilgisi yok (Dijital Belge)"
            verification_rows.append(f"| `{clause_clean}` | <span style='color:green'>✔ DOĞRULANDI (Çekilen Madde)</span> | `{src}` ({page_desc}) |")
            verified_count += 1
            continue

        # Öncelik 2: Genel veritabanında var mı? (YALNIZCA ilgili proje veya global mevzuat taranır)
        found_in_db = None
        for doc, meta in zip(all_docs, all_metas):
            src = meta.get("source_file", "").lower()
            scope = meta.get("scope", "")
            meta_proj = meta.get("project_id", "")
            if current_project_id and scope != "global" and meta_proj != current_project_id:
                continue
            if law_filter and law_filter not in src:
                continue
            if clause_pat.search(doc) or clause_pat.search(meta.get("title", "")):
                found_in_db = meta
                break

        if found_in_db:
            src = found_in_db.get("source_file", "Veritabanı Dokümanı")
            p_val = found_in_db.get("page_num", 0)
            page_desc = f"Sayfa {p_val}" if p_val and p_val > 0 else "Fiziksel sayfa bilgisi yok (Dijital Belge)"
            verification_rows.append(f"| `{clause_clean}` | <span style='color:blue'>✔ DOĞRULANDI (Veritabanında Mevcut)</span> | `{src}` ({page_desc}) |")
            verified_count += 1'''

assert old_vf_rows in ag_norm, "old_vf_rows not found in 2_agents_graph.py!"
ag_norm = ag_norm.replace(old_vf_rows, new_vf_rows)

ag_path.write_text(ag_norm.replace("\n", "\r\n"), encoding="utf-8")
print("2_agents_graph.py updated successfully with physical page distinction!")
