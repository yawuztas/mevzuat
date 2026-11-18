# -*- coding: utf-8 -*-
"""
Metro Projeleri Elektrik, Elektronik, Topraklama ve Zayıf Akım DWG İnceleme ve Hesap Kılavuzu
Yapay Zeka Otomasyonu İçin Teknik Şartname, Mühendislik Hesapları ve Kural Motoru Rehberi

Tam Kapsamlı Mühendislik ve Yapay Zeka Denetim Dokümanı
"""

import os
import sys
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

def create_guide_document():
    doc = docx.Document()

    # Sayfa Kenar Boşlukları (Standart Kurumsal Rapor Düzeni)
    for s in doc.sections:
        s.top_margin = Inches(0.7)
        s.bottom_margin = Inches(0.7)
        s.left_margin = Inches(0.7)
        s.right_margin = Inches(0.7)

    # Renk Paleti (Metro Elektromekanik Kurumsal Tasarım)
    COLOR_PRIMARY = RGBColor(16, 44, 87)       # Koyu Lacivert (Deep Navy)
    COLOR_SECONDARY = RGBColor(26, 82, 118)   # Çelik Mavisi (Steel Blue)
    COLOR_ACCENT = RGBColor(186, 24, 27)       # Güvenlik Kırmızısı (Alert/Fire)
    COLOR_DARK = RGBColor(33, 37, 41)          # Koyu Antrasit (Gövde Metni)
    COLOR_MUTED = RGBColor(108, 117, 125)      # Gri (Açıklama / Metadata)
    COLOR_GREEN = RGBColor(25, 135, 84)        # Onay Yeşili (Success)
    COLOR_WARNING = RGBColor(180, 83, 9)       # Uyarı Turuncusu (Warning)
    
    COLOR_BG_LIGHT = "F8F9FA"                  # Açık Gri Satır Dolgusu
    COLOR_BG_HEADER = "EAECEE"                 # Başlık Arka Planı
    COLOR_BG_CALLOUT = "F0F4F8"                # Callout Kutusu Arka Planı
    COLOR_BG_ALERT = "FDF2E9"                  # Uyarı Kutusu Arka Planı
    COLOR_BG_SUCCESS = "E8F8F5"                # Başarı Kutusu Arka Planı
    COLOR_BG_CODE = "F4F6F7"                   # Kod Bloğu Arka Planı

    # Yardımcı Fonksiyonlar
    def set_cell_background(cell, fill_hex):
        tcPr = cell._element.get_or_add_tcPr()
        shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
        tcPr.append(shd)

    def set_cell_margins(cell, top=90, bottom=90, left=120, right=120):
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
            run.font.size = Pt(14)
            run.font.color.rgb = COLOR_PRIMARY
            h.paragraph_format.space_before = Pt(14)
            h.paragraph_format.space_after = Pt(3)
            h.paragraph_format.keep_with_next = True
        elif level == 2:
            run.font.size = Pt(11.5)
            run.font.color.rgb = COLOR_SECONDARY
            h.paragraph_format.space_before = Pt(10)
            h.paragraph_format.space_after = Pt(2)
            h.paragraph_format.keep_with_next = True
        elif level == 3:
            run.font.size = Pt(10)
            run.font.color.rgb = COLOR_ACCENT
            h.paragraph_format.space_before = Pt(7)
            h.paragraph_format.space_after = Pt(2)
            h.paragraph_format.keep_with_next = True
        return h

    def add_para(text, bold=False, italic=False, bullet=False, space_after=2.5):
        p = doc.add_paragraph(style='List Bullet' if bullet else 'Normal')
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(text)
        run.font.name = 'Calibri'
        run.font.size = Pt(9.5)
        run.bold = bold
        run.italic = italic
        run.font.color.rgb = COLOR_DARK
        return p

    def add_callout(text, prefix="YAPAY ZEKA DENETİM KRİTERİ:", border_color="102C57", bg_color=COLOR_BG_CALLOUT):
        tbl = doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        tbl.columns[0].width = Inches(7.1)
        cell = tbl.cell(0, 0)
        set_cell_background(cell, bg_color)
        set_cell_margins(cell, top=90, bottom=90, left=140, right=140)
        
        tcPr = cell._element.get_or_add_tcPr()
        borders = parse_xml(
            f'<w:tcBorders {nsdecls("w")}>'
            f'<w:left w:val="single" w:sz="36" w:space="0" w:color="{border_color}"/>'
            f'<w:top w:val="none"/>'
            f'<w:right w:val="none"/>'
            f'<w:bottom w:val="none"/>'
            f'</w:tcBorders>'
        )
        tcPr.append(borders)
        
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing = 1.15
        r1 = p.add_run(prefix + " ")
        r1.bold = True
        r1.font.name = 'Calibri'
        r1.font.size = Pt(9)
        if border_color == "BA181B":
            r1.font.color.rgb = COLOR_ACCENT
        elif border_color == "198754":
            r1.font.color.rgb = COLOR_GREEN
        elif border_color == "B45309":
            r1.font.color.rgb = COLOR_WARNING
        else:
            r1.font.color.rgb = COLOR_PRIMARY
        
        r2 = p.add_run(text)
        r2.font.name = 'Calibri'
        r2.font.size = Pt(9)
        r2.font.color.rgb = COLOR_DARK
        
        p_spacer = doc.add_paragraph()
        p_spacer.paragraph_format.space_before = Pt(0)
        p_spacer.paragraph_format.space_after = Pt(2)

    def add_code_block(code_text):
        tbl = doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        tbl.columns[0].width = Inches(7.1)
        cell = tbl.cell(0, 0)
        set_cell_background(cell, COLOR_BG_CODE)
        set_cell_margins(cell, top=70, bottom=70, left=110, right=110)
        
        tcPr = cell._element.get_or_add_tcPr()
        borders = parse_xml(
            f'<w:tcBorders {nsdecls("w")}>'
            f'<w:left w:val="single" w:sz="18" w:space="0" w:color="BDC3C7"/>'
            f'<w:top w:val="single" w:sz="6" w:space="0" w:color="E5E7E9"/>'
            f'<w:right w:val="single" w:sz="6" w:space="0" w:color="E5E7E9"/>'
            f'<w:bottom w:val="single" w:sz="6" w:space="0" w:color="E5E7E9"/>'
            f'</w:tcBorders>'
        )
        tcPr.append(borders)
        
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing = 1.05
        r = p.add_run(code_text)
        r.font.name = 'Consolas'
        r.font.size = Pt(8)
        r.font.color.rgb = COLOR_SECONDARY
        
        p_spacer = doc.add_paragraph()
        p_spacer.paragraph_format.space_before = Pt(0)
        p_spacer.paragraph_format.space_after = Pt(2)

    def format_table(table, col_widths, headers, data, alignments=None):
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        
        # Başlık Satırı
        hdr_cells = table.rows[0].cells
        for i, title in enumerate(headers):
            hdr_cells[i].width = Inches(col_widths[i])
            set_cell_background(hdr_cells[i], COLOR_BG_HEADER)
            set_cell_margins(hdr_cells[i], top=70, bottom=70, left=90, right=90)
            p = hdr_cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing = 1.1
            if alignments:
                p.alignment = alignments[i]
            run = p.add_run(title)
            run.bold = True
            run.font.name = 'Calibri'
            run.font.size = Pt(8.5)
            run.font.color.rgb = COLOR_PRIMARY

        # Veri Satırları
        for r_idx, row_data in enumerate(data):
            row_cells = table.add_row().cells
            bg_color = COLOR_BG_LIGHT if r_idx % 2 == 1 else "FFFFFF"
            for c_idx, val in enumerate(row_data):
                row_cells[c_idx].width = Inches(col_widths[c_idx])
                set_cell_background(row_cells[c_idx], bg_color)
                set_cell_margins(row_cells[c_idx], top=55, bottom=55, left=90, right=90)
                p = row_cells[c_idx].paragraphs[0]
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.line_spacing = 1.05
                if alignments:
                    p.alignment = alignments[c_idx]
                run = p.add_run(str(val))
                run.font.name = 'Calibri'
                run.font.size = Pt(8)
                run.font.color.rgb = COLOR_DARK

        p_spacer = doc.add_paragraph()
        p_spacer.paragraph_format.space_before = Pt(0)
        p_spacer.paragraph_format.space_after = Pt(2)

    # ==============================================================================
    # BAŞLIK VE KAPAK BÖLÜMÜ
    # ==============================================================================
    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_before = Pt(8)
    p_meta.paragraph_format.space_after = Pt(2)
    p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_meta = p_meta.add_run("RAYLI SİSTEM PROJELERİ YAPAY ZEKA OTOMATİK DWG/CAD DENETİM MOTORU")
    r_meta.font.name = 'Calibri'
    r_meta.font.size = Pt(10.5)
    r_meta.font.color.rgb = COLOR_SECONDARY
    r_meta.bold = True

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(2)
    p_title.paragraph_format.space_after = Pt(4)
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_title = p_title.add_run("METRO PROJELERİ ELEKTRİK, ELEKTRONİK, TOPRAKLAMA VE SCADA\nDWG İNCELEME, HESAP VE KURAL MOTORU KILAVUZU")
    r_title.font.name = 'Calibri'
    r_title.font.size = Pt(16)
    r_title.font.color.rgb = COLOR_PRIMARY
    r_title.bold = True

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(12)
    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_sub = p_sub.add_run("İkitelli - Ataköy Metro Hattı Teknik Şartnameleri, EN 50122, EN 50163, EN 54, IEC 60909 ve NFPA 130 Standartları Uyarınca Hazırlanmıştır")
    r_sub.font.name = 'Calibri'
    r_sub.font.size = Pt(9)
    r_sub.italic = True
    r_sub.font.color.rgb = COLOR_MUTED

    # Özet / Giriş Kutusu
    add_callout(
        "Bu kılavuz; Yapay Zeka (AI) CAD/DWG Analiz Motoru'nun bir metro projesine ait Elektrik Kuvvetli Akım, Cer Gücü (Traction Power), "
        "Topraklama / Eşpotansiyel Kuşaklama, DC Kaçak Akım (Stray Current) Korozyon Önleme, Zayıf Akım Sistemleri (Yangın Algılama, "
        "CCTV, Acil Anons, Kartlı Geçiş) ve SCADA / ECS mimarilerini pafta bazında denetlerken kullanacağı teknik hesap kriterlerini, "
        "şartname limitlerini, katman (layer) filtrelerini ve deterministik kural motoru (rule engine) algoritmalarını eksiksiz olarak ortaya koymaktadır.",
        prefix="KILAVUZUN AMACI VE KULLANIM ALANI:",
        border_color="102C57"
    )

    # ==============================================================================
    # BÖLÜM 1: GENEL METRO ELEKTROMEKANİK MİMARİSİ VE CAD/DWG STANDARTLARI
    # ==============================================================================
    add_header("BÖLÜM 1: GENEL METRO ELEKTROMEKANİK MİMARİSİ VE CAD/DWG STANDARTLARI", level=1)
    
    add_para(
        "Metro projeleri, klasik bina ve endüstriyel tesis projelerinden radikal biçimde ayrışır. Yüksek yolcu sirkülasyonu, "
        "yer altında acil tahliye güçlükleri, 1500V DC cer gücü geri dönüş akımının oluşturduğu şiddetli elektrokimyasal korozyon riski "
        "ve yüksek seviyede entegre can güvenliği (Life Safety) mimarisi nedeniyle DWG çizimlerinin AI tarafından denetimi "
        "katı kurallara, belirli katman (layer) disiplinine ve akıllı blok (attribute) yapılarına dayanmalıdır."
    )

    add_header("1.1. Pafta Hiyerarşisi, Kodlama Sistemi ve Disiplin Ayrımı", level=2)
    add_para(
        "Yapay zeka analiz motoru, gelen paftayı adlandırma ve antet (title block) bilgilerine göre otomatik olarak sınıflandırmalıdır. "
        "İkitelli-Ataköy şartnamesi (Bölüm A.1.32 ve A.2.2) gereğince pafta kodlama formatı şu şekilde denetlenmelidir:"
    )
    
    headers_1_1 = ["Disiplin Kodu", "Disiplin Tanımı", "Pafta Türü / Kapsamı", "AI İnceleme ve Doğrulama Odağı"]
    data_1_1 = [
        ["E-HV / E-OG", "Yüksek Gerilim / Cer Gücü", "34.5 kV Ring, Cer Trafoları, 1500V DC Doğrultucular", "N-1 güvenliği, kuplaj kilitleri, 12-pulse doğrultucu, DC kesici polaritesi"],
        ["E-LV / E-AG", "Alçak Gerilim Dağıtım", "İç İhtiyaç Trafoları (34.5/0.4kV), AG Dağıtım, MCC", "Yük cetveli, faz dengesi (<%10), şalter-kesit uyumu, Form-4b pano yapısı"],
        ["E-GEN / E-UPS", "Acil Durum Enerji", "Dizel Jeneratör, UPS, Akü Odaları, Transfer Panoları", "Yangın/acil yük kapsama, motor demarajı gerilim düşümü (<%15), 120-180 dk akü otonomisi"],
        ["E-EAR / E-TOP", "Topraklama & Kaçak Akım", "TN-S topraklama, MEB/EEB baraları, Stray Current hasırı", "R < 1.0 Ohm, ray yalıtımı (floating return), VLD cihazı, 200m test kutuları"],
        ["EL-FAS / YNG", "Yangın Algılama & Alarm", "Detektör, Buton, Flaşör/Siren, Giriş/Çıkış Modülleri", "EN 54 kapsama yarıçapı, asma tavan çift kat, Cause & Effect senaryosu, FE180 kablo"],
        ["EL-CCTV / KDTS", "Kamera Güvenlik Sistemi", "Peron, DCO, Turnike, Merdiven, Teknik Hacim Kameraları", "Kör nokta denetimi, DORI çözünürlük kriteri (250 px/m), 30 gün depolama"],
        ["EL-PAVA / ACS", "Acil Anons / Kartlı Geçiş", "EN 54-16/24 hoparlörler, kart okuyucular, acil çıkışlar", "STI >= 0.50 anlaşılabilirlik, A/B çapraz hat besleme, fail-safe kilit açma"],
        ["SCADA / ECS", "Süpervizör Kontrol & İzleme", "RTU/PLC panoları, optik ring mimarisi, I/O şematiği", "DWG'deki motor/şalterlerin SCADA I/O listesi ile 1:1 birebir eşleşmesi"]
    ]
    tbl_1_1 = doc.add_table(rows=1, cols=4)
    format_table(tbl_1_1, [1.1, 1.4, 2.4, 2.2], headers_1_1, data_1_1)

    add_header("1.2. DWG Katman (Layer) Yapısı, Standart Adlandırma ve Varlık Tipleri", level=2)
    add_para(
        "AI motoru, paftadaki çizgi ve sembolleri analiz ederken aşağıdaki katman isimlendirme standartlarını aramalıdır. "
        "Farklı disiplinlere ait kablo ve ekipmanların aynı layer üzerinde çizilmesi durumunda yapay zeka 'Layer Kural İhlali' uyarısı üretmelidir:"
    )
    
    headers_1_2 = ["Standart Katman Adı", "Çizim Elemanı / Obje Tipi", "Beklenen Çizgi Tipi / Renk", "Zorunlu Öznitelikler (Attributes)"]
    data_1_2 = [
        ["E-HV-CABL-34KV", "Polyline / LWPolyline", "Continuous / Kırmızı (Red - Color 10)", "Kablo kesiti (örn: 3x1x240/25 mm2 Cu), gerilim sınıfı"],
        ["E-LV-POWR-CABL", "Polyline / LWPolyline", "Continuous / Sarı/Yeşil/Mavi", "Kablo tipi (N2XH 0.6/1kV), metraj, pano başlangıç/bitiş etiketi"],
        ["E-EAR-MESH-COND", "Polyline (Topraklama)", "Dashed / Yeşil (Green - Color 3)", "İletken tipi (95 mm2 Cu / 30x3.5 mm galvaniz şerit), kot"],
        ["E-STRAY-CURR-BOX", "Block Reference", "Noktasal Sembol / Magenta (Color 6)", "Test kutusu ID (örn: SC-JB-200M), tünel kilometre zinciri"],
        ["EL-FAS-DETC-SMOK", "Block Reference", "Sembol / Kırmızı (EN 54 Standart)", "Loop ID, Dedektör No, Montaj Kotu, Asma Tavan İçi/Altı Bilgisi"],
        ["EL-CCTV-CAMR-INDR", "Block Reference + Arc", "Kamera + Görüş Açısı (FOV)", "Kamera ID, Çözünürlük, Lens Açısı, DORI Kapsama Alanı"],
        ["EL-PAVA-SPKR-CEIL", "Block Reference", "Sembol / Turuncu (Color 30)", "Hoparlör gücü (6W/12W), A/B zon kanalı, dBA ses seviyesi"],
        ["SCADA-RTU-PANEL", "Block Reference", "Dikdörtgen Çerçeve / Cyan", "RTU ID, Rack No, Dijital/Analog I/O Kapasitesi, IP Adresi"]
    ]
    tbl_1_2 = doc.add_table(rows=1, cols=4)
    format_table(tbl_1_2, [1.5, 1.5, 1.6, 2.5], headers_1_2, data_1_2)

    # ==============================================================================
    # BÖLÜM 2: ELEKTRİK KUVVETLİ AKIM VE CER GÜCÜ PROJELERİNDE OLMASI GEREKEN HESAPLAR
    # ==============================================================================
    add_header("BÖLÜM 2: ELEKTRİK KUVVETLİ AKIM VE CER GÜCÜ PROJELERİNDE OLMASI GEREKEN HESAPLAR VE DWG İNCELEME KRİTERLERİ", level=1)
    
    add_para(
        "Metro elektrik altyapısı Cer Gücü (Traction Power Supply) ve İstasyon İç İhtiyaç (Auxiliary Power Supply) "
        "olmak üzere iki ana eksenden oluşur. DWG çizimlerinde yer alan tek hat şemaları, yük cetvelleri ve yerleşim planları "
        "aşağıda belirtilen kesin hesap değerleriyle tam uyumlu olmalıdır."
    )

    add_header("2.1. Cer Gücü Sistemi (Traction Power) ve 1500 V DC Doğrultucu Hesapları", level=2)
    add_para(
        "İkitelli - Ataköy Metro şartnamesi (Madde 02.2 - Cer Gücü Sistemi) ve EN 50163 uyarınca cer gücü parametreleri şunlardır:"
    )
    add_para("Cer Gerilimi ve Besleme Tipi: Nominal 1500 V DC, rijit veya esnek katener / 3. ray sistemi ile EN 50163 standardına tam uyum.", bullet=True)
    add_para("İzin Verilen Gerilim Limitleri: Minimum gerilim 1000 V DC, Nominal gerilim 1500 V DC, Maksimum sürekli gerilim 1800 V DC, Tepe (kısa süreli aşırı) gerilim 1950 V DC. Yapay zeka gerilim düşümü hesaplarında bu limitlerin dışına çıkan hatları hatalı işaretlemelidir.", bullet=True)
    add_para("Cer Trafoları ve Doğrultucular: 34.5 kV primer, çift sekonderli (2 x 1.2 kV AC), dökme reçineli kuru tip, 12-darbeli (12-pulse) silikon doğrultucu üniteleri.", bullet=True)
    add_para("Harmonik Sınırlamaları: IEEE 519 ve IEC 61000-2-4 uyarınca 34.5 kV şebekede THD (Toplam Harmonik Distorsiyon) gerilim için %3'ü, akım için %5'i kesinlikle geçmemelidir.", bullet=True)
    add_para("N-1 Yedeklilik Kriteri: Bir cer trafo-doğrultucu grubu devre dışı kaldığında (N-1 arıza modu), komşu cer trafo merkezleri pik saat sefer aralığındaki (headway) tren trafiğini aksatmadan karşılayacak aşırı yükleme kapasitesine (IEC 60146 Class VI - 2 saat boyunca %150 yüklenme) sahip olmalıdır.", bullet=True)

    add_callout(
        "AI DWG Doğrulama Kuralı (CER-01): Cer trafo merkezi tek hat paftalarında (E-HV-SLD) cer trafosunun çift sekonder sargısı "
        "(yıldız-üçgen / Yd11-Yy0) ile 12 darbeli doğrultucu köprüsü gösterilmiş mi? DC kesicilerde (HSCB - High Speed Circuit Breaker) "
        "ters akım (reverse current) ve transfer açtırma kilidi şematize edilmiş mi? Bu donanımlar yoksa 'Kritik Proje Hatası' olarak raporlanmalıdır.",
        prefix="CER GÜCÜ TEK HAT DENETİMİ:",
        border_color="BA181B",
        bg_color=COLOR_BG_ALERT
    )

    add_header("2.2. İstasyon İç İhtiyaç Dağıtımı ve Trafo Boyutlandırma", level=2)
    add_para(
        "İstasyonların aydınlatma, mekanik havalandırma (tünel ve istasyon fanları), yürüyen merdiven, asansör, yangın pompaları ve "
        "zayıf akım sistemlerini besleyen 34.5/0.4 kV dökme reçineli kuru tip iç ihtiyaç trafoları için hesap kriterleri:"
    )
    
    headers_2_2 = ["İstasyon Boyutu / Yük Tipi", "Asgari Trafo Sayısı ve Gücü", "Yedeklilik (Redundancy)", "AG Pano Form Yapısı (IEC 61439)"]
    data_2_2 = [
        ["Standart Tip İstasyon", "2 x 1000 kVA (veya 2 x 1250 kVA)", "%100 N-1 Yedekli (Her biri tüm yükü taşır)", "Form-4b (Çekmeceli tip fonksiyonel üniteler)"],
        ["Aktarma İstasyonu (Transfer Hub)", "2 x 1600 kVA (veya 2 x 2000 kVA)", "%100 N-1 Yedekli + Kuplaj Otomasyonu", "Form-4b (Bağımsız bara ve ayırıcı perdeler)"],
        ["Tünel Havalandırma Şaftı / Kaçış", "2 x 800 kVA veya 2 x 1000 kVA", "N-1 Yedekli (Acil duman tahliye fanları)", "Form-3b veya Form-4b"],
        ["Depo Sahası ve Atölye Binası", "2 x 2500 kVA + 1 x 1600 kVA", "Kritik atölye yükleri için N-1", "Form-4b (Büyük motor yol vericiler)"]
    ]
    tbl_2_2 = doc.add_table(rows=1, cols=4)
    format_table(tbl_2_2, [1.6, 1.8, 1.8, 1.9], headers_2_2, data_2_2)

    add_header("2.3. Yük Dağılımı, Yük Sınıflandırması ve Faz Dengesi Tahkiki", level=2)
    add_para(
        "DWG paftasında yer alan AG Ana Dağıtım Panosu (AGADP) yük cetveli yapay zeka tarafından satır satır taranmalı ve "
        "yükler üç ana kategoriye ayrılmalıdır:"
    )
    add_para("1. Normal Yükler (Non-Essential): Konfor aydınlatması, prizler, idari ofis klimaları, ticari alanlar. Şebeke kesintisinde devreden çıkar.", bullet=True)
    add_para("2. Zorunlu / Hayati Yükler (Essential): İstasyon emniyet aydınlatması (%30-50), drenaj pompaları, sinyalizasyon/haberleşme klimaları, bilet otomasyonu, yolcu bilgilendirme. Jeneratör tarafından beslenir.", bullet=True)
    add_para("3. Yangın ve Acil Durum Yükleri (Fire / Life Safety): Tünel ve istasyon duman tahliye fanları, basınçlandırma fanları, yangın pompaları, yangın asansörleri, acil anons, kaçış yönlendirme aydınlatması. Kesintisiz jeneratör ve yangına dayanıklı kablolarla beslenir.", bullet=True)

    add_callout(
        "AI Yük Dengesi Algoritması: AG Dağıtım Panosu yük cetvelinde R (L1), S (L2), T (L3) fazları arasındaki toplam yük dağılımı "
        "taranmalıdır. Fazlar arası dengesizlik oranı formülü: % Dengesizlik = [(Maksimum Faz Yükü - Ortalama Faz Yükü) / Ortalama Faz Yükü] x 100. "
        "Bu değer %10'u aşıyorsa yapay zeka 'Faz Dengesizliği Hatası' uyarısı vermeli ve fazlar arası yük transferi önermelidir.",
        prefix="YÜK DAĞILIMI VE FAZ DENGESİ TAHKİKİ:",
        border_color="B45309",
        bg_color=COLOR_BG_ALERT
    )

    add_header("2.4. Dizel Jeneratör ve UPS (Kesintisiz Güç Kaynağı) Hesapları", level=2)
    add_para(
        "Metro sistemlerinde enerji kesintisi veya yangın anında insan tahliyesini sağlamak üzere jeneratör ve UPS boyutlandırma kriterleri:"
    )
    add_para("Dizel Jeneratör Kapasitesi: İstasyonun tüm zorunlu (essential) ve yangın (life-safety) yüklerini aynı anda karşılayacak güçte seçilmelidir. Tünel fanlarının (örneğin 2x150 kW) doğrudan veya yumuşak yol vericiyle (soft-starter / VFD) devreye girmesi sırasındaki demaraj akımı (inrush current) hesaplanmalı, jeneratör klemenslerindeki gerilim düşümü %15'i aşmamalıdır. Yakıt tankı kapasitesi en az 24 saat kesintisiz tam yük çalışmaya uygun olmalıdır.", bullet=True)
    add_para("UPS Sistemi Boyutlandırması: Sinyalizasyon (CBTC), Telsiz/Haberleşme (TETRA), SCADA/ECS, Yangın Algılama Panelleri, Acil Anons (PA/VA), CCTV kritik kameraları ve Acil Kaçış Aydınlatması için bağımsız UPS üniteleri öngörülmelidir.", bullet=True)
    add_para("UPS Otonomi Süresi (Akü Besleme Süresi): İkitelli-Ataköy şartnamesine göre kritik zayıf akım, sinyalizasyon ve acil durum sistemleri için aküden besleme süresi EN AZ 120 DAKİKA (2 SAAT) - bazı kritik aktarma istasyonlarında 180 DAKİKA olmalıdır. Statik by-pass ve bakım by-pass şalterleri DWG şematiğinde açıkça gösterilmelidir.", bullet=True)

    add_header("2.5. Kablo Kesit, Akım Taşıma, Gerilim Düşümü ve Kısa Devre Hesapları", level=2)
    add_para(
        "DWG'de belirtilen her kablo için yapay zeka şu 4 aşamalı mühendislik doğrulamasını gerçekleştirmelidir:"
    )
    add_para("Aşama 1: Akım Taşıma Kapasitesi (Iz >= Ib): Kablonun nominal akımı (Ib), ortam sıcaklığı düzeltme katsayısı (kt: 40°C tünel/istasyon için 0.91), yan yana döşeme katsayısı (kg) ile çarpılarak indirgenmiş akım taşıma kapasitesinden (Iz) küçük olmalıdır.", bullet=True)
    add_para("Aşama 2: Şalter Eşleşmesi (Ib <= In <= Iz): Kabloyu koruyan termik-manyetik veya kompakt şalter nominal akımı (In), yük akımından büyük veya eşit, kablonun akım taşıma kapasitesinden küçük veya eşit olmalıdır.", bullet=True)
    add_para("Aşama 3: Gerilim Düşümü Limiti (%e): Formül: Trifaze için %e = (100 x P x L) / (k x S x U^2). Aydınlatma linyelerinde azami %3, motor besleme hatlarında azami %5, motor demarajı anında azami %15. Bu oranları aşan kablo kesitleri için AI 'Kesit Büyütme Zorunluluğu' bayrağı açmalıdır.", bullet=True)
    add_para("Aşama 4: Kısa Devre Dayanımı (IEC 60909): Kablonun termik kısa devre dayanımı t süresinde kablo izin verilen sınır sıcaklığını aşmamalıdır: S >= (Ik x sqrt(t)) / k_termik. 34.5 kV hücreler min 25 kA / 1 sn (veya 31.5 kA), AG panolar min 50 kA / 1 sn kısa devre değerine sahip olmalıdır.", bullet=True)

    add_header("2.6. Kablo Tavaları, Yangın Dayanımı ve Doluluk Oranları", level=2)
    add_para("Kablo Tava Doluluk Oranı: Yangın tahliyesi ve ısınma önleme amacıyla kablo tavalarında doluluk oranı azami %60 olmalı (%40 net genişleme rezervi bırakılmalıdır). DWG kesitlerinde kablo katman kalınlığı tava yüksekliğinin yarısını geçmemelidir.", bullet=True)
    add_para("Kablo Tava Ayrımı: Kuvvetli akım kabloları (AG) ile Zayıf Akım / Haberleşme kablo tavaları arasında en az 30 cm; OG kabloları ile AG tavaları arasında en az 50 cm fiziksel ayırma mesafesi bulunmalıdır.", bullet=True)
    add_para("Yangına Dayanıklılık Standartları: Acil aydınlatma, duman egzoz fanları, acil anons ve yangın algılama kabloları TS EN 50200 / DIN 4102-12 normuna göre en az PH120 / E90 (alev altında 120/90 dakika işlevsellik) standardında olmalıdır.", bullet=True)

    # ==============================================================================
    # BÖLÜM 3: TOPRAKLAMA, EŞPOTANSİYEL KUŞAKLAMA VE KAÇAK AKIM / KOROZYON KONTROLÜ
    # ==============================================================================
    add_header("BÖLÜM 3: TOPRAKLAMA, EŞPOTANSİYEL KUŞAKLAMA VE KAÇAK AKIM / KOROZYON KONTROLÜ", level=1)
    
    add_para(
        "Metro projelerinde topraklama tasarımı, klasik binalardan radikal bir şekilde ayrılır. "
        "Bunun temel sebebi, rayların 1500 V DC cer akımı için negatif geri dönüş iletkeni olarak kullanılması ve "
        "toprağa sızabilecek kaçak akımların (stray currents) tünel donatılarında, su borularında ve metalik yapılarda "
        "şiddetli elektrokimyasal korozyona (delinmeye) yol açması tehlikesidir (EN 50122-2)."
    )

    add_header("3.1. Topraklama Sistemi Tipi ve Eşpotansiyel Kuşaklama Kuralları", level=2)
    add_para(
        "İkitelli - Ataköy şartnamesi ve uluslararası metro normlarına göre topraklama kuralları:"
    )
    add_para("Topraklama Şebeke Tipi: Tüm istasyon alçak gerilim sistemi KESİNLİKLE TN-S SİSTEMİ (Nötr ve Koruma Topraklaması PE iletkenleri trafo çıkışından itibaren tamamen ayrık) olarak projelendirilmelidir. Nötr ve toprak iletkenlerinin panolarda birleştirilmesi kesinlikle YASAKTIR.", bullet=True)
    add_para("Topraklama Direnci Kriteri: İstasyon temel topraklaması ve tünel topraklama ağının eşdeğer direnci R <= 1.0 Ohm (mümkünse R <= 0.5 Ohm) olmalıdır. Çizimlerde topraklama elektrotları (bakır kaplı çelik çubuklar min 20mm çap, 3.5m boy) ve 95-120 mm2 çıplak bakır örgülü iletken ağı gösterilmelidir.", bullet=True)
    add_para("Ana Eşpotansiyel Baralar (MEB): İstasyon peron altı kablo galerisinde, istasyonun her iki başında en az 2 ADET Ana Eşpotansiyel Bara (MEB - Main Earthing Bar) bulunmalı ve bunlar çift hat 120 mm2 çıplak bakır ile birbirine bağlanmalıdır.", bullet=True)
    add_para("Teknik Hacim Tali Eşpotansiyel Baraları (EEB): OG Dağıtım Odası, Cer Trafo Odası, AG Pano Odası, Jeneratör Odası, Sinyalizasyon (CER) Odası, Haberleşme (TER) Odası ve SCADA Odasında bağımsız Eşpotansiyel Baralar (EEB) yer almalı ve sarı-yeşil yalıtımlı NYA kablolarla ana baraya yıldız topolojide bağlanmalıdır.", bullet=True)

    add_header("3.2. DC Kaçak Akım (Stray Current) İzolasyonu ve Floating Return Prensibi", level=2)
    add_para(
        "EN 50122-2 standardı gereğince cer gücü dönüş akımını taşıyan raylar topraktan tamamen izole edilmelidir ('Floating Return - Yüzen Ray Sistemi'). "
        "Yapay zeka DWG çizimlerinde aşağıdaki hayati unsurları denetlemelidir:"
    )
    
    headers_3_2 = ["İncelenecek Sistem Elemanı", "DWG'de Aranacak Teknik Detay", "Hatalı Tasarım Durumu (Kırmızı Bayrak)", "Standart Referansı"]
    data_3_2 = [
        ["Ray Altı İzolasyon Pedi", "Ray tespit sepeti altında elastomer / poliüretan yalıtım pedi", "Rayın doğrudan betonarme döşemeye temas etmesi", "EN 50122-2 Madde 5"],
        ["Ray-Toprak Bağlantısı", "Rayların hiçbir noktada istasyon topraklamasına doğrudan bağlanmaması", "Rayın MEB barasına veya bina toprağına doğrudan irtibatı (FACİA)", "EN 50122-2 / NFPA 130"],
        ["VLD (Ray Potansiyel Sınırlayıcı)", "Ray ile toprak arasına çift yönlü tristörlü / kontaktörlü VLD-F/O konulması", "VLD ünitesinin çizilmemiş olması veya korumasız kısa devre", "EN 50122-1 Madde 6"],
        ["Tünel Kaçak Akım Hasırı", "Ray altı betonu içinde kesintisiz kaynaklı hasır donatı (Collector Mesh)", "Hasır donatının tünel yapısal çeliğine kaynaklanması", "EN 50122-2 Madde 7"],
        ["Kaçak Akım Test Terminalleri", "Her 200 metrede bir tünel duvarında ölçüm/test terminal kutusu (Block-out)", "200m test kutularının yerleşim planında gösterilmemesi", "İkitelli-Ataköy Şart. 02.4"]
    ]
    tbl_3_2 = doc.add_table(rows=1, cols=4)
    format_table(tbl_3_2, [1.5, 2.1, 2.1, 1.4], headers_3_2, data_3_2)

    add_callout(
        "HAYATİ EMNİYET VE KOROZYON KURALI (EAR-01): Raylar ile yapısal topraklama şebekesi (MEB/PE) kesinlikle doğrudan birleştirilemez! "
        "Yolcu güvenliği için dokunma gerilimi tehlikeli sınıra (EN 50122-1 uyarınca >120V DC) ulaştığında rayı anlık olarak topraklayan "
        "ancak arıza geçince devreyi tekrar açan VLD (Voltage Limiting Device) panosu çizimlerde yer almalıdır. "
        "DWG'de rayın toprağa doğrudan bağlı çizildiği tespit edilirse AI en yüksek öncelikli 'DURDURUCU TASARIM HATASI' üretmelidir.",
        prefix="DC KAÇAK AKIM VE RAY YALITIM DENETİMİ:",
        border_color="BA181B",
        bg_color=COLOR_BG_ALERT
    )

    add_header("3.3. Adım ve Dokunma Gerilimleri Tahkiki (IEEE 80 & EN 50122-1)", level=2)
    add_para("İstasyon genelinde ve trafo merkezlerinde izin verilen dokunma gerilimi (Ut) ve adım gerilimi (Us) tahkiki:")
    add_para("EN 50122-1 uyarınca DC cer sistemlerinde normal işletme koşullarında ray-toprak potansiyeli U_TE <= 120 V DC olmalıdır.", bullet=True)
    add_para("Kısa süreli arıza durumlarında (t <= 300 ms) azami dokunma gerilimi 300 V DC değerini geçmemeli, aksi halde VLD cihazı tetiklenmelidir.", bullet=True)
    add_para("Yolcuların temas edebileceği metal korkuluklar, yürüyen merdiven karkasları ve bilet turnikeleri istasyon topraklamasına (MEB) bağlı olmalı ancak ray bölgesinden en az 2.0 metre mesafede yalıtılmalıdır.", bullet=True)

    add_header("3.4. Yıldırımdan Korunma (LPS) ve Faraday Kafesi", level=2)
    add_para(
        "İstasyon giriş yapıları, havalandırma bacaları ve yer üstü depo binalarında TS EN 62305 standardına göre:"
    )
    add_para("Koruma Sınıfı: Seviye I (LPL I - En Yüksek Emniyet Düzeyi).", bullet=True)
    add_para("Yakalama Uçları ve Ağ Gözü: Çatı yüzeyinde Faraday kafesi iletkenleri en fazla 5m x 5m ağ gözü (mesh) aralığında döşenmelidir.", bullet=True)
    add_para("İniş İletkenleri ve Test Klemensleri: Her 10 metrede bir iniş iletkeni indirilmeli ve yer seviyesinden 1.5 metre yükseklikte test klemensi (test link box) DWG üzerinde gösterilmelidir.", bullet=True)

    # ==============================================================================
    # BÖLÜM 4: ELEKTRONİK, ZAYIF AKIM VE SCADA SİSTEMLERİNDE HESAPLAR
    # ==============================================================================
    add_header("BÖLÜM 4: ELEKTRONİK, ZAYIF AKIM VE SCADA SİSTEMLERİNDE HESAPLAR VE DWG İNCELEME KRİTERLERİ", level=1)
    
    add_para(
        "Metro zayıf akım sistemleri, can güvenliğinin (Life Safety) ve işletme sürekliliğinin omurgasıdır. "
        "Yapay zeka analiz motoru, her zayıf akım alt disiplininde hem şematik hem de mimari yerleşim paftalarını "
        "çapraz kontrol (cross-validation) ile denetlemelidir."
    )

    add_header("4.1. SCADA ve Çevre Kontrol Sistemi (ECS / BMS) Entegrasyon Denetimi", level=2)
    add_para(
        "İkitelli - Ataköy Şartnamesi (Kısım 04 - SCADA ve Haberleşme) uyarınca her istasyonda çift yedekli (Redundant Hot-Standby) "
        "PLC/RTU mimarisi bulunmalıdır. AI motorunun yapacağı çapraz kontroller:"
    )
    add_para("1. I/O Eşleşme Doğrulaması: DWG tek hat ve kuvvetli akım planlarında yer alan her motorlu damper, yangın damperi, tünel jeti fanı, istasyon besleme/egzoz fanı, karter/drenaj pompası, OG hücre şalteri ve AG kesici için SCADA şemasında (ve I/O listesinde) ilgili DI (Digital Input - Durum/Arıza), DO (Digital Output - Aç/Kapa/Çalıştır) ve AI (Analog Input - Sıcaklık/Akım) noktaları birebir eşleşmelidir.", bullet=True)
    add_para("2. İletişim Protokolü ve Optik Halka (Fiber Ring): İstasyon içi PLC'ler ve uzak I/O modülleri çift halka (dual redundant fiber optic ring) üzerinden IEC 60870-5-104 veya Modbus TCP/IP protokolleriyle bağlanmalıdır. DWG'de yedeksiz (tekil star veya bus) haberleşme hattı hata olarak işaretlenmelidir.", bullet=True)

    add_header("4.2. Yangın Algılama ve Alarm Sistemi (FAS) ve Kapsama Hesapları", level=2)
    add_para(
        "TS EN 54-14 standardı ve İkitelli-Ataköy Şartnamesi Kısım 06 gereğince yapay zeka yangın paftalarını şu kurallara göre tarar:"
    )
    
    headers_4_2 = ["Hacim / Alan Türü", "Dedektör Tipi", "Maksimum Kapsama Alanı / Yarıçap", "Özel Yerleşim / Tavan Kuralları"]
    data_4_2 = [
        ["İstasyon Peron ve Bilet Holü", "Optik Duman Dedektörü", "Maksimum 80 m² / Yarıçap r = 7.5 m", "Yüksek tavanlarda (h > 6m) ışın tipi (beam) veya örneklemeli dedektör"],
        ["Asma Tavan ve Yükseltilmiş Döşeme", "Çift Kat Optik Duman", "Asma tavan içi ve taban altı bağımsız", "Asma tavan yüksekliği > 80 cm ise tavan içine ayrı loop dedektörü zorunlu"],
        ["Trafo ve OG Hücre Odaları", "Optik Duman + Sıcaklık (Multi)", "Maksimum 30 m² / Yarıçap r = 5.3 m", "Yangın söndürme (gazlı) boşaltma için çapraz zon (cross-zone) prensibi"],
        ["Tüneller ve Hat Boyu", "Lineer Sıcaklık Algılama (LHD)", "Fiber optik kablo veya sensör kablosu", "Ray boyunca tünel tavan merkezinde kesintisiz algılama"],
        ["Yangın Butonları ve Flaşörler", "Manuel Buton + Siren/Flaşör", "Maksimum kaçış mesafesi 30 metre", "Tüm acil çıkış kapıları ve merdiven başlarında 1.2 - 1.4 m kotta"]
    ]
    tbl_4_2 = doc.add_table(rows=1, cols=4)
    format_table(tbl_4_2, [1.5, 1.6, 1.8, 2.2], headers_4_2, data_4_2)

    add_callout(
        "YANGIN KONTROL MATRİSİ (CAUSE & EFFECT) DENETİMİ: Yangın algılama paftalarında yangın senaryo matrisi şematik olarak "
        "bulunmalıdır. Yangın alarmı doğrulandığında; turnikelerin manyetik kilitleri serbest kalmalı, asansörler otomatik olarak "
        "çıkış katına inip kapılarını açmalı, yürüyen merdivenler kaçış yönüne doğru tahliye moduna geçmeli veya durmalı, "
        "ilgili duman tahliye damperleri açılarak tünel/istasyon fanları acil duman egzoz moduna geçmelidir. "
        "Kablo tipi TS EN 50200 uyarınca en az PH120 (120 dakika alev altında fonksiyonunu sürdüren) ve FE180 olmalıdır.",
        prefix="YANGIN ALARM VE TAHLİYE SENARYOSU DOĞRULAMASI:",
        border_color="BA181B",
        bg_color=COLOR_BG_ALERT
    )

    add_header("4.3. Kapalı Devre Kamera Sistemi (CCTV / KDTS) ve Depolama Hesapları", level=2)
    add_para(
        "Metro güvenliği EN 62676 serisi standartlara dayanır. Yapay zeka DWG üzerindeki kamera bloklarını, yönelimlerini ve "
        "görüş açılarını (Field of View - FOV) poligon çarpışma (polygon intersection) testleri ile denetlemelidir:"
    )
    add_para("Kör Nokta (Blind Spot) Denetimi: Peron boyunca Peron Ayırıcı Kapı (DCO/PSD) eşiği, tren-peron arayüzü, yürüyen merdiven iniş ve biniş noktaları, acil kaçış kapıları ve bilet turnike hatlarında hiçbir kör nokta kalmamalıdır.", bullet=True)
    add_para("DORI Kriterleri Uyumu: EN 62676-4 uyarınca; Turnike ve biletleme alanında Tanıma/Teşhis (Recognition/Identification: min 250 px/m), Peron ve yürüyen merdivenlerde Gözlem (Observation: min 125 px/m), Tünel ve geniş hacimlerde Algılama (Detection: min 25 px/m) çözünürlüğü sağlanmalıdır.", bullet=True)
    add_para("Depolama ve Bant Genişliği Hesabı: Tüm kameralar en az 1080p (2 Megapiksel) veya 4K çözünürlükte, saniyede 25 resim karesi (25 fps), H.265 / H.264 sıkıştırma formatında, 7/24 kesintisiz olarak EN AZ 30 GÜN kayıt depolayacak NVR / SAN depolama kapasitesi hesap tablosunda belirtilmelidir. Formül: Depolama (TB) = [Kamera Sayısı x Bitrate (Mbps) x 3600 x 24 x 30] / (8 x 10^6).", bullet=True)

    add_header("4.4. Acil Anons ve Seslendirme Sistemi (PA/VA) ve Akustik Kriterler", level=2)
    add_para(
        "İstasyon tünel ve peron hacimleri yoğun betonarme ve yansıtıcı yüzeylerden oluştuğu için ses anlaşılabilirliği hayati önem taşır:"
    )
    add_para("Standart Uyumu: EN 54-16 (Merkezi Ekipman) ve EN 54-24 (Hoparlörler) sertifikasyonu.", bullet=True)
    add_para("Konuşma Anlaşılabilirlik İndeksi (STI): Tüm yolcu alanlarında (peron, konkors, merdivenler) STI değeri en az 0.50 (tercihen STI >= 0.55) olmalıdır. Çizim ekindeki akustik simülasyon raporunda reverberasyon süresi (RT60) hesaplanmış olmalıdır.", bullet=True)
    add_para("Ses Seviyesi (SPL): Arka plan gürültüsünün (tren fren ve hareket gürültüsü ~75-80 dBA) en az 10 dBA üzerinde, minimum 85 dBA ses basınç seviyesi elde edilmelidir.", bullet=True)
    add_para("A/B Yedekli Hoparlör Hatları: Tek bir kablo kopması veya kısa devre durumunda o zonda anonsun tamamen kesilmemesi için yan yana iki hoparlör farklı amplifikatör kanallarından (Hat A ve Hat B) çapraz beslenmelidir. DWG'de homojen dağıtılmış A/B kablolaması kontrol edilmelidir.", bullet=True)

    add_header("4.5. Geçiş Kontrol (ACS) ve Merkezi Saat / Yolcu Bilgilendirme (PIS)", level=2)
    add_para("Geçiş Kontrol Sistemi (ACS): Tüm teknik hacim kapılarında kart okuyucu, manyetik kilit ve manyetik kontak bulunmalıdır. Yangın alarmı anında tüm manyetik kilitler 'Fail-Safe' (enerjisi kesilerek açık konuma geçen) prensipte olmalıdır.", bullet=True)
    add_para("Merkezi Saat Sistemi (Master Clock): İstasyon genelinde GPS ve NTP zaman sunucusu ile senkronize, analog ve dijital tali saatler cer ve sinyalizasyon odaları ile peronlarda gösterilmelidir.", bullet=True)
    add_para("Yolcu Bilgilendirme Sistemi (PIS): Peronlarda ray eksenine dik açıyla yerleştirilmiş LED/LCD tren varış göstergeleri ve konkors yönlendirme ekranlarının görüş mesafeleri mimari DWG ile çakıştırılmalıdır.", bullet=True)

    # ==============================================================================
    # BÖLÜM 5: YAPAY ZEKA (.DWG) OTOMATİK İNCELEME VE HATA DENETİM MOTORU
    # ==============================================================================
    add_header("BÖLÜM 5: YAPAY ZEKA (.DWG) OTOMATİK İNCELEME VE HATA DENETİM MOTORU (RULE ENGINE)", level=1)
    
    add_para(
        "Bu bölüm, yazılım ekibinin DWG analiz motorunda doğrudan uygulayacağı deterministik denetim kurallarını, "
        "algoritmik adımları ve hata sınıflandırma matrisini içermektedir. AI motoru DXF/DWG parser kütüphaneleri "
        "(ezdxf vb.) aracılığıyla nesneleri ayrıştırarak bu kontrolleri koşmalıdır."
    )

    add_header("5.1. AI Doğrulama Kuralları ve Algoritmik Denetim Adımları", level=2)
    
    headers_5_1 = ["Kural ID", "Kural Başlığı / Kapsamı", "İncelenen CAD Nesneleri & Katmanlar", "Matematiksel / Mantıksal Tahkik Formülü", "Hata Seviyesi"]
    data_5_1 = [
        ["R-PWR-01", "Trafo-Kablo Akım Uyumu", "INSERT (Trafo), POLYLINE (AG Kablo)", "Iz_kablo >= In_trafo / 0.91 (kt x kg faktörü)", "KRİTİK"],
        ["R-PWR-02", "Şalter-Kablo Kesit Uyumu", "INSERT (Kablo Bilgisi), INSERT (Şalter)", "Ib <= In_şalter <= Iz_kablo", "KRİTİK"],
        ["R-PWR-03", "Gerilim Düşümü Tahkiki", "POLYLINE (Metraj L), TEXT (Güç P, Kesit S)", "%e = (100*P*L)/(k*S*U²) <= %3 (Aydınlatma) / %5 (Motor)", "MAJÖR"],
        ["R-PWR-04", "Yük Faz Dengesi", "TABLE / TEXT (Yük Dağıtım Cetveli)", "Max(|P_L1 - P_ort|, |P_L2 - P_ort|, |P_L3 - P_ort|) / P_ort <= %10", "MAJÖR"],
        ["R-PWR-05", "N-1 Trafo Yedekliliği", "INSERT (Trafo), TABLE (Toplam İstasyon Yükü)", "Trafo_Gücü (Tek Başına) >= P_toplam_talep * 1.0", "KRİTİK"],
        ["R-PWR-06", "UPS Otonomi Süresi", "INSERT (UPS Blok), TABLE (Akü Listesi)", "Akü Otonomi Süresi >= 120 Dakika (İkitelli-Ataköy Şart.)", "KRİTİK"],
        ["R-EAR-01", "Ray-Toprak Doğrudan Bağlantı", "POLYLINE (Topraklama), LINE (Ray Çizgisi)", "INTERSECT(Ray, Topraklama_PE) == 0 (Doğrudan temas YASAK)", "DURDURUCU"],
        ["R-EAR-02", "VLD Koruma Varlığı", "INSERT (VLD Panosu), LINE (Ray & MEB)", "Ray ile MEB arasında çift yönlü VLD blok bağlantısı VAR MI?", "KRİTİK"],
        ["R-EAR-03", "Stray Current Test Kutusu", "INSERT (SC-JB), POLYLINE (Tünel Ekseni)", "Mesafe(SC_JB_i, SC_JB_i+1) <= 200 Metre", "MAJÖR"],
        ["R-EAR-04", "Eşpotansiyel Baralar (MEB)", "INSERT (MEB Barası), LWPOLYLINE", "İstasyon her iki başında MEB var mı ve 120mm² Cu irtibatlı mı?", "MAJÖR"],
        ["R-FAS-01", "EN 54 Duman Kapsama Alanı", "INSERT (Duman Dedektörü), Hacim Poligonu", "Herhangi bir noktanın en yakın dedektöre mesafesi d <= 7.5 m", "KRİTİK"],
        ["R-FAS-02", "Asma Tavan Çift Kat Detektör", "INSERT (Dedektör), TEXT (Asma Tavan Kotu)", "Asma Tavan Boşluğu > 80cm ise tavan içine ayrı dedektör konmuş mu?", "MAJÖR"],
        ["R-FAS-03", "Yangın Kablo Yangın Dayanımı", "POLYLINE (FAS Loop Hattı), TEXT (Kablo)", "Kablo tipi == 'FE180 / PH120 Halogen-Free' mi?", "KRİTİK"],
        ["R-CTV-01", "Peron & DCO Kör Nokta Analizi", "INSERT (Kamera Blok), POLYLINE (Peron Hattı)", "Peron kenarı poligonunda görüş açısı (FOV) örtüşmesi %100 mü?", "KRİTİK"],
        ["R-CTV-02", "Turnike Tanıma Çözünürlüğü", "INSERT (Kamera), POLYLINE (Turnike Hattı)", "Görüş alanındaki piksel yoğunluğu >= 250 px/m (EN 62676 DORI)", "MAJÖR"],
        ["R-PAV-01", "A/B Çapraz Hoparlör Hattı", "INSERT (Hoparlör A/B), POLYLINE", "Ardışık iki hoparlör aynı fiderden mi beslenmiş? (Farklı olmalı)", "MAJÖR"],
        ["R-ACS-01", "Manyetik Kilit Fail-Safe", "INSERT (ACS Kapı), SCHEMATIC (Yangın Röle)", "Yangın ihbar rölesi açtığında kapı kilit beslemesi kesiliyor mu?", "KRİTİK"],
        ["R-SCA-01", "DWG vs SCADA I/O Listesi", "INSERT (Motor, Pano, Şalter), EXTERNAL I/O", "DWG'deki motor/şalter sayısı ile I/O listesi birebir (1:1) eşleşiyor mu?", "KRİTİK"]
    ]
    tbl_5_1 = doc.add_table(rows=1, cols=5)
    format_table(tbl_5_1, [0.9, 1.6, 1.5, 2.3, 0.8], headers_5_1, data_5_1)

    add_header("5.2. Hata Sınıflandırması ve AI Raporlama Şablonu", level=2)
    add_para(
        "Yapay zeka analiz motoru, DWG dosyasını taradıktan sonra bulgularını üç seviyede derecelendirmelidir:"
    )
    add_para("1. SEVİYE 1: DURDURUCU / KRİTİK UYGUNSUZLUK (Critical Defect): Can güvenliğini doğrudan tehdit eden, uluslararası standartlara (EN 50122, NFPA 130) veya yangın emniyetine aykırı durumlar. Örnek: Rayların doğrudan bina toprağına bağlanması, yangın anında kilitli kalan acil kapılar, N-1 trafo kapasitesinin yetersiz olması. Proje bu haliyle kesinlikle onaylanamaz.", bullet=True)
    add_para("2. SEVİYE 2: MAJÖR MÜHENDİSLİK HATASI (Major Defect): Sistemin işletilmesinde arızaya, aşırı gerilim düşümüne, korozyona veya ekipman ömrünün kısalmasına yol açacak hatalar. Örnek: Kablo kesitinin gerilim düşümü sınırını aşması, faz dengesizliğinin %10'u geçmesi, CCTV peron kör noktası bulunması, tünel test kutularının 200m'yi aşması.", bullet=True)
    add_para("3. SEVİYE 3: MİNOR / ÇİZİM STANDARDI HATASI (Minor Defect): Çizim tekniği, katman adlandırması, antet eksikliği veya sembol uyumsuzlukları. Örnek: Yanlış renkte layer kullanımı, kablo kodunun yazılmaması.", bullet=True)

    add_header("5.3. Yapay Zeka Kural Motoru Python Sözde Kodu (Rule Engine Pseudocode)", level=2)
    add_para(
        "CAD/DWG geometrik ayrıştırıcı motorunun arka planda çalıştıracağı örnek Python kural fonksiyonları:"
    )

    py_pseudocode = """# Metro DWG Kural Motoru Çekirdek Denetim Fonksiyonları (Python Örneği)

def audit_phase_imbalance(load_table_data):
    \"\"\"R-PWR-04: Faz dengesizliği tahkiki (%10 sınırı)\"\"\"
    p_l1 = load_table_data['phases']['L1']
    p_l2 = load_table_data['phases']['L2']
    p_l3 = load_table_data['phases']['L3']
    p_avg = (p_l1 + p_l2 + p_l3) / 3.0
    
    max_dev = max(abs(p_l1 - p_avg), abs(p_l2 - p_avg), abs(p_l3 - p_avg))
    imbalance_ratio = (max_dev / p_avg) * 100.0
    
    if imbalance_ratio > 10.0:
        return {
            "rule_id": "R-PWR-04",
            "severity": "MAJOR",
            "message": f"Faz dengesizliği limiti asildi: %{imbalance_ratio:.2f} > %10.0",
            "action": "Yuklerin fazlar arasinda yeniden dagitilmasi gerekmektedir."
        }
    return {"rule_id": "R-PWR-04", "status": "PASSED"}

def audit_rail_floating_earthing(dxf_model):
    \"\"\"R-EAR-01 & R-EAR-02: Ray izolasyonu ve VLD varlik denetimi\"\"\"
    rail_lines = dxf_model.get_entities_by_layer("E-TRAK-RAIL")
    ground_mesh = dxf_model.get_entities_by_layer("E-EAR-MESH-COND")
    vld_blocks = dxf_model.get_blocks_by_name("VLD_LIMITING_DEVICE")
    
    # 1. Ray ile PE topragi dogrudan temas ediyor mu?
    for r in rail_lines:
        for g in ground_mesh:
            if r.geometry.intersects(g.geometry):
                return {
                    "rule_id": "R-EAR-01",
                    "severity": "CRITICAL_STOPPER",
                    "coord": r.geometry.intersection(g.geometry).coords[0],
                    "message": "DURDURUCU TASARIM HATASI: DC Ray hattı bina topragina dogrudan baglanmis! Korozyon ve can guvenligi faciasi."
                }
    
    # 2. VLD cihazi sematize edilmis mi?
    if len(vld_blocks) == 0:
        return {
            "rule_id": "R-EAR-02",
            "severity": "CRITICAL",
            "message": "Ray ile istasyon topragi arasinda Voltaj Sinirlama Cihazi (VLD) bulunamadi! (EN 50122-1 ihlali)."
        }
    return {"rule_id": "R-EAR-01_02", "status": "PASSED"}

def audit_cctv_coverage(dxf_model, platform_polygon):
    \"\"\"R-CTV-01: Peron ve DCO kapilari kor nokta analizi\"\"\"
    cameras = dxf_model.get_blocks_by_layer("EL-CCTV-CAMR-INDR")
    combined_fov = unary_union([cam.get_fov_polygon() for cam in cameras])
    
    blind_spots = platform_polygon.difference(combined_fov)
    if not blind_spots.is_empty and blind_spots.area > 0.5: # 0.5 m2 üzeri açık alan
        return {
            "rule_id": "R-CTV-01",
            "severity": "CRITICAL",
            "blind_spot_area_m2": blind_spots.area,
            "message": f"Peron hattinda {blind_spots.area:.2f} m2 kor nokta tespit edildi! Kamera yerlesimi revize edilmelidir."
        }
    return {"rule_id": "R-CTV-01", "status": "PASSED"}"""

    add_code_block(py_pseudocode)

    add_header("5.4. Yapay Zeka Parser ve Kural Motoru Veri Modeli (JSON Schema)", level=2)
    add_para(
        "DWG dosyasından ezdxf kütüphanesi veya CAD API'si ile çıkarılan geometrik varlıkların AI Kural Motoruna "
        "aktarılacağı örnek JSON veri yapısı aşağıda sunulmuştur:"
    )

    json_example = """{
  "project_type": "METRO_STATION",
  "drawing_metadata": {
    "file_name": "IA-M05-E-LV-SLD-001_REV02.dwg",
    "station_code": "M05_MIMARSINAN",
    "discipline": "ELECTRICAL_LV",
    "system": "AUXILIARY_POWER"
  },
  "entities": {
    "transformers": [
      { "id": "TR-01", "type": "CAST_RESIN", "power_kva": 1250, "ratio": "34.5/0.4kV", "n1_group": "GRP-A" },
      { "id": "TR-02", "type": "CAST_RESIN", "power_kva": 1250, "ratio": "34.5/0.4kV", "n1_group": "GRP-A" }
    ],
    "switchboards": [
      {
        "id": "AGADP-01",
        "form_type": "4b",
        "busbar_rating_a": 2500,
        "phases_kw": { "L1": 340.5, "L2": 332.1, "L3": 355.8 },
        "imbalance_ratio_percent": 4.1,
        "feeders": [
          { "load_name": "TUNNEL_VENT_FAN_1", "kw": 150, "cb_rating_a": 315, "cable": "3x(1x185/25) N2XH", "length_m": 85, "v_drop_percent": 1.8 }
        ]
      }
    ],
    "earthing": {
      "system_type": "TN-S",
      "measured_or_calc_resistance_ohm": 0.45,
      "meb_count": 2,
      "rail_direct_ground_connection": false,
      "vld_device_present": true
    }
  },
  "audit_results": {
    "critical_defects_count": 0,
    "major_defects_count": 0,
    "minor_defects_count": 1,
    "verdict": "APPROVED_WITH_COMMENTS"
  }
}"""
    add_code_block(json_example)

    add_callout(
        "YAPAY ZEKA ENTEGRASYON MİMARİSİ: Geliştirilen yazılım, DXF/DWG çizimindeki geometrik ve metinsel verileri "
        "JSON formatında ayrıştırarak bir kural motoruna (Rule Engine) iletmeli; kural motoru yukarıda listelenen 18 temel kuralı "
        "koşarak pafta bazında koordinat (X, Y kotu) işaretli 'Revizyon Talep Raporu' üretmelidir.",
        prefix="YAZILIM GELİŞTİRME ÖZETİ:",
        border_color="198754",
        bg_color=COLOR_BG_SUCCESS
    )

    # Doküman Sonu Bilgisi
    p_end = doc.add_paragraph()
    p_end.paragraph_format.space_before = Pt(14)
    p_end.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r_end = p_end.add_run("Teknik Kılavuz Sonu — İkitelli-Ataköy Metro ve Uluslararası Standartlar Uyarınca Derlenmiştir.")
    r_end.font.name = 'Calibri'
    r_end.font.size = Pt(8.5)
    r_end.italic = True
    r_end.font.color.rgb = COLOR_MUTED

    return doc

def main():
    print("Metro DWG Inceleme ve Hesap Kilavuzu Word Belgesi Olusturuluyor...")
    doc = create_guide_document()
    
    desktop_path = Path(r"C:\Users\yvzta\OneDrive\Masaüstü\METRO_PROJELERI_ELEKTRIK_ELEKTRONIK_DWG_INCELEME_VE_HESAP_KILAVUZU.docx")
    backup_path = Path(r"D:\mevzuatinceleme\data\raporlar\METRO_PROJELERI_ELEKTRIK_ELEKTRONIK_DWG_INCELEME_VE_HESAP_KILAVUZU.docx")
    
    # Klasörlerin varlığından emin ol
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    
    doc.save(str(desktop_path))
    print(f"Masaustune kaydedildi: {desktop_path}")
    
    doc.save(str(backup_path))
    print(f"Yedek klasorune kaydedildi: {backup_path}")
    print("Islem basariyla tamamlandi.")

if __name__ == "__main__":
    main()
