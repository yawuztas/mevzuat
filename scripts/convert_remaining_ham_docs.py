import sys
import base64
import time
from pathlib import Path
from bs4 import BeautifulSoup

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(r"d:\mevzuatinceleme")
sys.path.insert(0, str(PROJECT_ROOT))

from utils.document_parser import parse_image_with_rapid_local

ham_dir = PROJECT_ROOT / "data/2_proje_evraklari/ikitelli_atakoy_metro/ham_dosyalar"
target_dir = PROJECT_ROOT / "data/2_proje_evraklari/ikitelli_atakoy_metro/3_sinyalizasyon"

# ==============================================================================
# 1. ITCF-C24028-01-ATF-RA-00001 (Alstom ISA Bağımsız Emniyet Değerlendirme Raporu)
# ==============================================================================
print("=" * 80)
print("1. ALSTOM ISA BAĞIMSIZ EMNİYET RAPORU DÖNÜŞTÜRÜLÜYOR...")
print("=" * 80)

itcf_file = ham_dir / "ITCF-C24028-01-ATF-RA-00001 Rev.0.0_ISA_AS_Ikitelli.pdf.html"
if itcf_file.exists():
    soup = BeautifulSoup(itcf_file.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    
    # Başlıkları ve paragrafları düzenle
    text = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # Markdown formatına getir
    md_content = [
        "# Alstom Independent Safety Assessment (ISA) Report - İkitelli Metro Sinyalizasyon Sistemi",
        "**Doküman Kodu:** ITCF-C24028-01-ATF-RA-00001 Rev. 0.0",
        "**Kapsam:** İkitelli Metro Hattı ve Ataköy, Bakırköy, Kayaşehir Uzatmaları IXL (Interlocking) Özel Uygulaması",
        "**Tarih:** 06/03/2024",
        "**Kuruluş:** Alstom Transportation / Independent Safety Assessor\n",
        "---",
        "\n## Rapor İçeriği ve Emniyet Değerlendirmesi\n"
    ]
    
    curr_para = []
    for l in lines:
        if l.startswith("ASSESSMENT REPORT Rev.") or "ITCF-C24028-01-ATF-RA-00001 Pag." in l:
            continue
        if len(l) < 80 and any(l.isupper() for c in l if c.isalpha()) and not l.endswith("."):
            if curr_para:
                md_content.append(" ".join(curr_para) + "\n")
                curr_para = []
            md_content.append(f"\n### {l}\n")
        else:
            curr_para.append(l)
            if l.endswith(".") or len(curr_para) > 6:
                md_content.append(" ".join(curr_para) + "\n")
                curr_para = []
                
    if curr_para:
        md_content.append(" ".join(curr_para) + "\n")
        
    itcf_md_path = target_dir / "Alstom_ISA_Bagimsiz_Emniyet_Degerlendirme_Raporu_ITCF.md"
    final_itcf_text = "\n".join(md_content)
    itcf_md_path.write_text(final_itcf_text, encoding="utf-8")
    print(f"✔ Kaydedildi: {itcf_md_path.name} ({len(final_itcf_text):,} karakter)")

# ==============================================================================
# 2. doc07192020240301130017 (ATC Onboard Kirazlı-Bakırköy Hassas Duruş Test Kaydı)
# ==============================================================================
print("\n" + "=" * 80)
print("2. ATC ONBOARD HASSAS DURUŞ TEST KAYDI DÖNÜŞTÜRÜLÜYOR (8 Sayfa OCR)...")
print("=" * 80)

doc0719_file = ham_dir / "doc07192020240301130017.pdf.html"
if doc0719_file.exists():
    soup = BeautifulSoup(doc0719_file.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    imgs = soup.find_all("img")
    
    atc_md_content = [
        "# İkitelli Metro Hattı ATC Onboard Hassas Duruş (Precision Stop) Test Kayıtları",
        "**Doküman Kodu:** 3NSS008349",
        "**Hat / Güzergah:** Kirazlı - Bakırköy Kesimi",
        "**Sistem / Sürüm:** ATC 1.6.0 (4 vagonlu dizi - ATP 1.2.2, ATO 1.2.8)",
        "**Tarih:** 28.02.2024 - 29.02.2024",
        "**Test Ekibi:** Fatih DEMİR (T&C Technician), Kiattisak CHINPHAN (ATC Yazılım Grup Müdürü), Serkan DUYAN (Proje Müdürü)\n",
        "---"
    ]
    
    for idx, img in enumerate(imgs, 1):
        src = img.get("src", "")
        if "base64," in src:
            b64 = src.split("base64,")[1]
            raw = base64.b64decode(b64)
            print(f"  • Sayfa {idx}/8 OCR ile taranıyor...")
            page_ocr = parse_image_with_rapid_local(raw)
            atc_md_content.append(f"\n## --- Test Sayfası {idx} ---\n\n{page_ocr}\n")
            
    atc_md_path = target_dir / "ATC_Onboard_Hassas_Durus_Test_Kaydi_3NSS008349.md"
    final_atc_text = "\n".join(atc_md_content)
    atc_md_path.write_text(final_atc_text, encoding="utf-8")
    print(f"✔ Kaydedildi: {atc_md_path.name} ({len(final_atc_text):,} karakter)")

print("\n" + "=" * 80)
print("DÖNÜŞÜM TAMAMLANDI!")
print("=" * 80)
