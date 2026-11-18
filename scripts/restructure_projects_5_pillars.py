import json
import re
import shutil
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from utils.config import DATA_DIR, PROJE_EVRAKLARI_DIR, VECTOR_DB_DIR
from utils.document_parser import extract_page_with_tables, parse_any_document
from utils.retriever import get_chroma_collection
from importlib import import_module

ingest_mod = import_module("1_ingest")
get_file_quick_hash = ingest_mod.get_file_quick_hash
MANIFEST_FILE = VECTOR_DB_DIR / "ingested_manifest.json"


def ensure_5_pillars(proj_dir: Path):
    pillars = [
        "1_sozlesme",
        "2_idari_sartname",
        "3_teknik_sartnameler",
        "4_birim_fiyat_ve_cetveller",
        "5_zeyilnameler_ve_soru_cevaplar",
    ]
    for p in pillars:
        (proj_dir / p).mkdir(parents=True, exist_ok=True)


def split_cilt1_markdown(md_path: Path, proj_dir: Path):
    """
    ikitelli_atakoy_sozlesme_ve_birim_fiyat.md (318 sayfa) dosyasını
    sayfa numaralarına göre 4 ana sütuna ayırır:
    - Sayfa 1-65   -> 1_sozlesme/01_Ikitelli_Atakoy_Imzali_Sozlesme_Sayfa_1_65.md
    - Sayfa 66-157 -> 2_idari_sartname/01_Ikitelli_Atakoy_Idari_Sartname_Sayfa_66_157.md
    - Sayfa 158-201-> 5_zeyilnameler_ve_soru_cevaplar/01_Ikitelli_Atakoy_Zeyilnameler_ve_Aciklamalar_Sayfa_158_201.md
    - Sayfa 202-318-> 4_birim_fiyat_ve_cetveller/01_Ikitelli_Atakoy_Birim_Fiyat_Tarifleri_ve_Cetveli_Sayfa_202_318.md
    """
    text = md_path.read_text(encoding="utf-8")
    parts = re.split(r"(?=## --- Sayfa \d+)", text)

    buckets = {
        "sozlesme": [
            "# İKİTELLİ-ATAKÖY METRO HATTI İNŞAAT VE ELEKTROMEKANİK İŞLERİ - İMZALI SÖZLEŞME METNİ (Sayfa 1 - 65)\n"
            "> Kaynak: 1. Cilt (Noter Onaylı İmzalı Sözleşme, Zeyilname İle Değiştirilen Maddeler Dahil)\n"
        ],
        "idari": [
            "# İKİTELLİ-ATAKÖY METRO HATTI İNŞAAT VE ELEKTROMEKANİK İŞLERİ - İDARİ ŞARTNAME (Sayfa 66 - 157)\n"
            "> Kaynak: 1. Cilt (İhale İdari Şartnamesi - İKN: 2015/74736)\n"
        ],
        "zeyilname": [
            "# İKİTELLİ-ATAKÖY METRO HATTI - ZEYİLNAMELER VE İHALE SORU-CEVAP AÇIKLAMALARI (Sayfa 158 - 201)\n"
            "> Kaynak: 1. Cilt (Zeyilname-1, Zeyilname-2 ve İsteklilerin Sorularına İdarenin Verdiği Bağlayıcı Yanıtlar)\n"
        ],
        "birim_fiyat": [
            "# İKİTELLİ-ATAKÖY METRO HATTI - BİRİM FİYAT TARİFLERİ, ANALİZ FORMATI VE TEKLİF CETVELİ (Sayfa 202 - 318)\n"
            "> Kaynak: 1. Cilt (Birim Fiyat Tarifleri s.204, Örnek Fiyat Analizi s.293, Birim Fiyat Teklif Cetveli s.298)\n"
        ],
    }

    for part in parts:
        m = re.match(r"## --- Sayfa (\d+)", part.strip())
        if not m:
            continue
        pno = int(m.group(1))
        if 1 <= pno <= 65:
            buckets["sozlesme"].append(part.strip())
        elif 66 <= pno <= 157:
            buckets["idari"].append(part.strip())
        elif 158 <= pno <= 201:
            buckets["zeyilname"].append(part.strip())
        elif pno >= 202:
            buckets["birim_fiyat"].append(part.strip())

    out_files = {
        "sozlesme": proj_dir / "1_sozlesme" / "01_Ikitelli_Atakoy_Imzali_Sozlesme_Sayfa_1_65.md",
        "idari": proj_dir / "2_idari_sartname" / "01_Ikitelli_Atakoy_Idari_Sartname_Sayfa_66_157.md",
        "zeyilname": proj_dir / "5_zeyilnameler_ve_soru_cevaplar" / "01_Ikitelli_Atakoy_Zeyilnameler_ve_Aciklamalar_Sayfa_158_201.md",
        "birim_fiyat": proj_dir / "4_birim_fiyat_ve_cetveller" / "01_Ikitelli_Atakoy_Birim_Fiyat_Tarifleri_ve_Cetveli_Sayfa_202_318.md",
    }

    for k, out_path in out_files.items():
        content = "\n\n".join(buckets[k]) + "\n"
        out_path.write_text(content, encoding="utf-8")
        print(f"  [OK] {out_path.name} ({len(content):,} karakter)")


