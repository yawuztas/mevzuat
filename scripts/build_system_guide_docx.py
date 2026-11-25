import os
import sys
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

doc = docx.Document()

# ---------------------------------------------------------
# Sayfa Kenar Boşlukları (Standart Kurumsal Rapor Düzeni)
# ---------------------------------------------------------
for s in doc.sections:
    s.top_margin = Inches(0.8)
    s.bottom_margin = Inches(0.8)
    s.left_margin = Inches(0.8)
    s.right_margin = Inches(0.8)

# ---------------------------------------------------------
# Renk Paleti (Kurumsal & Teknik Şık Tasarım)
# ---------------------------------------------------------
COLOR_PRIMARY = RGBColor(16, 44, 87)       # Koyu Lacivert (Deep Navy)
COLOR_SECONDARY = RGBColor(41, 128, 185)   # Mavi (Ocean Blue)
COLOR_ACCENT = RGBColor(186, 24, 27)       # Koyu Kırmızı (Alert / Important)
COLOR_DARK = RGBColor(33, 37, 41)          # Koyu Antrasit (Gövde Metni)
COLOR_MUTED = RGBColor(108, 117, 125)      # Gri (Açıklama / Metadata)
COLOR_GREEN = RGBColor(25, 135, 84)        # Yeşil (Success)
COLOR_BG_LIGHT = "F8F9FA"                  # Çok Açık Gri Hücre Arka Planı
COLOR_BG_HEADER = "E9ECEF"                 # Tablo Başlığı Arka Planı
COLOR_BG_CALLOUT = "F0F4F8"                # Bilgi Kutusu Arka Planı

# ---------------------------------------------------------
# Yardımcı Şekillendirme Fonksiyonları
# ---------------------------------------------------------
def set_cell_background(cell, fill_hex):
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._element.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def add_header(title, level=1):
    h = doc.add_heading(level=level)
    run = h.add_run(title)
    run.font.name = 'Calibri'
    run.bold = True
    if level == 1:
        run.font.size = Pt(16)
        run.font.color.rgb = COLOR_PRIMARY
        h.paragraph_format.space_before = Pt(16)
        h.paragraph_format.space_after = Pt(4)
        h.paragraph_format.keep_with_next = True
    elif level == 2:
        run.font.size = Pt(13)
        run.font.color.rgb = COLOR_SECONDARY
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(3)
        h.paragraph_format.keep_with_next = True
    elif level == 3:
        run.font.size = Pt(11)
        run.font.color.rgb = COLOR_ACCENT
        h.paragraph_format.space_before = Pt(9)
        h.paragraph_format.space_after = Pt(2)
        h.paragraph_format.keep_with_next = True
    return h

def add_para(text, bold=False, italic=False, bullet=False, space_after=3):
    p = doc.add_paragraph(style='List Bullet' if bullet else 'Normal')
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run(text)
    run.font.name = 'Calibri'
    run.font.size = Pt(10)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = COLOR_DARK
    return p

def add_callout(text, prefix="MİMARİ PRENSİP / KRİTİK NOT:", color_hex="102C57"):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Inches(6.8)
    cell = tbl.cell(0, 0)
    set_cell_background(cell, COLOR_BG_CALLOUT)
    set_cell_margins(cell, top=120, bottom=120, left=180, right=180)
    
    tcPr = cell._element.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="36" w:space="0" w:color="{color_hex}"/>'
        f'<w:top w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'<w:bottom w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.15
    r1 = p.add_run(prefix + " ")
    r1.bold = True
    r1.font.name = 'Calibri'
    r1.font.size = Pt(9.5)
    if color_hex == "BA181B":
        r1.font.color.rgb = COLOR_ACCENT
    elif color_hex == "198754":
        r1.font.color.rgb = COLOR_GREEN
    else:
        r1.font.color.rgb = COLOR_PRIMARY
    
    r2 = p.add_run(text)
    r2.font.name = 'Calibri'
    r2.font.size = Pt(9.5)
    r2.font.color.rgb = COLOR_DARK
    
    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_before = Pt(0)
    p_spacer.paragraph_format.space_after = Pt(4)

