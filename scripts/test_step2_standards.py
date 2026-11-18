# -*- coding: utf-8 -*-
"""Adım 2 duman testi: utils/standards.py izole doğrulama."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from utils.standards import normalize_standard_code as n, extract_standard_refs as e, match_standard_fuzzy as mf

tests = [
    "DİN 16726", "TS EN 50122-1:2020+A1", "EN50126", "NFPA-13", "BS 476",
    "TS 500", "UIC 60", "EN 50126-1", "IEEE 1474", "EN IEC 62368-1",
    # Adım 2 düzeltme: ÇOK TİRELİ standartlar (önceden valid=False eleniyordu)
    "EN 61000-6-3", "IEC 60870-5-104:2006", "EN 50121-3-2", "IEC 60870-5",
]
for t in tests:
    r = n(t)
    print(f"{t:28s} -> canonical={r['canonical']!r:20s} family={r['family']!r:14s} ed={r['edition']!r:12s} valid={r['valid']}")
    assert r["valid"], f"GECERSIZ KALDI: {t}"

# Çok tireli zincirlerin beklentileri
assert n("EN 61000-6-3")["canonical"] == "EN 61000-6-3"
assert n("EN 61000-6-3")["family"] == "EN 61000"
assert n("IEC 60870-5-104:2006")["canonical"] == "IEC 60870-5-104"
assert n("IEC 60870-5-104:2006")["edition"] == "2006"
assert n("IEC 60870-5")["family"] == "IEC 60870"
print("ÇOK TİRELİ STANDART BEKLENTİLERİ SAGLANDI ✔")

print()
metin = ("Bu imalat EN 50122-1 ve TS EN 50122-2:2020+A1 uygun olacaktır. "
         "Poz 04.191 kapsamında NFPA-13 de (ayrıca EN50126) uygulanır; "
         "Madde 10 ve Sayfa 500 atıfları standart DEĞİLDİR.")
for r in e(metin):
    print("bulunan:", r["canonical"], "| ham:", r["raw"], "| span:", r["span"])

poz_var = any("Poz" in r["raw"] for r in e(metin))
madde_var = any("Madde" in r["raw"] for r in e(metin))
print()
print("Poz 04.191 yakalandı mı:", poz_var, "(False olmalı)")
print("Madde 10 yakalandı mı:", madde_var, "(False olmalı)")
print("fuzzy tam kod:", mf("EN 50122", ["EN 50122-1", "EN 50163", "NFPA 13"]))
print("fuzzy yazım bozuk:", mf("EN50122-1", ["EN 50122-1", "EN 50163"]))