def extract_digital_contract_draft(doc_path: Path, proj_dir: Path):
    """2015-74736_sozlesme_tasarisi.doc dosyasını temiz Markdown olarak 1_sozlesme altına yazar."""
    text = parse_any_document(doc_path)
    header = (
        "# İKİTELLİ-ATAKÖY METRO HATTI - EKAP DİJİTAL SÖZLEŞME TASARISI (İKN: 2015/74736)\n"
        "> Kaynak: 2015-74736_sozlesme_tasarisi.doc (%100 Dijital EKAP Metni - Madde 1..37)\n\n"
    )
    out_path = proj_dir / "1_sozlesme" / "02_Ikitelli_Atakoy_EKAP_Dijital_Sozlesme_Tasarisi.md"
    out_path.write_text(header + text + "\n", encoding="utf-8")
    print(f"  [OK] {out_path.name} ({len(text):,} karakter)")


def extract_digital_teknik_sartname_chapters(pdf_path: Path, proj_dir: Path):
    """
    660 sayfalık %100 dijital '2015-74736_Teknik Şartname.pdf' dosyasını
    orijinal sayfa numaralarını (## --- Sayfa X ---) ve tabloları koruyarak
    10 ana mühendislik disiplini dosyasına ayırır.
    """
    chapters = [
        ("00_Ortak_Teknik_Kosullar_Sayfa_1_51.md", 1, 51, "BÖLÜM 00: ORTAK TEKNİK KOŞULLAR VE GENEL GEREKSİNİMLER (Sayfa 1 - 51)"),
        ("01_Kaba_ve_Ince_Insaat_Isleri_Sayfa_52_221.md", 52, 221, "BÖLÜM 01: İNŞAAT İŞLERİ - KABA VE İNCE İNŞAAT, TÜNEL, İSTASYON VE GEOTEKNİK (Sayfa 52 - 221)"),
        ("02_Guc_Temini_ve_Cer_Gucu_Sistemi_Sayfa_222_299.md", 222, 299, "BÖLÜM 02: GÜÇ TEMİNİ VE CER GÜCÜ / ELEKTRİFİKASYON SİSTEMİ (Sayfa 222 - 299)"),
        ("03_Sinyalizasyon_Sistemi_Sayfa_300_338.md", 300, 338, "BÖLÜM 03: SİNYALİZASYON VE TREN KONTROL (CBTC / GoA4) SİSTEMİ (Sayfa 300 - 338)"),
        ("04_Haberlesme_ve_Kontrol_Sistemleri_SCADA_Sayfa_339_431.md", 339, 431, "BÖLÜM 04: HABERLEŞME, ZAYIF AKIM VE SCADA KONTROL SİSTEMLERİ (Sayfa 339 - 431)"),
        ("05_Cevresel_Kontrol_ve_Havalandirma_TVS_Sayfa_432_478.md", 432, 478, "BÖLÜM 05: ÇEVRESEL KONTROL VE TÜNEL HAVALANDIRMA SİSTEMİ - TVS (Sayfa 432 - 478)"),
        ("06_Yardimci_Tesisler_ve_Yangin_Sondurme_Sayfa_479_577.md", 479, 577, "BÖLÜM 06: YARDIMCI TESİSLER, MEKANİK TESİSAT VE YANGIN SÖNDÜRME SİSTEMLERİ (Sayfa 479 - 577)"),
        ("07_Yuruyen_Merdiven_ve_Asansorler_Sayfa_578_606.md", 578, 606, "BÖLÜM 07: DÜŞEY TAŞIMA SİSTEMLERİ - YÜRÜYEN MERDİVENLER VE ASANSÖRLER (Sayfa 578 - 606)"),
        ("08_Demiryolu_Ustyapi_ve_Ray_Isleri_Sayfa_607_642.md", 607, 642, "BÖLÜM 08: DEMİRYOLU ÜSTYAPI, RAY VE MAKAS İŞLERİ (Sayfa 607 - 642)"),
        ("09_Yeterlilik_Test_ve_Denetim_RAMS_Sayfa_643_660.md", 643, 660, "BÖLÜM 09: YETERLİLİK, TEST, DENETİM VE SİSTEM MÜHENDİSLİĞİ / RAMS (Sayfa 643 - 660)"),
    ]

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    print(f"  [PDF] {pdf_path.name} açıldı ({total_pages} sayfa)")

    out_dir = proj_dir / "3_teknik_sartnameler"
    out_dir.mkdir(parents=True, exist_ok=True)

    for fname, start_p, end_p, title in chapters:
        lines = [
            f"# İKİTELLİ-ATAKÖY METROSU TEKNİK ŞARTNAMESİ - {title}\n"
            f"> Kaynak: 2015-74736_Teknik Şartname.pdf (%100 Orijinal Dijital İhale Dokümanı, Sayfa {start_p} - {end_p})\n"
        ]
        for pno in range(start_p, min(end_p, total_pages) + 1):
            page = doc[pno - 1]
            page_text = extract_page_with_tables(page)
            lines.append(f"## --- Sayfa {pno} (Dijital Metin & Tablo) ---\n{page_text.strip()}")
        content = "\n\n".join(lines) + "\n"
        out_path = out_dir / fname
        out_path.write_text(content, encoding="utf-8")
        print(f"  [OK] {fname} (Sayfa {start_p}-{end_p}, {len(content):,} karakter)")

    doc.close()


