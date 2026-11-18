# -*- coding: utf-8 -*-
"""
Proje-Bağımsız (Global) Katman 2 Etiketleme ve Parçalama Genelleme Testleri
---------------------------------------------------------------------------
Hiçbir yeni proje dosya adı ezberlemeden (Cilt_3_Ek_B.md, Dokuman_Z.md gibi)
doğru domain/subsystem çıkarımı, tarafsız fallback ve tek-\n bölme doğrulanır.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

spec = importlib.util.spec_from_file_location("ingest_mod", BASE_DIR / "1_ingest.py")
ingest = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(ingest)


def test_unseen_filename_in_teknik_sartnameler_and_dominant_subsystem() -> None:
    fake_path = BASE_DIR / "data/2_proje_evraklari/yeni_tramvay_hatti/3_teknik_sartnameler/Cilt_3_Ek_B.md"
    dom = ingest.detect_domain_from_path(fake_path)
    fsub = ingest.detect_folder_subsystem(fake_path)
    assert dom == "karma", f"3_teknik_sartnameler altındaki nötr adlı dosya 'karma' olmalı, gelen: {dom}"
    assert fsub is None, f"Rastgele dosya adında fsub None olmalı, gelen: {fsub}"

    md = (
        "## BÖLÜM 1 GENEL AMAÇ\n\n"
        "Bu doküman yeni tramvay hattı kapsamında tesis edilecek ekipmanların genel çerçevesini, "
        "teslim esaslarını ve kalite güvence belgelerini özetlemektedir.\n\n"
        "## BÖLÜM 2 DUMAN TAHLİYE VE HİDRANT\n\n"
        "Tüm istasyon ve yeraltı geçitlerinde F300 sınıfı jet fan ve şaft fan üniteleri kullanılacaktır. "
        "Duman tahliye damperleri NFPA 130 ve EN 12101 uyumlu olup sprinkler ve hidrant hatları "
        "hidrofor ve yangın pompası üzerinden beslenecektir. Borulama ve drenaj sistemleri vana testine tabidir."
    )
    chunks = ingest.split_markdown_into_legal_chunks(
        markdown_text=md,
        filename="Cilt_3_Ek_B.md",
        domain=dom,
        scope="project",
        project_id="yeni_tramvay_hatti",
        rel_path="2_proje_evraklari/yeni_tramvay_hatti/3_teknik_sartnameler/Cilt_3_Ek_B.md",
        procurement_type="yapim",
        folder_subsystem=fsub,
    )
    assert len(chunks) >= 2
    for ch in chunks:
        sub = ch["metadata"]["subsystem"]
        assert sub == "havalandirma_ve_yangin_tvs", f"Beklenen havalandirma_ve_yangin_tvs, gelen: {sub}"
        assert ch["metadata"]["domain"] == "elektromekanik"
    print("[OK] Test 1: Rastgele adlı yeni proje belgesinde giriş parçası dahil tüm parçalar doğru disiplini aldı.")


def test_neutral_fallback_never_defaults_to_sinyalizasyon() -> None:
    md = (
        "## BÖLÜM 1 GENEL HÜKÜMLER\n\n"
        "Ekipmanların boya kalınlığı, ambalajlanması, şantiyeye nakliyesi ve saha depolama koşulları "
        "idarenin onaylayacağı genel elektromekanik usuller çerçevesinde yürütülür."
    )
    chunks = ingest.split_markdown_into_legal_chunks(
        markdown_text=md,
        filename="Ek_99_Elektromekanik_Ambalaj.md",
        domain="elektromekanik",
        scope="project",
        project_id="yeni_tramvay_hatti",
        rel_path="2_proje_evraklari/yeni_tramvay_hatti/3_teknik_sartnameler/Ek_99_Elektromekanik_Ambalaj.md",
        procurement_type="yapim",
        folder_subsystem=None,
    )
    assert len(chunks) == 1
    assert chunks[0]["metadata"]["subsystem"] == "genel_elektromekanik", chunks[0]["metadata"]["subsystem"]
    print("[OK] Test 2: Eşleşmeyen elektromekanik parça sinyalizasyon_cbtc yerine 'genel_elektromekanik' aldı.")


def test_multidiscipline_karma_document_keeps_per_section_routing() -> None:
    md = (
        "## BÖLÜM 1 TÜNEL İMALATLARI\n\n"
        "TBM ve NATM tünel kazılarında segment, püskürtme beton ve kaya bulon uygulaması yapılacaktır.\n\n"
        "## BÖLÜM 2 TREN KONTROL\n\n"
        "CBTC tabanlı sinyalizasyon sistemi SIL 4 düzeyinde EN 50128 ve EN 50129 uyumlu olacak, baliz ve anklaşman içerecektir.\n\n"
        "## BÖLÜM 3 ELEKTRİFİKASYON\n\n"
        "1500V DC cer gücü sistemi EN 50122 ve EN 50163 standartlarına göre kaçak akım ve topraklama korumalı kurulacaktır."
    )
    chunks = ingest.split_markdown_into_legal_chunks(
        markdown_text=md,
        filename="Ortak_Cilt_1.md",
        domain="karma",
        scope="project",
        project_id="yeni_tramvay_hatti",
        rel_path="2_proje_evraklari/yeni_tramvay_hatti/3_teknik_sartnameler/Ortak_Cilt_1.md",
        procurement_type="yapim",
        folder_subsystem=None,
    )
    subs = [c["metadata"]["subsystem"] for c in chunks]
    assert subs == ["tunel_ve_kazilar", "sinyalizasyon_cbtc", "cer_gucu_ve_elektrifikasyon"], f"Gelen: {subs}"
    print("[OK] Test 3: Çok disiplinli karma belge bölüm bazlı doğru ayrıştırıldı:", subs)


def test_single_newline_large_spec_splits_cleanly() -> None:
    sample_path = BASE_DIR / "data/2_proje_evraklari/ikitelli_atakoy_musavirlik/3_teknik_sartnameler/2015-78345_1_Teknik_Sartname.md"
    txt = sample_path.read_text(encoding="utf-8")
    chunks = ingest.split_markdown_into_legal_chunks(
        markdown_text=txt,
        filename=sample_path.name,
        domain="idari",
        scope="project",
        project_id="ikitelli_atakoy_musavirlik",
        rel_path="2_proje_evraklari/ikitelli_atakoy_musavirlik/3_teknik_sartnameler/2015-78345_1_Teknik_Sartname.md",
        procurement_type="danismanlik",
    )
    assert len(chunks) >= 20, f"44.885 krk metin >=20 parçaya bölünmeliydi, gelen: {len(chunks)}"
    max_len = max(len(c["content"]) for c in chunks)
    assert max_len <= 2200, f"En büyük parça çok uzun: {max_len}"
    print(f"[OK] Test 4: Tek satır sonlu 44.885 krk Müşavirlik Teknik Şartnamesi {len(chunks)} temiz parçaya bölündü (maks {max_len} krk).")


if __name__ == "__main__":
    test_unseen_filename_in_teknik_sartnameler_and_dominant_subsystem()
    test_neutral_fallback_never_defaults_to_sinyalizasyon()
    test_multidiscipline_karma_document_keeps_per_section_routing()
    test_single_newline_large_spec_splits_cleanly()
    print("TÜM GLOBAL GENELLEME TESTLERİ BAŞARIYLA GEÇTİ ✔")