def format_table(table, col_widths, headers, data, alignments=None):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    # Başlık Satırı
    hdr_cells = table.rows[0].cells
    for i, title in enumerate(headers):
        hdr_cells[i].width = Inches(col_widths[i])
        set_cell_background(hdr_cells[i], COLOR_BG_HEADER)
        set_cell_margins(hdr_cells[i], top=100, bottom=100, left=120, right=120)
        p = hdr_cells[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing = 1.1
        if alignments:
            p.alignment = alignments[i]
        run = p.add_run(title)
        run.bold = True
        run.font.name = 'Calibri'
        run.font.size = Pt(9.5)
        run.font.color.rgb = COLOR_PRIMARY

    # Veri Satırları
    for r_idx, row_data in enumerate(data):
        row_cells = table.add_row().cells
        bg_color = COLOR_BG_LIGHT if r_idx % 2 == 1 else "FFFFFF"
        for c_idx, val in enumerate(row_data):
            row_cells[c_idx].width = Inches(col_widths[c_idx])
            set_cell_background(row_cells[c_idx], bg_color)
            set_cell_margins(row_cells[c_idx], top=80, bottom=80, left=120, right=120)
            p = row_cells[c_idx].paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing = 1.1
            if alignments:
                p.alignment = alignments[c_idx]
            run = p.add_run(str(val))
            run.font.name = 'Calibri'
            run.font.size = Pt(9)
            run.font.color.rgb = COLOR_DARK

    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_before = Pt(0)
    p_spacer.paragraph_format.space_after = Pt(4)


# ==============================================================================
# KAPAK VE BAŞLIK
# ==============================================================================
p_cover_pre = doc.add_paragraph()
p_cover_pre.paragraph_format.space_before = Pt(20)
p_cover_pre.paragraph_format.space_after = Pt(4)
p_cover_pre.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_pre = p_cover_pre.add_run("T.C. KAMU VE RAYLI SİSTEMLER YAPIM / MÜŞAVİRLİK SÖZLEŞMELERİ DENETİM OTOMASYONU")
r_pre.font.name = 'Calibri'
r_pre.font.size = Pt(11)
r_pre.font.color.rgb = COLOR_MUTED
r_pre.bold = True

p_cover_title = doc.add_paragraph()
p_cover_title.paragraph_format.space_before = Pt(2)
p_cover_title.paragraph_format.space_after = Pt(6)
p_cover_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_title = p_cover_title.add_run("SİSTEM ÇALIŞMA MİMARİSİ VE KOD BAĞLANTI REHBERİ\n(LIVING BLUEPRINT & DEVELOPER MANUAL)")
r_title.font.name = 'Calibri'
r_title.font.size = Pt(20)
r_title.font.color.rgb = COLOR_PRIMARY
r_title.bold = True

p_cover_sub = doc.add_paragraph()
p_cover_sub.paragraph_format.space_before = Pt(2)
p_cover_sub.paragraph_format.space_after = Pt(16)
p_cover_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_sub = p_cover_sub.add_run(
    "InsaatAudit: Çok Katmanlı Ayrıştırma, Standart Hop-2 Genişletmeli BGE-M3 Hibrit RAG, "
    "SQLite Yazışma Hafızası, LangGraph 6 Düğümlü Çoklu Ajan ve Kapalı Döngü Denetim Mimarisi"
)
r_sub.font.name = 'Calibri'
r_sub.font.size = Pt(11)
r_sub.font.color.rgb = COLOR_SECONDARY
r_sub.italic = True

add_callout(
    "BU BELGE PROJENİN TEKNİK VE MİMARİ HAFIZASIDIR: Sisteme yeni bir geliştirici veya YZ ajanı dahil olduğunda, "
    "tüm kod tabanını ve binlerce dosyalık arşivi baştan taramaya gerek kalmaksızın sistemin çalışma prensibini, "
    "Adım 1–5 mimari katmanlarını, kodların birbirine bağlantılarını, kütüphane ekosistemini ve veri akışını doğrudan bu belgeden okuyacaktır. "
    "Yapılan her köklü güncellemede bu doküman güncellenerek senkronize tutulacaktır.",
    prefix="AMAÇ VE PROTOKOL:",
    color_hex="102C57"
)


# ==============================================================================
# BÖLÜM 1: GENEL BAKIŞ VE SİSTEMİN TEMEL AMACI
# ==============================================================================
add_header("1. SİSTEMİN AMACI VE GENEL ÇALIŞMA PRENSİBİ", level=1)

add_para(
    "InsaatAudit, büyük ölçekli altyapı, raylı sistem yapım ve müşavirlik/danışmanlık projelerinde (metro hatları, tüneller, elektromekanik sistemler, kontrollük hizmetleri vb.) "
    "yükleniciler tarafından İdareye sunulan dilekçeleri (süre uzatımı, ek fiyat farkı, revize iş programı, yeni birim fiyat, "
    "tasarım değişikliği, malzeme onay itirazları, bağımsız emniyet değerlendirme ve test tutanakları) otonom olarak denetleyen "
    "ve İdareye bağlayıcı resmi inceleme raporu üreten yapay zekâ tabanlı bir denetim platformudur."
)

add_para("Sistem dört bütüncül aşamadan (Adım 1–5 Mimari Dönüşümü) oluşur:")
add_para("1. Evrak Ayrıştırma, Disiplin & Standart Normalizasyonu (Adım 1–2): Yüzlerce sayfalık taranmış/dijital PDF sözleşme, şartname ve standartları sayfa hiyerarşisiyle okur; ihale türü (yapim / danismanlik / ortak), mühendislik disiplini (subsystem), rol (doc_role) ve kanonik standart kodları (EN/IEC/TS EN/ISO/NFPA) etiketleriyle ChromaDB vektör veri tabanına indeksler.", bullet=True)
add_para("2. Yapısal Vaka Hafızası & Yazışma Zinciri İnşası (Adım 3): Resmi yazışmaları deterministik regex + dateparser (DATE_ORDER='DMY') + opsiyonel instructor/langextract (char_interval kanıt izi) ile Kimlik Kartı'na dönüştürür; 'İlgi:' atıflarını 2 turlu eşleştirme + özyinelemeli CTE ile SQLite (project_graph.db) çizgesinde bağlar; eksik başlıklı evrakları insan onay kuyruğuna (pending_review) ayırır.", bullet=True)
add_para("3. 6 Düğümlü Çoklu Ajan Denetimi & Kanıt Ağırlıklı Bağlam (Adım 4): case_builder_node düğümü, SQLite İlgi zincirini + açık talepleri + geçmiş İdare cevaplarını 90.000 karakterlik bütçeye [KANIT TÜRÜ: TUTANAK_ORTAK / RESMİ POZİSYON / İDDİA] ağırlıklarıyla derler. Ardından Router ve Uzman Ajanlar, Hop 1 + döngü korumalı Hop 2 Standart/Norm genişletmeli hibrit arama (BM25 + BGE-M3 + BGE-Reranker) ile incelemeyi tamamlar.", bullet=True)
add_para("4. Sentez, Alıntı Doğrulama & Kapalı Döngü Durum Makinesi (Adım 4–5): Baş Denetçi raporu sentezler, Citation Verifier kanun/standart kodlarını (extract_standard_refs) ChromaDB ile doğrular. Nihai İdare cevabı verildiğinde record_admin_reply + confirm_transition (confirmed_by_human=1 zorunlu) ile ilgili yüklenici talepleri denetim iziyle kapatılır.", bullet=True)


# ==============================================================================
# BÖLÜM 2: DİZİN VE VERİ YERLEŞİM MİMARİSİ
# ==============================================================================
add_header("2. DİZİN YAPISI VE 3 BOYUTLU İZOLE VERİ MİMARİSİ", level=1)

add_para(
    "Sistemde proje sayısı 6-10'a çıktığında ve yüzlerce standart eklendiğinde global havuzun şişip alakasız evrakların taranmasını "
    "önlemek amacıyla 3 Boyutlu İzolasyon (Proje Kapsamı + İhale Türü + Mühendislik Disiplini) uygulanmaktadır:"
)

tree_text = """d:\\mevzuatinceleme\\
├── .env                                  # API anahtarları (Google Gemini, Anthropic vb.)
├── requirements.txt                      # Kesinleştirilmiş Python bağımlılıkları (pip check = 0 hata)
├── README.md                             # Hızlı başlangıç ve kullanım kılavuzu
├── 1_ingest.py                           # Master Veri İndeksleme (doc_role, subsystem, standard_codes etiketli)
├── 2_agents_graph.py                     # LangGraph 6 Düğümlü Çoklu Ajan + Hop-2 Standart + Vaka Hafızası Akışı
├── ingest_history.py                     # Geçmiş Yazışmaları 2 Turlu İlgi Çözümleme ile SQLite+Chroma'ya Alıcı
├── generate_final_report.py              # Denetim sonuçlarını resmi Word (.docx) raporuna dönüştürücü
├── SISTEM_MIMARISI_VE_CALISMA_REHBERI.docx # Bu teknik referans kılavuzu
│
├── utils/                                # Çekirdek Kütüphaneler ve Adım 2–5 Yapısal Katmanlar
│   ├── config.py                         # Dizin sabitleri, LLM konfigürasyonları ve ortam değişkenleri
│   ├── text_tr.py                        # Türkçe karakter katlama (tr_lower, ascii_fold) motoru
│   ├── document_parser.py                # Akıllı Hibrit OCR (.cache_ocr destekli Docling/PyMuPDF/RapidOCR)
│   ├── retriever.py                      # ChromaDB + BGE-M3 + BM25 + BGE-Reranker + Hop-2 Standart Genişletme
│   ├── standards.py                      # Standart/Norm kanonikleştirici (EN/IEC/TS EN/ISO/NFPA -> standard_codes)
│   ├── project_db.py                     # SQLite 4 Tablolu Yazışma Çizgesi, CTE Zinciri & Onaylı Durum Makinesi
│   ├── card_extractor.py                 # Resmi Yazı Kimlik Kartı (Regex + DMY dateparser + instructor/langextract)
│   ├── case_context_builder.py           # Vaka Hafızası Toplayıcısı ([KANIT TÜRÜ] ağırlıklı, 90k sabit bütçe)
│   └── closed_loop.py                    # İdare Cevabı Kapalı Döngü Kayıt & İnsan Onaylı Durum Geçiş Önerici
│
├── scripts/                              # Operasyon, Kuyruk, Pilot ve Regresyon Araçları
│   ├── review_queue.py                   # pending_review kartları için 10 saniyelik insan onay arayüzü
│   ├── close_loop_reply.py               # İdare cevabını sisteme geri işleyen CLI aracı
│   ├── run_pilot_eval.py                 # 25 Gerçek Yazılık Adım 5 Pilot Değerlendirme ve Ölçüm Aracı
│   ├── build_system_guide_docx.py        # Bu yaşayan mimari rehberi üreten script
│   └── test_step2..5_*.py                # Adım 2–5 regresyon, temel ve uçtan uca doğrulama testleri
│
├── data/                                 # 3 Seviyeli Veri Havuzu (İhale Türü ve Disiplin Etiketli)
│   ├── 1_genel_mevzuat_ve_standartlar/   # [SEVİYE 1 - GLOBAL] İhale Türü ve Disiplin Bazlı Hiyerarşi (25 Dosya)
│   │   ├── 1_kanunlar/                   # 4734 (KİK), 4735 (Sözleşmeler Kanunu) [procurement_type='ortak']
│   │   ├── 2_sozlesme_ve_genel_sartnameler/
│   │   │   ├── yapim_isleri/             # YİGŞ, Yapım Uygulama & Kabul Yön. [procurement_type='yapim']
│   │   │   └── danismanlik_ve_musavirlik/# Danışmanlık Hizmet İşleri Genel Şartnamesi [procurement_type='danismanlik']
│   │   ├── 3_tebligler_ve_kararnameler/  # 2013/5608 Fiyat Farkı Esasları, KİK Genel Tebliği [procurement_type='ortak']
│   │   ├── 4_standart_normlar/           # Mühendislik Disiplinlerine Göre İzole Normlar [subsystem etiketli]
│   │   │   ├── sinyalizasyon_ve_cbtc/    # CENELEC EN 50126/128/129, IEEE 1474 [subsystem='sinyalizasyon_cbtc']
│   │   │   ├── cer_gucu_ve_elektrifikasyon/ # EN 50122, EN 50163, 750V/1500V DC [subsystem='cer_gucu_ve_elektrifikasyon']
│   │   │   ├── zayif_akim_ve_scada/      # SCADA, TETRA, CCTV, EN 54, PSD [subsystem='zayif_akim_ve_scada']
│   │   │   ├── yangin_ve_havalandirma/   # NFPA 130, EN 12101, TVS Jet Fan [subsystem='havalandirma_ve_yangin_tvs']
│   │   │   ├── asansor_ve_yuruyen_merdiven/ # EN 115-1, EN 81-20/50/70/72 [subsystem='asansor_ve_yuruyen_merdiven']
│   │   │   ├── demiryolu_ustyapi_ve_ray/ # EN 13674, UIC 60, Slab Track [subsystem='demiryolu_ustyapi_ve_ray']
│   │   │   ├── insaat_ve_geoteknik/      # TBDY 2018, TS 500, Eurocode 2/7, TBM/NATM
│   │   │   └── genel_rayli_sistemler/    # AYGM Katalogları ve Çok Disiplinli Rehberler
│   │   └── 5_standart_formlar/           # Şantiye defteri, yeşil defter, hakediş ve kabul şablonları
│   │
│   ├── 2_proje_evraklari/                # [SEVİYE 2 - PROJE İZOLASYONU & 5 SÜTUNLU PROJE MİMARİSİ]
│   │   ├── ikitelli_atakoy_metro/        # İkitelli-Ataköy M9 Hattı [procurement_type='yapim']
│   │   │   ├── 1_sozlesme/               # İmzalı Sözleşme (s.1-65) + EKAP Dijital Sözleşme Tasarısı [doc_type='sozlesme']
│   │   │   ├── 2_idari_sartname/         # İhale İdari Şartnamesi (s.66-157) [doc_type='idari_sartname']
│   │   │   ├── 3_teknik_sartnameler/     # %100 Dijital 10 Disiplin Bölümü (s.1-660) + Test Prosedürleri [doc_type='teknik_sartname']
│   │   │   ├── 4_birim_fiyat_ve_cetveller/# Birim Fiyat Tarifleri, Analiz Formatı & Cetvel (s.202-318) [doc_type='birim_fiyat_tarifi']
│   │   │   └── 5_zeyilnameler_ve_soru_cevaplar/ # Zeyilname-1/2 ve İdare Soru-Cevapları (s.158-201) [doc_type='zeyilname_ve_aciklama']
│   │   ├── kirazli_halkali_metro/        # Kirazlı-Halkalı Metro Hattı (Aynı 5 Sütunlu Standart Yapı) [procurement_type='yapim']
│   │   └── ikitelli_atakoy_musavirlik/   # Müşavirlik Sözleşme ve Şartnameleri (5 Sütunlu Yapı) [procurement_type='danismanlik']
│   │
│   ├── 3_yuklenici_talepleri/            # [SEVİYE 3 - YAZIŞMALAR] Proje bazlı yazışma & talep klasörleri (temiz başlangıç)
│   │   ├── ikitelli_atakoy_metro/        # Boş proje klasörü (gerçek yazışmalar eklendikçe ingest_history ile işlenir)
│   │   ├── kirazli_halkali_metro/        # Boş proje klasörü
│   │   ├── ikitelli_atakoy_musavirlik/   # Boş proje klasörü
│   │   └── ornek_proje/                  # Sentetik demo dilekçesi
│   │
│   └── raporlar/                         # Üretilen resmi denetim raporları (.md ve .docx)
│
├── vector_db/                            # [CHROMA #1] Saf Normatif Vektör DB (Katman 1 + Katman 2)
│   ├── chroma.sqlite3                    # HNSW Cosine indeksli veritabanı (11.098 saf normatif vektör, 0 yazışma)
│   └── ingested_manifest.json            # project_id::rel_path artımlı indeks manifesti
│
├── vector_db_yazismalar/                 # [CHROMA #2] Fiziksel Ayrı Yazışma Vektör DB (Katman 3: proje_yazismalari)
├── data/project_graph.db                 # SQLite 4 Tablolu Proje Yazışma Çizgesi (documents, links, tags, state_history)
├── ui_app.py                             # NiceGUI + Apache ECharts + Cytoscape.js 4 Sekmeli Görsel Denetim Stüdyosu
│
└── _arsiv/                               # İzole Edilmiş Yedekler ve Ham Dosyalar (Aramaya Kapalı)
    ├── root_scripts/                     # Geçici test ve kıyaslama scriptleri
    ├── cache_backups/                    # Eski mükerrer OCR önbellekleri (.cache_ocr_backup_old)
    ├── duplicate_test_pdfs/              # 3_yuklenici_talepleri altından taşınan 73 mükerrer PDF (1.1 GB)
    └── html_stubs/                       # Eski kesik kalmış HTML ve ara çıktı taslakları
"""

p_tree = doc.add_paragraph()
p_tree.paragraph_format.space_before = Pt(4)
p_tree.paragraph_format.space_after = Pt(6)
p_tree.paragraph_format.line_spacing = 1.05
r_tree = p_tree.add_run(tree_text)
r_tree.font.name = 'Consolas'
r_tree.font.size = Pt(8)
r_tree.font.color.rgb = COLOR_DARK


# ==============================================================================
# BÖLÜM 3: KOD BAĞLANTILARI VE ETKİLEŞİM HARİTASI
# ==============================================================================
add_header("3. KOD MODÜLLERİ VE ÇALIŞMA BAĞLANTILARI (DEPENDENCY GRAPH)", level=1)

add_para(
    "Projedeki her kod modülü tek bir amaca hizmet edecek şekilde katmanlı ve gevşek bağlı (loosely coupled) "
    "olarak tasarlanmıştır. Modüller arasındaki çağrı hiyerarşisi aşağıda özetlenmiştir:"
)

tbl_deps = doc.add_table(rows=1, cols=4)
format_table(
    table=tbl_deps,
    col_widths=[1.5, 1.8, 1.8, 1.7],
    headers=["Modül / Dosya", "Kullandığı (Imports)", "Kullanan Modüller", "Temel Görevi"],
    data=[
        [
            "utils/text_tr.py",
            "re, unicodedata",
            "1_ingest.py, retriever.py, document_parser.py, 2_agents_graph.py",
            "Türkçe 'İ-i', 'I-ı' harf dönüşümleri ve aksan katlama (tr_lower, ascii_fold)."
        ],
        [
            "utils/config.py",
            "os, pathlib, dotenv, langchain",
            "1_ingest.py, retriever.py, document_parser.py, 2_agents_graph.py",
            "Tüm klasör yolları, model adları ve LLM istemcisi oluşturucu (get_llm)."
        ],
        [
            "utils/document_parser.py",
            "fitz (PyMuPDF), docling, rapidocr, rapid_table, google-genai",
            "1_ingest.py, 2_agents_graph.py",
            "Triage ile PDF/DOCX/Resim dosyalarını sayfa numaralı Markdown'a çevirme ve bütünlük kontrolü."
        ],
        [
            "utils/standards.py",
            "re, utils.text_tr",
            "1_ingest.py, retriever.py, 2_agents_graph.py, ingest_history.py",
            "EN, IEC, TS EN, ISO, NFPA, BS, DIN standart kodlarını base+subs ile kanonikleştirir; arama takma adlarını üretir."
        ],
        [
            "utils/project_db.py",
            "sqlite3, hashlib, rapidfuzz, json",
            "ingest_history.py, case_context_builder.py, closed_loop.py, review_queue.py",
            "4 tablolu SQLite çizgesi (documents/links/tags/state_history); CTE zincir yürütme ve insan onaylı durum makinesi."
        ],
        [
            "utils/card_extractor.py",
            "dateparser (DMY), instructor, langextract, re",
            "ingest_history.py, case_context_builder.py, run_pilot_eval.py",
            "Aşama 1 deterministik resmi yazı kimlik kartı + Aşama 2 opsiyonel Pydantic LLM & char_interval kanıt izleme."
        ],
        [
            "utils/case_context_builder.py",
            "sqlite3, utils.project_db, utils.card_extractor, utils.retriever",
            "2_agents_graph.py, closed_loop.py, run_pilot_eval.py",
            "SQLite İlgi zinciri + açık talepler + geçmiş cevapları [KANIT TÜRÜ] ağırlığıyla 90.000 krk bütçeye derler."
        ],
        [
            "utils/closed_loop.py",
            "utils.project_db, utils.card_extractor, utils.retriever",
            "scripts/close_loop_reply.py, scripts/run_pilot_eval.py",
            "İdare/Müşavir cevabını Kimlik Kartı ile işler, durum önerir, yalnızca confirmed_by_human=1 ile talep kapatır."
        ],
        [
            "utils/retriever.py",
            "chromadb, FlagEmbedding, rank_bm25, torch, text_tr, standards",
            "1_ingest.py, 2_agents_graph.py, case_context_builder.py, closed_loop.py",
            "ChromaDB istemcisi, Hop-1 ihale/disiplin filtreli hibrit arama + döngü korumalı Hop-2 standart genişletmesi."
        ],
        [
            "1_ingest.py",
            "utils.config, utils.retriever, utils.document_parser, utils.standards, utils.text_tr",
            "Bağımsız CLI aracı (Komut satırından çalışır)",
            "Evrakları okur, procurement_type, subsystem, doc_role ve standard_codes etiketleriyle ChromaDB'ye yazar."
        ],
        [
            "ingest_history.py",
            "utils.document_parser, utils.card_extractor, utils.project_db, utils.standards",
            "Bağımsız CLI aracı (Yazışma arşivi besleme)",
            "Yazışmaları 2 turlu İlgi eşleştirme ve OCR iskelet toleransıyla SQLite+ChromaDB'ye kronolojik bağlar."
        ],
        [
            "2_agents_graph.py",
            "langgraph, langchain_core, utils.retriever, utils.case_context_builder, utils.standards",
            "Bağımsız CLI / UI Motoru (Denetim çalıştırıcı)",
            "LangGraph 6 düğümlü StateGraph akışını çalıştırır: Reader -> CaseBuilder -> Router -> Experts -> ChiefAuditor -> Verifier."
        ],
        [
            "generate_final_report.py",
            "python-docx, os",
            "Kullanıcı / Rapor Motoru",
            "Üretilen denetim raporunu kurumsal Word (.docx) formatına dönüştürür."
        ]
    ]
)


# ==============================================================================
# BÖLÜM 4: KÜTÜPHANELER, PROGRAMLAR VE YAPAY ZEKA MODELLERİ
# ==============================================================================
add_header("4. TEKNOLOJİ STACK'İ, KÜTÜPHANELER VE MODELLER", level=1)

add_para("Sistemde kullanılan kritik program, donanım, model ve kütüphaneler:")

tbl_tech = doc.add_table(rows=1, cols=4)
format_table(
    table=tbl_tech,
    col_widths=[1.6, 1.4, 1.4, 2.4],
    headers=["Bileşen / Kütüphane", "Sürüm / Tür", "Çalışma Ortamı", "Kullanım Amacı ve Avantajı"],
    data=[
        [
            "NVIDIA CUDA & PyTorch",
            "CUDA 12.8 / PyTorch 2.12+",
            "Donanım / GPU",
            "BGE-M3, BGE-Reranker, RapidOCR ve Docling modellerini yerel GPU üzerinde milisaniyeler seviyesinde çalıştırma."
        ],
        [
            "BAAI / bge-m3",
            "1024 Boyutlu Yoğun Vektör",
            "HuggingFace / FlagEmbedding (GPU)",
            "Türkçe teknik şartname ve mevzuat dilini anlayan en güçlü çok dilli dense embedding modeli."
        ],
        [
            "BAAI / bge-reranker-v2-m3",
            "Cross-Encoder Reranker",
            "FlagEmbedding (GPU)",
            "Dense arama ve BM25 ile gelen ilk 25-30 adayı soru-metin çifti olarak derinlemesine puanlayıp en iyi 4 adayı seçme."
        ],
        [
            "rank-bm25 (BM25Okapi)",
            "v0.2.2 (Lexical Engine)",
            "In-Memory Python (mtime duyarlı)",
            "EN 50122, Poz 04.191, Madde 10 gibi birebir kod ve poz numarası aramalarında tam isabet sağlama."
        ],
        [
            "ChromaDB",
            "v1.5.9 (PersistentClient)",
            "Yerel Disk / SQLite",
            "HNSW kosinüs benzerliği indeksli, proje, ihale türü ve disiplin filtrelemeyi ($and, $or, $in) destekleyen gömülü vektör tabanı."
        ],
        [
            "IBM Docling v2",
            "v2.130.0",
            "Yerel Python (CUDA)",
            "Küçük/orta boy dokümanlarda başlık hiyerarşisi, karmaşık tablolar ve antetleri sayfa işaretli yapısal Markdown'a çevirme."
        ],
        [
            "RapidOCR & RapidTable",
            "v3.9.2 & v3.0.2",
            "ONNXRuntime CUDAExecutionProvider",
            "Taranmış yüzlerce sayfalık büyük sözleşmelerde sayfa başına 0.4 sn hızında GPU hızlandırmalı yerel OCR akışı."
        ],
        [
            "PyMuPDF (fitz)",
            "v1.24.14",
            "Yerel C++ / Python",
            "Dijital şartnamelerden yüksek hızlı metin çekme, mükerrersiz tablo katmanı çıkarma ve 150 DPI sayfa görseli oluşturma."
        ],
        [
            "Google Gemini 2.5 Flash",
            "LLM (Google GenAI API)",
            "Bulut API",
            "Router analizi, uzman ajan değerlendirmesi ve baş denetçi sentezi için yüksek hızlı, 1M token pencereli ana zeka (Anthropic Claude seçeneğiyle)."
        ],
        [
            "LangGraph & LangChain",
            "v1.2.12 / v1.4.2",
            "Python Çerçevesi",
            "6 düğümlü AgentState yönetimi, case_builder_node yönlendirmesi ve çoklu ajan akış orkestrasyonu."
        ],
        [
            "SQLite 3 + RapidFuzz",
            "SQLite WAL + rapidfuzz v3.14.6",
            "Yerel Disk (data/project_graph.db)",
            "Özyinelemeli CTE İlgi zinciri sorguları, evrak no bulanık + OCR iskelet eşleştirme ve durum denetim izi."
        ],
        [
            "dateparser + instructor + langextract",
            "v1.5.0 / v1.17.0 / v1.7.2",
            "Python + Gemini GenAI SDK 2.25.0",
            "DATE_ORDER='DMY' kilitli Türkçe tarih çözme, Pydantic tip-güvenli LLM çıkarımı ve char_interval kaynak-geri izleme."
        ]
    ]
)


# ==============================================================================
# BÖLÜM 5: DOKÜMAN İŞLEME VE VEKTÖRLEŞTİRME MİMARİSİ (1_ingest.py)
# ==============================================================================
add_header("5. DOKÜMAN İŞLEME VE İNDEKSLEME DETAYLARI (1_ingest.py)", level=1)

add_para(
    "1_ingest.py, ham dokümanların veritabanına aktarılmasından sorumlu ana orkestrasyondur. "
    "Sistemin doğruluğunu sağlayan çekirdek mekanizmalar aşağıdadır:"
)

add_header("A. Akıllı Hibrit Doküman Triage (document_parser.py)", level=2)
add_para("Bir PDF sisteme girdiğinde doğrudan tek bir motora verilmez; evrakın fiziksel karakteristiğine göre en verimli yola yönlendirilir:")
add_para("• Rota 1 (Docling v2 CUDA): Evrak <= 30 sayfa ve dijital metin < %70 ise (kısa tutanaklar, formlar, özel tablolar). Sayfa bazlı dışa aktarım ile her sayfaya '## --- Sayfa X ---' etiketi basar.", bullet=True)
add_para("• Rota 2 (PyMuPDF Hızlı Dijital Yol): Dijital metin oranı >= %70 ise (dijital üretilmiş şartnameler). Sayfa başına 0.02 saniyede PyMuPDF ile metin + mükerrersiz dijital tablo katmanını Markdown'a aktarır.", bullet=True)
add_para("• Rota 3 (Yerel RapidOCR CUDA Akışı): Sayfa sayısı > 30 ve taranmış ise (İkitelli'nin 318 sayfalık sözleşmesi veya 660 sayfalık şartnamesi gibi). 150 DPI sayfa render + RapidOCR + RapidTable ile sayfa sayfa işlenir. Yalnızca bozulma skoru aşırı yüksek olan sayfalarda cerrahi olarak Gemini Vision (60 sn timeout, maks. 5 çağrı) devreye girer.", bullet=True)
add_para("• Bütünlük Muhafızı (Integrity Guard): Sayfa bazlı try/except koruması altındadır. Gerçek metin çıkarılan sayfa oranı %75'in altına düşerse DocumentIntegrityError fırlatılır; kesik ya da bozuk evrak sisteme sokulmaz.", bullet=True)

add_header("B. Anlamsal Parçalama ve Sayfa Numarası Takibi (split_markdown_into_legal_chunks)", level=2)
add_para(
    "Geleneksel kör karakter bölme (fixed-size chunking) hukuk ve şartname metinlerinde maddeyi ortadan bölerek anlamı bozar. "
    "InsaatAudit'te parçalama: 'MADDE X', 'Madde X', 'Bölüm X', 'Poz X' ve Markdown başlıklarına (#, ##) göre yapılır. "
    "Maddenin uzunluğu 1800 karakteri aşıyorsa paragraf sınırlarından bölünür."
)
add_callout(
    "SAYFA NUMARASI AYRIMI (page_num >= 1 vs page_num = 0): Fiziksel sayfa işaretleyicisi ('## --- Sayfa X ---') içeren PDF ve taranmış "
    "belgelerde gerçek sayfa numarası (1..N) saklanır. Fiziksel sayfası olmayan saf dijital Markdown/HTML mevzuat belgelerinde ise "
    "has_page_marker=False ve page_num=0 atanır; böylece doğrulama tablosunda sahte 'Sayfa 1' yerine 'Dijital Belge' ibaresi gösterilir.",
    prefix="SAYFA METADATA GÜVENCESİ:",
    color_hex="198754"
)

add_header("C. İhale Türü (procurement_type) ve Klasör Güdümlü Disiplin (subsystem) Etiketleme", level=2)
add_para(
    "Genel mevzuat ve standartlar havuzu büyüdükçe bir yapım işinde danışmanlık şartnamesinin veya bir sinyalizasyon işinde "
    "asansör/tünel standardının taranmasını engellemek için iki boyutlu akıllı etiketleme uygulanır:"
)
add_para("1. İhale Türü (procurement_type): Her parça 'yapim' (YİGŞ, yapım projeleri), 'danismanlik' (Danışmanlık Hizmet İşleri Genel Şartnamesi, müşavirlik projeleri) veya 'ortak' (4734 KİK, 4735, Fiyat Farkı Esasları, Teknik Standartlar) olarak etiketlenir.", bullet=True)
add_para("2. Klasör Güdümlü Disiplin Önceliği (detect_folder_subsystem): 4_standart_normlar/ altındaki disiplin klasörlerine (sinyalizasyon_ve_cbtc, cer_gucu_ve_elektrifikasyon, zayif_akim_ve_scada, yangin_ve_havalandirma, asansor_ve_yuruyen_merdiven, demiryolu_ustyapi_ve_ray) konulan standartlar otomatik olarak ilgili subsystem (+6 öncelik puanı ve varsayılan fallback) ile etiketlenir.", bullet=True)
add_para("3. Dinamik Master Şartname Çözümlemesi: 'TAM_TEKNIK_SARTNAME_*' veya 'genel_rayli_sistemler/' altındaki çok disiplinli kataloglar 'karma' domaini alır ve her madde kendi içeriğine göre doğru mühendislik disiplinine yönlendirilir.", bullet=True)
add_para("4. Yetim Kayıt Temizliği (Orphan Cleanup): Klasörü değişen veya silinen dosyaların eski vektörleri artımlı çalışmada otomatik olarak tespit edilip ChromaDB ve manifestten temizlenir.", bullet=True)


# ==============================================================================
# BÖLÜM 6: ÇOKLU AJAN GRAFİĞİ VE DENETİM DÖNGÜSÜ (2_agents_graph.py)
# ==============================================================================
add_header("6. ÇOKLU AJAN DENETİM GRAFİĞİ (2_agents_graph.py)", level=1)

add_para(
    "2_agents_graph.py, LangGraph StateGraph mimarisi üzerinde Vaka Hafızası ve Standart/Norm genişletmeli "
    "6 düğümlü otonom bir denetim yürütür. Ajan grafiğinin düğümleri ve sorumlulukları:"
)

tbl_nodes = doc.add_table(rows=1, cols=3)
format_table(
    table=tbl_nodes,
    col_widths=[1.5, 2.0, 3.3],
    headers=["Düğüm (Node)", "Girdi / Çıktı", "İş Mantığı ve Sorumluluk Alanı"],
    data=[
        [
            "1. reader_node",
            "Girdi: doc_path\nÇıktı: doc_text, project_id, procurement_type",
            "Yüklenici evrakını document_parser ile okur. Evrakın dosya yolundan projesini ('ikitelli_atakoy_metro' vb.) ve ihale türünü ('yapim' veya 'danismanlik') tespit ederek kapsamı kilitler."
        ],
        [
            "2. case_builder_node",
            "Girdi: doc_text, doc_path, project_id\nÇıktı: case_context, case_metadata",
            "VAKA HAFIZASI DÜĞÜMÜ (Adım 4): Resmi yazıdan Kimlik Kartı ve 'İlgi:' referanslarını çıkarır; project_graph.db üzerinden özyinelemeli CTE zincirini, açık talepleri ve İdare cevaplarını 90.000 karakterlik bütçeye [KANIT TÜRÜ] ağırlıklarıyla derler."
        ],
        [
            "3. router_node",
            "Girdi: doc_text, case_context\nÇıktı: router_result (Pydantic/JSON)",
            "Gemini LLM ile evrakı ve tarihsel vaka özetini teşhis eder: Belge türünü, talep özetini, hedef mühendislik disiplinlerini (target_subsystems) ve görüş alınacak uzman domainleri (mevzuat, idari, elektromekanik, insaat) belirler."
        ],
        [
            "4. expert_consultation_node",
            "Girdi: router_result, doc_text, case_context\nÇıktı: expert_analyses",
            "Her uzman domain için matched_subs ve procurement_type bilgisini retriever.search_and_rerank motoruna iletir. Hop-1 şartname/sözleşme + Hop-2 standart genişletmesi ve vaka hafızası kanıtlarıyla haklılık analizi yapar."
        ],
        [
            "5. chief_auditor_node",
            "Girdi: expert_analyses, case_context\nÇıktı: final_report",
            "Tüm uzman raporlarını ve vaka geçmişini sentezler; çelişen veya daha önce reddedilmiş/cevaplanmış talepleri yakalayarak İdare adına bağlayıcı resmi denetim raporu üretir."
        ],
        [
            "6. citation_verifier_node",
            "Girdi: final_report, ChromaDB\nÇıktı: verified_report",
            "GERÇEK ZAMANLI DOĞRULAYICI: Rapordaki kanun/şartname maddelerini ve extract_standard_refs(final_report) ile kanonikleştirilen standart atıflarını ChromaDB indeksiyle doğrular; fiziksel sayfa numaralarını tabloya işler."
        ]
    ]
)

add_header("Arama Motoru Mimarisi: 3 Boyutlu Filtreleme + Hibrit RAG + Hop-2 Standart Genişletme", level=2)
add_para("Uzman ajanların arama sorguları şu 7 aşamalı süzgeçten geçer:")
add_para("1. Proje ve İhale Türü İzolasyonu: Seçili projenin evrakları + Genel havuzdaki uyumlu ihale türü (yapim işinde 'yapim'+'ortak'; danismanlik işinde 'danismanlik'+'ortak') taranır.", bullet=True)
add_para("2. Disiplin Korumalı Dense & BM25 Arama (Hop 1): BGE-M3 (1024-d) ve rank-bm25 ile yalnızca yetkili alt disiplinler içinde arama yapılır; alakasız disiplinlere gevşetme yapılmaz.", bullet=True)
add_para("3. RRF + Cross-Encoder BGE-Reranker: Dense ve BM25 sıralamaları RRF (1/(60+rank)) ile birleştirilir ve BGE-Reranker-v2-m3 en iyi adayları seçer.", bullet=True)
add_para("4. Parent-Child Genişletme: Metadata'daki parent_content ile maddenin tam metni korunur.", bullet=True)
add_para("5. Döngü Korumalı Hop-2 Standart/Norm Genişletmesi: Hop-1 parçalarından çıkan standard_codes (örn. EN 50122-1, IEC 60870-5-104) taranır; katalog dokümanları (doc_role='standart_norm_katalogu') hariç en çok 3 standart hedeflenerek yalnızca 1 ek hop ile ilgili teknik norm chunk'ları çekilir (özyineleme yasaktır).", bullet=True)
add_para("6. Kanıt Ağırlıklı Vaka Bağlamı (90k Sabit Bütçe): TUTANAK_ORTAK > RESMİ POZİSYON (İdare/Müşavir) > İDDİA (Yüklenici) ağırlığıyla kronolojik zincir uzman ve baş denetçi istemlerine eklenir.", bullet=True)


# ==============================================================================
# BÖLÜM 7: GÜNCEL VERİ ENVANTERİ VE SİSTEM METRİKLERİ
# ==============================================================================
add_header("7. GÜNCEL VERİ TABANI ENVANTERİ VE METRİKLER", level=1)

add_para(
    "2026 yılı disiplin bazlı global katman yapılandırması sonrasında ChromaDB koleksiyonundaki güncel durum:"
)

tbl_metrics = doc.add_table(rows=1, cols=3)
format_table(
    table=tbl_metrics,
    col_widths=[2.5, 1.8, 2.5],
    headers=["Kapsam / Proje Havuzu", "İşlenen Doküman Sayısı", "Vektör Parça Sayısı ve İzolasyon Durumu"],
    data=[
        [
            "1. Genel Mevzuat ve Standartlar\n(5 Ana Klasör + Sürüm Korumalı Resmi Tam Metinler)",
            "50 adet resmi doküman & katalog\n(4734, 4735 + Geçici 5/6/7, 4686, 6098, 6100, 5018, 6085, 6331, 4857, 2872, YİGŞ, Uygulama/Muayene-Kabul Yön., KİK Tebliği, 2013/5215-5216-5217 Fiyat Farkı, Yangın, Deprem/Tünel 34909, Mahalli İdareler Harcama, CENELEC/EN Normları)",
            "5.441 Vektör (4.203 ortak, 670 danismanlik, 568 yapim; 2.356 kanun, 2.299 yonetmelik, 692 teblig_ve_kararname). Otomatik sürüm kontrolü: utils/mevzuat_sync.py."
        ],
        [
            "2. İkitelli-Ataköy Metro Hattı (M9)\n(5 Sütun: Sözleşme, İdari, 10 Disiplin Teknik Şartname, Birim Fiyat, Zeyilname)",
            "15 adet normatif ihale dosyası\n(İmzalı Sözleşme + EKAP Tasarı + İdari + Zeyilname + Birim Fiyat + 10 Dijital Teknik Bölüm; test raporları _arsiv'de)",
            "1.910 Saf Normatif Vektör — İkitelli'ye izole (project_id='ikitelli_atakoy_metro', procurement_type='yapim'; 0 yazışma)."
        ],
        [
            "3. Kirazlı-Halkalı Metro Hattı\n(Sözleşme, İdari, 20 Disiplin/BIM Şartnamesi, Birim Fiyat)",
            "25 adet dosya\n(Tüm şartnameler + BIM ekleri; zeyilname bulunmuyor)",
            "3.747 Saf Normatif Vektör — Disiplin etiketleri güncel (%100 subsystem uyumlu, procurement_type='yapim')."
        ],
        [
            "4. İkitelli Ataköy Müşavirlik\n(Ham dosyalar yenilenene kadar veritabanından temizlendi)",
            "0 aktif vektör\n(Ham evraklar diskte bekletiliyor)",
            "0 Vektör (Eski sorunlu 254 vektör temizlendi; yeni ham dosyalar konunca yeniden indekslenecek)."
        ],
        [
            "5. Fiziksel Ayrı Yazışma DB\n(vector_db_yazismalar/ + data/project_graph.db)",
            "Temiz başlangıç (0 yüklenici yazısı)\nProje klasörleri hazır ve boş",
            "0 Yazışma Vektörü + 0 SQLite Kaydı (Sentetik test yazıları temizlendi; gerçek yazışmalar eklendikçe yalnızca bu DB'ye yazılır)."
        ],
        [
            "TOPLAM NORMATİF DB (vector_db/)",
            "90 Aktif Normatif Doküman\n(Katman 1 + Katman 2)",
            "11.098 Saf Normatif Chroma Vektörü (BGE-M3 1024-d, 0 yazışma sızıntısı) | Ayrı Yazışma DB: vector_db_yazismalar/ + project_graph.db"
        ]
    ]
)

add_header("Adım 5 Kapalı Döngü & 25 Gerçek İkitelli Yazısı Pilot Sonuçları (data/raporlar/pilot_eval_raporu.md)", level=2)
add_para("İkitelli-Ataköy TAHKİM arşivindeki 25 benzersiz gerçek süre uzatım/müşavir/idare yazısı (PDF, maks. <=20 sayfa, yalıtılmış test SQLite'ı) üzerinde yapılan doğrulanmış pilot ölçümleri:")
add_para("• Evrak Sayısı (doc_no) Çıkarım Tamlığı: 25/25 (%100.0) | Konu Çıkarım Tamlığı: 25/25 (%100.0)", bullet=True)
add_para("• Tarih (doc_date) Çıkarım Tamlığı: 18/25 (%72.0) — okunamayan/damgasız Olur tarihlerinde sistem uydurma yapmak yerine dürüstçe pending_review'a düşmektedir (Dosya adı tarih çapraz doğruluğu: 11/11; Sayı çapraz doğruluğu: 18/24).", bullet=True)
add_para("• İlgi Zinciri Çözümleme & Recall: Havuz içi 50/50 (%100.0) kenar hatırlama (14 kenar 2. tur OCR iskelet eşleştirmeyle bağlandı).", bullet=True)
add_para("• Karşılaştırmalı Bağlam Kalitesi (5678-yüklenici.pdf): Hafızasız eski mod 0 krk iken Vaka Hafızası 5 İlgi zincir belgesi + 17 ekstra cevap + 7 RESMİ POZİSYON + 6 İDDİA bloğunu 4.948 / 90.000 krk bütçe içinde sundu.", bullet=True)


# ==============================================================================
# BÖLÜM 8: GELİŞTİRİCİ VE YZ AJANI İÇİN KULLANIM KILAVUZU (OPERATOR CHEAT-SHEET)
# ==============================================================================
add_header("8. GELİŞTİRİCİ VE YZ İÇİN BAKIM VE KULLANIM REHBERİ", level=1)

add_para(
    "Sisteme yeni bir evrak eklendiğinde, yazışma arşivi beslendiğinde veya İdare cevabı kapatıldığında izlenecek operasyonel adımlar:"
)

add_header("Adım 1: Yeni Doküman Ekleme Kuralı", level=2)
add_para("• Genel bir kanun, genel şartname veya standart ise: data/1_genel_mevzuat_ve_standartlar/ altındaki ilgili klasöre koyun:", bullet=True)
add_para("  - Yapım genel şartnamesi/yönetmeliği -> 2_sozlesme_ve_genel_sartnameler/yapim_isleri/", bullet=False)
add_para("  - Danışmanlık/Müşavirlik mevzuatı -> 2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/", bullet=False)
add_para("  - Teknik standartlar -> 4_standart_normlar/<ilgili_disiplin_klasoru>/ (sinyalizasyon_ve_cbtc, cer_gucu_ve_elektrifikasyon vb.)", bullet=False)
add_para("• Yeni bir proje ise: data/2_proje_evraklari/<yeni_proje_kodu>/ klasörü açın (Müşavirlik işi ise klasör adında 'musavirlik' veya 'danismanlik' geçsin).", bullet=True)
add_para("• Yazışma arşivi (Katman 3) ise: data/3_yuklenici_talepleri/<proje_kodu>/ altında 1_yuklenici_yazilari/, 2_idare_cevaplari/, 3_tutanak_ve_toplantilar/, 4_hakedis_ozetleri/ klasörlerine ekleyin.", bullet=True)

add_header("Adım 2: Katman 1 Resmi Mevzuat Güncelleme Kontrolü ve Normatif Vektör İndeksleme (vector_db/)", level=2)
add_para("• Resmi kaynaklarda (mevzuat.gov.tr + ihale.gov.tr) değişiklik kontrolü (dosyaya dokunmaz):")
add_para(".\\venv\\Scripts\\python.exe -X utf8 scripts\\sync_mevzuat.py --check --deep", bold=True)
add_para("• Değişiklik varsa eski sürümü data/_arsiv/mevzuat_surumleri/ altına yedekleyip madde-fark raporuyla eşitleme ve Normatif ChromaDB güncelleme:")
add_para(".\\venv\\Scripts\\python.exe -X utf8 scripts\\sync_mevzuat.py --sync --ingest", bold=True)
add_para("• Artımlı Normatif Vektör Güncelleme (Yalnızca Katman 1 + Katman 2; yazışmalara ASLA dokunmaz):")
add_para(".\\venv\\Scripts\\python.exe -X utf8 1_ingest.py", bold=True)
add_para("• Tam Sıfırlama (Normatif koleksiyonu sıfırlayıp Katman 1+2'yi baştan temiz indeksler):")
add_para(".\\venv\\Scripts\\python.exe -X utf8 1_ingest.py --reset", bold=True)

add_header("Adım 3: Akıllı Karma Klasör Alıcısı, Uyuşmazlık Kümeleri ve Görsel Stüdyo", level=2)
add_para("• Karışık (Yüklenici/İdare/Müşavir/Tutanak) 400+ yazışmayı tek klasörden otomatik taraf tespitiyle SQLite + Ayrı Yazışma DB'ye alma (opsiyonel --organize orijinalleri silmeden taraf/yıl klasörlerine kopyalar):")
add_para(".\\venv\\Scripts\\python.exe -X utf8 ingest_history.py --project ikitelli_atakoy_metro --source-dir \"<klasor_yolu>\"", bold=True)
add_para("• Keşfedilen uyuşmazlık kümelerini (bağlı zincirler, cevapsız talepler, eksik İlgi belgeleri) 0-LLM matris (.docx) olarak çıkarma ve seçili kümede (ör. K01) toplu sözleşme denetimi çalıştırma:")
add_para(".\\venv\\Scripts\\python.exe -X utf8 scripts\\analyze_disputes.py --project ikitelli_atakoy_metro --export-docx", bold=True)
add_para(".\\venv\\Scripts\\python.exe -X utf8 scripts\\analyze_disputes.py --project ikitelli_atakoy_metro --cluster K01 --audit", bold=True)
add_para("• Eksik tarih/sayılı kartları insan onay kuyruğunda düzeltme (pending_review -> human_approved + otomatik İlgi bağlama):")
add_para(".\\venv\\Scripts\\python.exe -X utf8 scripts\\review_queue.py --project ikitelli_atakoy_metro", bold=True)
add_para("• İdare / Müşavir nihai cevabını sisteme geri işleyip ilgili talebi onaylı kapatma:")
add_para(".\\venv\\Scripts\\python.exe -X utf8 scripts\\close_loop_reply.py --project ikitelli_atakoy_metro --file <cevap_yolu> --reply-to <doc_no> --confirm-state Cevaplandi --yes --chroma", bold=True)
add_para("• Çoklu Ajan (6 Düğümlü) denetimini CLI'dan çalıştırma veya 400+ yazışma filtreli NiceGUI Görsel Stüdyoyu açma:")
add_para(".\\venv\\Scripts\\python.exe -X utf8 2_agents_graph.py \"<evrak_yolu>\" --project ikitelli_atakoy_metro", bold=True)
add_para(".\\venv\\Scripts\\python.exe -X utf8 ui_app.py", bold=True)

add_header("Adım 4: Güvenlik ve Bütünlük Kuralları (Asla Çiğnenmeyecekler)", level=2)
add_callout(
    "1. FİZİKSEL ÇİFT VEKTÖR DB AYRIMI: vector_db/ (insaat_mevzuat) %100 saf bağlayıcı kural/şartname havuzudur; yüklenici yazışmaları YALNIZCA vector_db_yazismalar/ (proje_yazismalari) + data/project_graph.db'ye yazılır.\n"
    "2. DATE_ORDER='DMY' KURALI: dateparser çağrılarında DMY zorunludur; Türkçe tarihlerin gün/ay takası sessiz kronoloji bozulması yaratır.\n"
    "3. ONAY OLMADAN DURUM KAPATMA YASAĞI: project_db.update_state() yalnızca confirmed_by_human=True ve geçerli state geçişleriyle uygulanır.\n"
    "4. KELİME SINIRLARI VE SAYFA ETİKETLERİ: '## --- Sayfa X ---' başlıklarını korumaya devam edin; verifier ve char_interval buna bağımlıdır.\n"
    "5. PYTHON ÇALIŞTIRMA KURALI: Komutları daima '.\\venv\\Scripts\\python.exe -X utf8' ile çalıştırın.",
    prefix="TEMEL MİMARİ İLKELER:",
    color_hex="BA181B"
)

# Çıktı dosyasını kaydet
output_path = Path(r"d:\mevzuatinceleme\SISTEM_MIMARISI_VE_CALISMA_REHBERI.docx")
doc.save(str(output_path))
print(f"Başarıyla oluşturuldu: {output_path} ({output_path.stat().st_size} bayt)")