def migrate_file_and_update_db(
    project_id: str,
    old_path: Path,
    new_path: Path,
    new_doc_type: str,
    manifest: dict,
    collection,
):
    """
    Dosyayı yeni klasörüne taşır, manifest ve ChromaDB içindeki document_id, rel_path ve doc_type
    alanlarını yerinde (in-place) günceller. Böylece değişmeyen dosyalar tekrar OCR/embedding'e girmez.
    """
    if not old_path.exists():
        return False

    old_rel = old_path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    old_key = f"{project_id}::{old_rel}"

    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_path), str(new_path))

    new_rel = new_path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    new_key = f"{project_id}::{new_rel}"

    # ChromaDB güncelle
    res = collection.get(where={"document_id": old_key}, include=["metadatas"])
    if res and res["ids"]:
        new_metas = []
        for m in res["metadatas"]:
            m_copy = dict(m)
            m_copy["document_id"] = new_key
            m_copy["rel_path"] = new_rel
            if new_doc_type:
                m_copy["doc_type"] = new_doc_type
            new_metas.append(m_copy)
        collection.update(ids=res["ids"], metadatas=new_metas)

    # Manifest güncelle
    if old_key in manifest:
        entry = manifest.pop(old_key)
        entry["rel_path"] = new_rel
        entry["hash"] = get_file_quick_hash(new_path)
        manifest[new_key] = entry

    return True


