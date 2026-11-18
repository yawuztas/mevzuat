# -*- coding: utf-8 -*-
"""Adım 3 uçtan uca doğrulama:
1) 2. tur OCR-fuzzy İlgi zinciri çözümlemesi (5.23-401 -> S.23-401 -> YK-2023-4236)
2) state='Acik' varsayılanı ve mevcut durumun (Cevaplandi) yeniden upsert ile korunması
3) ChromaDB izolasyonu: doc_role='normative_rule' yazışmaları ASLA çekmez;
   doc_role='correspondence_history' yalnızca yazışmaları çeker.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from utils import project_db as pdb
from utils.retriever import search_and_rerank, get_chroma_collection

print("1) SQLITE İKİ TURLU ZİNCİR + STATE KONTROLÜ")
conn = pdb.connect()
try:
    docs = conn.execute(
        "SELECT doc_id, doc_no, state, review_status FROM documents WHERE project_id='ikitelli_atakoy_metro'"
    ).fetchall()
    assert len(docs) == 4, f"Beklenen 4 belge, bulunan {len(docs)}"
    assert all(d["state"] in pdb.VALID_STATES for d in docs), f"NULL/geçersiz state var: {[dict(d) for d in docs]}"

    d4289 = pdb.find_by_doc_no(conn, "ikitelli_atakoy_metro", "YK-2023-4289")
    assert d4289 is not None, "YK-2023-4289 bulunamadı"
    chain = pdb.iter_chain(conn, d4289["doc_id"])
    chain_nos = [c["doc_no"] for c in chain]
    print("   YK-2023-4289 zinciri:", chain_nos)
    assert chain_nos == ["S.23-401", "YK-2023-4236"], f"Zincir bozuk: {chain_nos}"

    # Mevcut state koruma testi (geçici test kartı üzerinde)
    pdb.upsert_document(conn, {"doc_id": "tmp_test::state", "project_id": "tmp_test", "state": "Acik"})
    pdb.update_state(conn, "tmp_test::state", "Cevaplandi", confirmed_by_human=True)
    pdb.upsert_document(conn, {"doc_id": "tmp_test::state", "project_id": "tmp_test"})
    st = pdb.get_document(conn, "tmp_test::state")["state"]
    assert st == "Cevaplandi", f"State ezildi: {st}"
    pdb.delete_document(conn, "tmp_test::state")
    conn.execute("DELETE FROM state_history WHERE doc_id='tmp_test::state'")
    conn.commit()
    print("   ✔ state koruması ve 2 turlu OCR-fuzzy zincir doğrulandı")
finally:
    conn.close()

print("\n2) CHROMADB DOC_ROLE İZOLASYONU")
col = get_chroma_collection()
corr = col.get(where={"doc_role": "correspondence_history"}, include=["metadatas"])
print("   correspondence_history chunk sayısı:", len(corr["ids"]))
assert len(corr["ids"]) >= 4, "Yazışma chunkları ChromaDB'de bulunamadı!"

# Özellikle HAKEDİŞ 112 ve YK-2023-4289 ifadelerini sorarak sızıntı testi
res_norm = search_and_rerank(
    query="HAKEDİŞ 112 12.450.000 TL 817 gün 5.23-401 AGA ENERJİ",
    domain="idari",
    project_id="ikitelli_atakoy_metro",
    candidate_k=15,
    final_top_k=4,
    doc_role="normative_rule",
)
leak = [x for x in res_norm if x.get("metadata", {}).get("doc_role") != "normative_rule"]
print("   normative_rule sorgu sonucu sayısı:", len(res_norm), "| sızan yazışma:", len(leak))
assert not leak, f"SIZINTI VAR: {leak}"

res_hist = search_and_rerank(
    query="210 gün süre uzatımı yer teslimi gecikmesi 120 gün cevap",
    domain="idari",
    project_id="ikitelli_atakoy_metro",
    candidate_k=10,
    final_top_k=3,
    doc_role="correspondence_history",
)
print("   correspondence_history sorgusu:", [(x["metadata"].get("doc_no"), x["metadata"].get("evidence_weight")) for x in res_hist])
assert len(res_hist) >= 1 and all(x["metadata"].get("doc_role") == "correspondence_history" for x in res_hist)
print("\nADIM 3 UÇTAN UCA TESTİ TAMAMEN GEÇTİ ✔")
