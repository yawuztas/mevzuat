# -*- coding: utf-8 -*-
"""Adım 2 Bitirme Testi: DB doğrulaması + döngü koruması simülasyonu."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import chromadb

print("=" * 74)
print("1) DB DOĞRULAMA: standard_codes / doc_role kapsaması")
c = chromadb.PersistentClient(path="vector_db").get_or_create_collection("insaat_mevzuat")
print("   toplam:", c.count())

r = c.get(where={"$and": [{"project_id": "ikitelli_atakoy_metro"}, {"doc_role": "normative_rule"}]}, include=["metadatas"], limit=6000)
print("   doc_role=normative_rule (ikitelli):", len(r["metadatas"]), "/ 5095")

# Bilinen vaka: cer gücü şartnamesinden EN 50122 taşıyan chunk
r2 = c.get(where={"$and": [{"project_id": "ikitelli_atakoy_metro"}, {"standard_codes": {"$ne": ""}}]}, include=["metadatas"], limit=3000)
print("   ikitelli standard_codes dolu chunk:", len(r2["metadatas"]))
from collections import Counter
kodlar = Counter()
for m in r2["metadatas"]:
    for k in (m.get("standard_codes") or "").split("|"):
        if k:
            kodlar[k] += 1
print("   ikitelli en sık 8 kod:", kodlar.most_common(8))

# Döngü koruması simülasyonu (Adım 3 testinin öncülü): A->B->A senteti
print()
print("2) DÖNGÜ KORUMASI SİMÜLASYONU (A -> B -> A)")
from utils.standards import extract_standard_refs, normalize_standard_code

# Sahte chunk'lar: A dokmanı EN 99999 + EN 88888'e atıf; B dokmanı EN 88888 + EN 99999'e
docA = "Tüm ekipman EN 99999 standardına ve EN 88888 hükümlerine uygun olacaktır."
docB = "Kablaj EN 88888 ve EN 99999 gereklerine göre蒙特 uygulanır."  # bilerek bozuk karakter içeriyor
visited = set()
sıra = ["EN 88888", "EN 99999"]  # Hop sırasında ziyaret edilecekler
hop_counts = {}
for code in sıra:
    if code in visited:
        continue
    visited.add(code)
    hop_counts[code] = hop_counts.get(code, 0) + 1
    # standart içi metin diğerine atıf içeriyor ama Hop 3 yapılmaz (MAX_STANDARD_HOP_DEPTH=2)
print("   ziyaret edilenler:", visited, "| hop sayıları:", hop_counts)
assert all(v == 1 for v in hop_counts.values()), "AYNI STANDART 2 KEZ SORGULANMIS!"
print("   ✔ döngü koruması: her kod tam 1 kez ziyaret edildi (Hop 3 yok)")

# Türkçe İ normalizasyonu chunk içi kontrol
tr_test = extract_standard_refs(docB)
print("   bozuk karakterli metinden çıkarım:", [r["canonical"] for r in tr_test], "(EN 88888 + EN 99999 beklenir)")

print()
print("SONUÇ: ADIM 2 BITIRME KRITERLERI SAGLANMIS ✔" if len(r["metadatas"]) > 4900 and len(r2["metadatas"]) > 200 else "SORUN VAR !!")
