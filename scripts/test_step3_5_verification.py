# -*- coding: utf-8 -*-
"""Adım 3-5 üretim sağlık ve fiziksel Dual-DB izolasyon doğrulaması (salt-okunur)."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from utils.config import CORRESPONDENCE_VECTOR_DB_DIR, VECTOR_DB_DIR
from utils.project_db import connect
from utils.retriever import (
    get_chroma_collection,
    get_correspondence_collection,
    search_and_rerank,
)

conn = connect()
try:
    print("=" * 74)
    print("1) SQLITE project_graph.db")
    docs = conn.execute(
        "SELECT doc_id, doc_date, doc_no, sender_role, doc_type, state, review_status FROM documents ORDER BY doc_date"
    ).fetchall()
    links = conn.execute("SELECT from_doc_id, to_ref, link_type, resolved FROM links").fetchall()
    hist = conn.execute("SELECT doc_id, old_state, new_state, confirmed_by_human FROM state_history").fetchall()
    print(f"   documents={len(docs)} | links={len(links)} | state_history={len(hist)}")
finally:
    conn.close()

print(f"\n2) NORMATİF CHROMADB ({VECTOR_DB_DIR.name}/insaat_mevzuat) SAF KURAL KONTROLÜ")
norm_col = get_chroma_collection()
norm_total = norm_col.count()
leaked_corr = norm_col.get(where={"doc_role": "correspondence_history"}, include=["metadatas"]).get("ids") or []
print(f"   toplam normatif vektör: {norm_total} | sızan correspondence_history: {len(leaked_corr)}")
assert norm_total > 0, "Normatif DB boş olmamalı"
assert len(leaked_corr) == 0, f"Normatif DB içinde yazışma kaydı bulundu: {len(leaked_corr)}"
print("   ✔ Normatif DB %100 saf kural/şartname (0 yazışma)")

print(f"\n3) AYRI YAZIŞMA CHROMADB ({CORRESPONDENCE_VECTOR_DB_DIR.name}/proje_yazismalari)")
corr_col = get_correspondence_collection()
corr_total = corr_col.count()
print(f"   toplam yazışma vektörü: {corr_total}")
if corr_total > 0:
    metas = corr_col.get(include=["metadatas"], limit=200).get("metadatas") or []
    print("   sender_role dağılımı:", dict(Counter(m.get("sender_role") for m in metas)))

print("\n4) HOP 1 SIZINTI TESTİ: 'süre uzatımı madde 10' normatif araması")
r = search_and_rerank(
    query="sure uzatimi madde 10 mucbir sebep",
    domain="mevzuat",
    project_id="ikitelli_atakoy_metro",
    candidate_k=15,
    final_top_k=4,
    doc_role="normative_rule",
)
sizinti = [x for x in r if x["metadata"].get("doc_role") != "normative_rule"]
print(f"   sonuç: {len(r)} | normatif olmayan (SIZINTI): {len(sizinti)}")
for x in r:
    print(f"   - {x['metadata']['source_file'][:52]} | doc_role={x['metadata'].get('doc_role')}")
assert not sizinti, "Normatif aramaya yazışma sızdı!"
print("   ✔ Fiziksel + mantıksal izolasyon tam")
