# -*- coding: utf-8 -*-
"""Adım 3 LLM duman testi: GERÇEK İkitelli yazısı + use_llm=True (canlı API)."""
import sys
import hashlib
import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import docx

from utils.card_extractor import extract_identity_card, parse_tr_date

# 1) Gerçek belgeyi seç (süre uzatımı bilgi notu öncelikli, recursive arama)
tahkim = Path("_arsiv/TAHKİM")
kandidatlar = sorted(tahkim.rglob("*.docx"))
öncelik = [k for k in kandidatlar if "bilgi notu" in k.name.lower()]
secilen = (öncelik or kandidatlar)[0] if kandidatlar else None
print("Aday docx sayısı:", len(kandidatlar))
print("Gerçek belge:", secilen)

doc = docx.Document(secilen)
paragraflar = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
md_text = "\n".join(paragraflar)
print(f"Metin uzunluğu: {len(md_text)} karakter | ilk 200: {md_text[:200]!r}")
print()

# 2) use_llm=True ile Kimlik Kartı
sha = hashlib.sha256(md_text.encode("utf-8")).hexdigest()
sonuc = extract_identity_card(
    md_text,
    filename=Path(secilen).name,
    rel_path=f"_arsiv/TAHKİM/{Path(secilen).name}",
    doc_sha256=sha,
    project_id="ikitelli_atakoy_metro",
    doc_type="yuklenici_yazisi",
    sender_role_hint=None,   # bilinçli None: rol tespiti da sınanacak
    use_llm=True,
)
card = sonuc["card"]
print("=" * 70)
print("KİMLİK KARTI (use_llm=True):")
for k in ("doc_date", "doc_no", "sender_role", "evidence_weight", "review_status",
          "extraction_confidence", "subject"):
    print(f"   {k:22s}: {str(card.get(k))[:80]}")
print(f"   summary             : {str(card.get('summary'))[:100]}")
print(f"   konu_etiketleri     : {card.get('konu_etiketleri')}")
print(f"   ilgi_refs           : {sonuc['ilgi_refs']}")
print(f"   llm_errors          : {sonuc['llm_errors']}")
enr = sonuc.get("enrichment")
if enr:
    print("   ENRICHMENT (instructor):")
    print(f"      talep_ozeti      : {str(enr.get('talep_ozeti'))[:120]}")
    print(f"      hukuki_dayanaklar: {enr.get('hukuki_dayanaklar')}")
spans = sonuc["spans"]
llm_spans = [s for s in spans if s["field"] in ("standart_atifi", "poz_atifi", "iddia")]
print(f"   LLM SPAN'LERI ({len(llm_spans)}):")
for s in llm_spans[:8]:
    print(f"      [{s['field']}] {s['char_start']}-{s['char_end']} -> {md_text[s['char_start']:s['char_end']][:60]!r}")

print()
# 3) Yıl sızıntısı sertleştirme kontrolü (sentezik)
test_ilgi = "İlgi: 2 Nisan 2023 tarihli ve 4236 sayılı yazınız."
r = extract_identity_card(
    "Sayı: S.23-100\nTarih: 2 Nisan 2023\n" + test_ilgi + "\n\nMetin.",
    filename="2023-04-02_yazı.md", project_id="t", doc_type="yuklenici_yazisi", use_llm=False,
)
print("YIL SIZINTISI kontrolü — ilgi_refs:", r["ilgi_refs"])
yil_var = any(x == "2023" for x in r["ilgi_refs"])
print("   '2023' çıplak yıl sızdı mı:", yil_var, "(False olmalı)")
print("   '4236' yakalandı mı:", "4236" in r["ilgi_refs"], "(True olmalı)")