def main():
    manifest = {}
    if MANIFEST_FILE.exists():
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    collection = get_chroma_collection()

    # =========================================================================
    # 1. İKİTELLİ - ATAKÖY METROSU
    # =========================================================================
    print("\n=== 1. İKİTELLİ-ATAKÖY METROSU 5 SÜTUNLU MİMARİYE GEÇİRİLİYOR ===")
    ia_dir = PROJE_EVRAKLARI_DIR / "ikitelli_atakoy_metro"
    ensure_5_pillars(ia_dir)

    old_cilt1_md = ia_dir / "1_sozlesme_ve_idari" / "ikitelli_atakoy_sozlesme_ve_birim_fiyat.md"
    old_ts1_md = ia_dir / "2_teknik_sartnameler" / "TAM_TEKNIK_SARTNAME_KISIM_1_Sayfa_1_330.md"
    old_ts2_md = ia_dir / "2_teknik_sartnameler" / "TAM_TEKNIK_SARTNAME_KISIM_2_Sayfa_331_660.md"

    # 1.a Cilt 1'i 4 sütuna ayır (Sözleşme, İdari Şartname, Zeyilname, Birim Fiyat)
    if old_cilt1_md.exists():
        split_cilt1_markdown(old_cilt1_md, ia_dir)

    # 1.b EKAP Dijital Sözleşme Tasarısını (.doc) çıkar
    doc_draft = ia_dir / "ham_dosyalar" / "2015-74736_sozlesme_tasarisi.doc"
    if doc_draft.exists():
        extract_digital_contract_draft(doc_draft, ia_dir)

    # 1.c %100 Dijital Teknik Şartname PDF'ini 10 disiplin bölümüne ayır
    digital_ts_pdf = ia_dir / "ham_dosyalar" / "2015-74736_Teknik Şartname.pdf"
    if digital_ts_pdf.exists():
        extract_digital_teknik_sartname_chapters(digital_ts_pdf, ia_dir)

    # 1.d Eski 3 OCR dosyasını _arsiv/eski_ocr_surumleri/ klasörüne taşı (Silinmez!)
    arsiv_dir = ia_dir / "_arsiv" / "eski_ocr_surumleri"
    arsiv_dir.mkdir(parents=True, exist_ok=True)
    for old_f in [old_cilt1_md, old_ts1_md, old_ts2_md]:
        if old_f.exists():
            dest = arsiv_dir / old_f.name
            shutil.move(str(old_f), str(dest))
            print(f"  [ARŞİV] {old_f.name} -> _arsiv/eski_ocr_surumleri/{old_f.name}")

    # Boşalan eski klasörleri temizle
    for empty_cand in [ia_dir / "1_sozlesme_ve_idari", ia_dir / "2_teknik_sartnameler"]:
        if empty_cand.exists() and not any(empty_cand.iterdir()):
            empty_cand.rmdir()

    # 1.e 3_sinyalizasyon klasörünü 3_teknik_sartnameler/sinyalizasyon_test_prosedurleri altına taşı (DB koruyarak)
    old_sig_dir = ia_dir / "3_sinyalizasyon"
    new_sig_dir = ia_dir / "3_teknik_sartnameler" / "sinyalizasyon_test_prosedurleri"
    if old_sig_dir.exists():
        moved_sig = 0
        for fp in list(old_sig_dir.rglob("*")):
            if fp.is_file():
                rel_sub = fp.relative_to(old_sig_dir)
                target_fp = new_sig_dir / rel_sub
                if migrate_file_and_update_db(
                    "ikitelli_atakoy_metro",
                    fp,
                    target_fp,
                    "teknik_sartname",
                    manifest,
                    collection,
                ):
                    moved_sig += 1
        shutil.rmtree(old_sig_dir, ignore_errors=True)
        print(f"  [OK] 3_sinyalizasyon ({moved_sig} dosya) -> 3_teknik_sartnameler/sinyalizasyon_test_prosedurleri/ (ChromaDB korundu)")

    # =========================================================================
    # 2. KİRAZLI - HALKALI METROSU (5 SÜTUNLU MİMARİYE HİZALAMA)
    # =========================================================================
    print("\n=== 2. KİRAZLI-HALKALI METROSU 5 SÜTUNLU MİMARİYE HİZALANIYOR ===")
    kh_dir = PROJE_EVRAKLARI_DIR / "kirazli_halkali_metro"
    ensure_5_pillars(kh_dir)

    kh_old_idari = kh_dir / "1_sozlesme_ve_idari"
    if kh_old_idari.exists():
        for fp in list(kh_old_idari.iterdir()):
            if not fp.is_file():
                continue
            fn_upper = fp.name.upper()
            if "İDARİ ŞARTNAME" in fn_upper or "IDARI SARTNAME" in fn_upper:
                migrate_file_and_update_db("kirazli_halkali_metro", fp, kh_dir / "2_idari_sartname" / fp.name, "idari_sartname", manifest, collection)
            elif "BİRİM FİYAT" in fn_upper or "ANALİZ FORMU" in fn_upper:
                migrate_file_and_update_db("kirazli_halkali_metro", fp, kh_dir / "4_birim_fiyat_ve_cetveller" / fp.name, "birim_fiyat_tarifi", manifest, collection)
            elif "TEKNİK ŞARTNAME" in fn_upper:
                migrate_file_and_update_db("kirazli_halkali_metro", fp, kh_dir / "3_teknik_sartnameler" / fp.name, "teknik_sartname", manifest, collection)
            else:
                migrate_file_and_update_db("kirazli_halkali_metro", fp, kh_dir / "1_sozlesme" / fp.name, "sozlesme", manifest, collection)
        if not any(kh_old_idari.iterdir()):
            kh_old_idari.rmdir()

    kh_old_ts = kh_dir / "2_teknik_sartnameler"
    if kh_old_ts.exists():
        for fp in list(kh_old_ts.iterdir()):
            if fp.is_file():
                migrate_file_and_update_db("kirazli_halkali_metro", fp, kh_dir / "3_teknik_sartnameler" / fp.name, "teknik_sartname", manifest, collection)
        if not any(kh_old_ts.iterdir()):
            kh_old_ts.rmdir()

    kh_old_bim = kh_dir / "3_bim_ve_sayisal_modelleme"
    if kh_old_bim.exists():
        for fp in list(kh_old_bim.iterdir()):
            if fp.is_file():
                migrate_file_and_update_db(
                    "kirazli_halkali_metro",
                    fp,
                    kh_dir / "3_teknik_sartnameler" / "bim_ve_sayisal_modelleme" / fp.name,
                    "teknik_sartname",
                    manifest,
                    collection,
                )
        if not any(kh_old_bim.iterdir()):
            kh_old_bim.rmdir()
    print("  [OK] Kirazlı-Halkalı tüm dosyaları 5 sütunlu mimariye taşındı (ChromaDB korundu).")

    # =========================================================================
    # 3. İKİTELLİ - ATAKÖY MÜŞAVİRLİK (5 SÜTUNLU MİMARİYE HİZALAMA)
    # =========================================================================
    print("\n=== 3. İKİTELLİ-ATAKÖY MÜŞAVİRLİK 5 SÜTUNLU MİMARİYE HİZALANIYOR ===")
    mus_dir = PROJE_EVRAKLARI_DIR / "ikitelli_atakoy_musavirlik"
    ensure_5_pillars(mus_dir)

    mus_old_idari = mus_dir / "1_sozlesme_ve_idari"
    if mus_old_idari.exists():
        for fp in list(mus_old_idari.iterdir()):
            if not fp.is_file():
                continue
            if "İdari Şartname" in fp.name or "Idari Sartname" in fp.name:
                migrate_file_and_update_db("ikitelli_atakoy_musavirlik", fp, mus_dir / "2_idari_sartname" / fp.name, "idari_sartname", manifest, collection)
            else:
                migrate_file_and_update_db("ikitelli_atakoy_musavirlik", fp, mus_dir / "1_sozlesme" / fp.name, "sozlesme", manifest, collection)
        if not any(mus_old_idari.iterdir()):
            mus_old_idari.rmdir()

    mus_old_ts = mus_dir / "2_teknik_sartnameler"
    if mus_old_ts.exists():
        for fp in list(mus_old_ts.iterdir()):
            if fp.is_file():
                migrate_file_and_update_db("ikitelli_atakoy_musavirlik", fp, mus_dir / "3_teknik_sartnameler" / fp.name, "teknik_sartname", manifest, collection)
        if not any(mus_old_ts.iterdir()):
            mus_old_ts.rmdir()
    print("  [OK] İkitelli-Ataköy Müşavirlik tüm dosyaları 5 sütunlu mimariye taşındı (ChromaDB korundu).")

    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[TAMAMLANDI] Manifest ve ChromaDB kayıtları güncellendi.")


if __name__ == "__main__":
    main()
