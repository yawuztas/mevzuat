# -*- coding: utf-8 -*-
"""Adım 3-5 uçtan uca doğrulama: SQLite + ChromaDB + izolasyon."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import chromadb
from collections import Counter
from utils.project_db import connect

conn = connect()
print("=" * 74)
print("1) SQLITE documents")
rows = conn.execute("SELECT doc_id, doc_date, doc_no, sender_role, doc_type, state, review_status FROM documents ORDER BY doc_date").fetchall()
print(f"   toplam kart: {len(rows)}")
for r in rows:
    d = dict(r)
    print(f"   {d['doc_date']} | {str(d['doc_no']):16s} | {str(d['sender_role']):14s} | {str(d['doc_type']):18s} | {d['state']:6s}/{d['review_status']}")

print("\n2) SQLITE links (ilgi zinciri çözümlemesi)")
rows = conn.execute("SELECT from_doc_id, to_ref, link_type, resolved FROM links").fetchall()
cozulmus = sum(r["resolved"] for r in rows)
print(f"   toplam kenar: {len(rows)} | çözülmüş: {cozulmus} | bekleyen: {len(rows) - cozulmus}")
for r in rows[:15]:
    mark = "✔" if r["resolved"] else "…"
    print(f"   {mark} {r['from_doc_id'][-24:]} -> {str(r['to_ref'])[:24]} [{r['link_type']}]")

print("\n3) SQLITE state_history")
rows = conn.execute("SELECT doc_id, old_state, new_state, confirmed_by_human, triggered_by_doc_id FROM state_history").fetchall()
print(f"   geçiş sayısı: {len(rows)}")
for r in rows[:8]:
    print("   ", dict(r))

print("\n4) CHROMADB correspondence_history izolasyonu")
c = chromadb.PersistentClient(path="vector_db").get_or_create_collection("insaat_mevzuat")
print("   toplam:", c.count())
corr = c.get(where={"doc_role": "correspondence_history"}, include=["metadatas"], limit=200)
print("   correspondence_history chunk:", len(corr["metadatas"]))
roller = Counter(m.get("sender_role") for m in corr["metadatas"])
print("   sender_role dağılımı:", dict(roller))
tarihli = sum(1 for m in corr["metadatas"] if m.get("doc_date"))
print("   doc_date taşıyan:", tarihli)

print("\n5) HOP 1 SIZINTI TESTİ: 'süre uzatımı madde 10' normatif araması")
from utils.retriever import search_and_rerank
r = search_and_rerank(
    query="sure uzatimi madde 10 mucbir sebep",
    domain="mevzuat", project_id="ikitelli_atakoy_metro",
    candidate_k=15, final_top_k=4, doc_role="normative_rule",
)
sizinti = [x for x in r if x["metadata"].get("doc_role") != "normative_rule"]
print(f"   sonuç: {len(r)} | normatif olmayan (SIZINTI): {len(sizinti)}")
for x in r:
    print(f"   - {x['metadata']['source_file'][:52]} | doc_role={x['metadata'].get('doc_role')}")
if sizinti:
    print("   !! SIZINTI VAR")
else:
    print("   ✔ izolasyon tam")

# correspondence araması da çalışıyor mu (vaka hafızası yolu)
print("\n6) CORRESPONDENCE ARAMASI (gelecekteki case builder yolu)")
r2 = search_and_rerank(
    query="sure uzatimi talebi cevabi itiraz",
    project_id="ikitelli_atakoy_metro",
    candidate_k=15, final_top_k=4, doc_role="correspondence_history",
)
print(f"   sonuç: {len(r2)}")
for x in r2:
    m = x["metadata"]
    print(f"   - {m.get('doc_date')} | {str(m.get('doc_no')):14s} | {m['source_file'][:44]} | agırlık={m.get('evidence_weight')}")
