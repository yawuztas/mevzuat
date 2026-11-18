# -*- coding: utf-8 -*-
"""Adım 2 regresyon: eski çağrı biçimi bozulmadı mı + Hop 2 filtresi doğru mu?"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import importlib.util

_spec = importlib.util.spec_from_file_location("ingest_mod", "1_ingest.py")
ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest)

from utils.retriever import search_and_rerank

print("1) ESKI CAGRI BIÇIMI (yeni parametreler verilmeyince filtre uygulanmamali)")
r = search_and_rerank(
    query="asansor ve yuruyen merdiven teknik sartname gereksinimleri",
    domain="elektromekanik",
    subsystem="asansor_ve_yuruyen_merdiven",
    project_id="kirazli_halkali_metro",
    candidate_k=15, final_top_k=3,
)
print("   sonuç:", len(r), "| kaynaklar:", set(x["metadata"]["source_file"][:40] for x in r))

print("\n2) HOP 2: doc_role + doc_type_filter ile sadece standart norm havuzu")
r2 = search_and_rerank(
    query="EN 50122 topraklama ve stray current sinirlari cer gucu",
    domain="elektromekanik",
    project_id="ikitelli_atakoy_metro",
    candidate_k=10, final_top_k=2,
    doc_role="normative_rule",
    doc_type_filter=["standart_norm_katalogu"],
)
for x in r2:
    m = x["metadata"]
    print(f"   {m['source_file'][:52]:52s} | doc_type={m['doc_type']} | codes={m.get('standard_codes','')[:40]}")

print("\n3) 1_ingest classify entegrasyonu (standard_codes + doc_role üretimi)")
ornek = "Kablolar EN 50122-1 ve IEEE 1474 standardına uygun olmalıdır. Madde 10 uyarınca kabul edilir."
meta = ingest.classify_chunk_metadata(ornek, "Güç Temini - Genel", "02_Guc_Temini.md", "elektromekanik")
print("   standard_codes:", meta["standard_codes"])
print("   doc_role:", meta["doc_role"])
assert meta["standard_codes"] == "EN 50122-1|IEEE 1474", "beklenmedik kodlar!"
assert meta["doc_role"] == "normative_rule"
print("   ✔ entegrasyon dogru")

print("\n4) split_markdown_into_legal_chunks — TUM dallar alanları taşıyor mu?")
kisa = "Madde 1 - Genel: Işler EN 50122-1'e uygun yapılacaktır."
uzun = ("Madde 1 - Genel:\n" + ("İmalat EN 50122-1 ve IEC 60870-5-104 uygunluğunda yapılacaktır. " * 60)
        + "\n\nMadde 2 - Kablaj:\n" + ("Kablaj NFPA 130 hükümlerine göre test edilecektir. " * 60))
ch = ingest.split_markdown_into_legal_chunks(
    markdown_text=kisa + "\n\n" + uzun,
    filename="test_standart_bolumleri.md",
    domain="elektromekanik",
    scope="project",
    project_id="test_projesi",
    project_name="Test Projesi",
    rel_path="2_proje_evraklari/test_projesi/3_teknik_sartnameler/test_standart_bolumleri.md",
    procurement_type="yapim",
)
print("   üretilen chunk:", len(ch), "(kısa metin 1 + uzun metin bölünen >1 beklenir)")
eksik = []
for i, ch_i in enumerate(ch):
    if ch_i["metadata"].get("doc_role") != "normative_rule":
        eksik.append((i, "doc_role"))
    if "standard_codes" not in ch_i["metadata"]:
        eksik.append((i, "standard_codes"))
if eksik:
    print("   !! EKSIK ALANLAR:", eksik[:10])
    raise SystemExit("SPLIT DAGLARINDA EKSIK ALAN VAR!")
print("   ✔ tüm dallarda doc_role + standard_codes mevcut")
# Kod doğru yakalanıyor mu (EN 61000-6-3 gibi çok tireli dahil)
tumu = " ".join(c["metadata"].get("standard_codes", "") for c in ch)
assert "EN 50122-1" in tumu and "IEC 60870-5-104" in tumu and "NFPA 130" in tumu
print("   ✔ çok tireli IEC 60870-5-104 dahil kodlar chunk'lara işlendi")
