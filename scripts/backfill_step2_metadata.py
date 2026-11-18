# -*- coding: utf-8 -*-
"""
Adım 2 Backfill: Mevcut ChromaDB chunk'larına standard_codes + doc_role alanlarını
metadata güncellemesiyle ekler. Re-embedding YOK, re-parse YOK — metin zaten DB'de;
yalnızca metadata zenginleştirilir (Adım 2.2'nin verimli ve güvenli yolu).

Kullanım:
    python scripts/backfill_step2_metadata.py          # asıl çalıştırma
    python scripts/backfill_step2_metadata.py --dry    # hesapla, yazma yapma
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collections import Counter

import chromadb

from utils.standards import extract_standard_refs

DRY = "--dry" in sys.argv
BATCH = 200

client = chromadb.PersistentClient(path="vector_db")
col = client.get_or_create_collection("insaat_mevzuat")
total = col.count()
print(f"Koleksiyon: {total} chunk | Mod: {'DRY (yazma yok)' if DRY else 'GERÇEK YAZMA'}")

offset = 0
updated = 0
with_codes = 0
empty_codes = 0
top_codes = Counter()
pending_ids, pending_metas = [], []


def flush():
    global pending_ids, pending_metas, updated
    if not pending_ids or DRY:
        pending_ids, pending_metas = [], []
        return
    col.update(ids=pending_ids, metadatas=pending_metas)
    updated += len(pending_ids)
    pending_ids, pending_metas = [], []


while offset < total:
    res = col.get(include=["documents", "metadatas"], limit=BATCH, offset=offset)
    docs = res.get("documents", [])
    metas = res.get("metadatas", [])
    ids = res.get("ids", [])
    if not docs:
        break
    for doc_id, doc, meta in zip(ids, docs, metas):
        refs = extract_standard_refs((doc or "") + " " + (meta.get("title") or ""))
        codes = "|".join(r["canonical"] for r in refs)
        if codes:
            with_codes += 1
            for c in codes.split("|"):
                top_codes[c] += 1
        else:
            empty_codes += 1
        new_meta = dict(meta)
        new_meta["standard_codes"] = codes
        new_meta["doc_role"] = meta.get("doc_role") or "normative_rule"
        # Adım 2 düzeltme: 4_standart_normlar havuzundaki ORİJİNAL standart
        # belgeleri dosya adından bağımsız olarak standart_norm_katalogu sayılır.
        rel_l = (meta.get("rel_path") or "").lower()
        if "4_standart_normlar" in rel_l or "standart_normlar" in rel_l:
            new_meta["doc_type"] = "standart_norm_katalogu"
        pending_ids.append(doc_id)
        pending_metas.append(new_meta)
        if len(pending_ids) >= BATCH:
            flush()
    offset += len(docs)
    print(f"  işlendi: {offset}/{total}", end="\r")

flush()
print()
print(f"Güncellenen chunk: {updated} | standard_codes dolu: {with_codes} | boş: {empty_codes}")
print("En sık 15 kanonik kod:")
for code, cnt in top_codes.most_common(15):
    print(f"  {code:24s} {cnt:5d} chunk")
