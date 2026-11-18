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
COLOR_ACCENT = RGBColor(186, 24, 27)       # Koyu Kırmızı (Alert / Critical)
COLOR_DARK = RGBColor(33, 37, 41)          # Koyu Antrasit (Gövde Metni)
COLOR_MUTED = RGBColor(108, 117, 125)      # Gri (Açıklama / Metadata)
COLOR_GREEN = RGBColor(25, 135, 84)        # Yeşil (Success / Onay)
COLOR_BG_LIGHT = "F8F9FA"                  # Çok Açık Gri Hücre Arka Planı
COLOR_BG_HEADER = "E9ECEF"                 # Tablo Başlığı Arka Planı
COLOR_BG_CALLOUT = "F0F4F8"                # Bilgi Kutusu Arka Planı
COLOR_BG_ALERT = "FFF5F5"                  # Uyarı Kutusu Arka Planı

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

def add_callout(text, prefix="KONTROL & TAKİP PRENSİBİ:", color_hex="102C57", bg_hex="F0F4F8"):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Inches(6.8)
    cell = tbl.cell(0, 0)
    set_cell_background(cell, bg_hex)
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
# KAPAK VE BAŞLIK BÖLÜMÜ
# ==============================================================================
p_cover_pre = doc.add_paragraph()
p_cover_pre.paragraph_format.space_before = Pt(20)
p_cover_pre.paragraph_format.space_after = Pt(4)
p_cover_pre.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_pre = p_cover_pre.add_run("T.C. KAMU, RAYLI SİSTEMLER VE ALTYAPI SÖZLEŞMELERİ DENETİM SİSTEMİ")
r_pre.font.name = 'Calibri'
r_pre.font.size = Pt(11)
r_pre.font.color.rgb = COLOR_MUTED
r_pre.bold = True

p_cover_title = doc.add_paragraph()
p_cover_title.paragraph_format.space_before = Pt(2)
p_cover_title.paragraph_format.space_after = Pt(6)
p_cover_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_title = p_cover_title.add_run("GENEL MEVZUAT, ŞARTNAME VE TEKNİK STANDARTLAR\nDENETİM, KONTROL VE TAKİP ENVANTERİ")
r_title.font.name = 'Calibri'
r_title.font.size = Pt(18)
r_title.font.color.rgb = COLOR_PRIMARY
r_title.bold = True

p_cover_sub = doc.add_paragraph()
p_cover_sub.paragraph_format.space_before = Pt(2)
p_cover_sub.paragraph_format.space_after = Pt(16)
p_cover_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_sub = p_cover_sub.add_run("InsaatAudit Global Katman (1_genel_mevzuat_ve_standartlar) İçerik Dökümü, Madde Haritası ve Eksik Standart Ekleme Rehberi")
r_sub.font.name = 'Calibri'
r_sub.font.size = Pt(11)
r_sub.font.color.rgb = COLOR_SECONDARY
r_sub.italic = True

add_callout(
    "BU BELGENİN KULLANIM AMACI: Bu doküman, sistemin 'data/1_genel_mevzuat_ve_standartlar' havuzundaki tüm kanun, "
    "genel şartname, yönetmelik, tebliğ, mühendislik standardı ve standart formların canlı envanteridir. "
    "1) Kanun ve yönetmeliklerde Resmi Gazete değişiklikleri olduğunda sistemdeki karşılığını kontrol edip güncellemek, "
    "2) Sahada veya denetimlerde eksikliği görülen yeni standart/şartnameleri tespit edip doğru klasöre eklemek, "
    "3) YZ ajanlarının ve geliştiricilerin her konuşmada sistemi baştan taramadan külliyata hakim olmasını sağlamak için kullanılır.",
    prefix="ENVANTER VE KONTROL PROTOKOLÜ:",
    color_hex="102C57"
)


# ==============================================================================
# BÖLÜM 1: GENEL ENVANTER ÖZETİ VE HİYERARŞİ TABLOSU
# ==============================================================================
add_header("1. GENEL MEVZUAT VE STANDARTLAR HAVUZU ÖZET TABLOSU", level=1)

add_para(
    "Global katman, kamu yapım ve danışmanlık sözleşmelerinde tarafların bağlı olduğu genel hukuk kurallarını, "
    "resmi kabul esaslarını ve teknik normları barındırır. İhale Türü (procurement_type) ve Disiplin (subsystem) "
    "filtrelemesi ile çalışan güncel 25 dokümanın klasör dağılımı aşağıdadır:"
)

tbl_summary = doc.add_table(rows=1, cols=5)
format_table(
    table=tbl_summary,
    col_widths=[1.8, 1.2, 1.3, 1.0, 1.5],
    headers=["Klasör / Bölüm", "İhale Türü", "Bağlı Disiplin (Subsystem)", "Dosya", "Temel Kapsam ve Amacı"],
    data=[
        [
            "1_kanunlar/",
            "ortak",
            "sozlesme_ve_idari / sure_uzatimi",
            "4 dosya",
            "4734 KİK, 4735 Sözleşmeler Kanunu, Geçici 5/6 Kararnameleri (Mücbir sebep, fesih, devir, fiyat farkı)."
        ],
        [
            "2_sozlesme_ve_genel_sartnameler/\nyapim_isleri/",
            "yapim",
            "YİGŞ / kabul / alt_yuklenici",
            "3 dosya",
            "Yapım İşleri Genel Şartnamesi (YİGŞ), İhaleler Uygulama Yön., Muayene ve Kabul Yönetmeliği."
        ],
        [
            "2_sozlesme_ve_genel_sartnameler/\ndanismanlik_ve_musavirlik/",
            "danismanlik",
            "sozlesme_ve_idari / kabul",
            "1 dosya",
            "Danışmanlık Hizmet İşleri Genel Şartnamesi (DHİGŞ), Müşavirin özen borcu, kilit personel, puantaj, kabul."
        ],
        [
            "3_tebligler_ve_kararnameler/",
            "ortak",
            "hakedis_ve_fiyat_farki / yeni_fiyat",
            "2 dosya",
            "2013/5608 Fiyat Farkı Esasları (Pn, B katsayısı), Kamu İhale Genel Tebliği (YBF analizi, aşırı düşük)."
        ],
        [
            "4_standart_normlar/\nsinyalizasyon_ve_cbtc/",
            "ortak",
            "sinyalizasyon_cbtc",
            "1 dosya",
            "CENELEC EN 50126 (RAMS), EN 50128 (SIL 4 Yazılım), EN 50129 (Donanım), IEEE 1474 CBTC."
        ],
        [
            "4_standart_normlar/\ncer_gucu_ve_elektrifikasyon/",
            "ortak",
            "cer_gucu_ve_elektrifikasyon",
            "1 dosya",
            "EN 50122 (Kaçak akım/topraklama), EN 50163 (750V/1500V DC cer cerilimi), EN 50328 (Trafo/Redresör)."
        ],
        [
            "4_standart_normlar/\nzayif_akim_ve_scada/",
            "ortak",
            "zayif_akim_ve_scada",
            "1 dosya",
            "EN 54 Yangın algılama, EN 50849 PA/VA anons, IEC 60870-5 SCADA, Peron Ayırıcı Kapı (PSD SIL 3)."
        ],
        [
            "4_standart_normlar/\nyangin_ve_havalandirma/",
            "ortak",
            "havalandirma_ve_yangin_tvs",
            "1 dosya",
            "NFPA 130 Sabit Kılavuzlu Raylı Sistemler Yangın Standardı, EN 12101-3 Duman Tahliye Fanları (F250/F300)."
        ],
        [
            "4_standart_normlar/\nasansor_ve_yuruyen_merdiven/",
            "ortak",
            "asansor_ve_yuruyen_merdiven",
            "1 dosya",
            "EN 115-1 Heavy Duty Yürüyen Merdiven, EN 81-20/50/70/72 Asansör güvenlik, erişilebilirlik, yangın."
        ],
        [
            "4_standart_normlar/\ndemiryolu_ustyapi_ve_ray/",
            "ortak",
            "demiryolu_ustyapi_ve_ray",
            "1 dosya",
            "EN 13674 UIC 60 / 60 E1 raylar (R260/R350HT), EN 13232 Makaslar, EN 14730 Alüminotermit kaynak."
        ],
        [
            "4_standart_normlar/\ninsaat_ve_geoteknik/",
            "ortak",
            "insaat",
            "1 dosya",
            "İnşaat Teknik Şartnamesi, Donatı çeliği bağlama/bindirme kuralları (Madde 14)."
        ],
        [
            "4_standart_normlar/\ngenel_rayli_sistemler/",
            "ortak",
            "karma",
            "2 dosya",
            "AYGM Metro Standartları, Metro Elektromekanik Kapsamlı Standartlar Kataloğu (Kablo, yangın, RAMS)."
        ],
        [
            "5_standart_formlar/",
            "ortak",
            "sozlesme_ve_idari / hakedis",
            "6 dosya",
            "KİK Standart Formları, Şantiye Defteri, Malzeme Onay (MAF), YBF Analiz, Süre Talebi, Hakediş/Kabul."
        ],
        [
            "TOPLAM GÜNCEL ENVANTER",
            "-",
            "-",
            "25 Dosya",
            "9.017 Vektörlük sisteme doğrudan referans sağlayan 176 temel mevzuat ve norm vektörü."
        ]
    ]
)


# ==============================================================================
# BÖLÜM 2: 1_KANUNLAR (KAMU İHALE VE SÖZLEŞMELER KANUNLARI)
# ==============================================================================
add_header("2. 1_KANUNLAR (KAMU İHALE VE SÖZLEŞME HUKUKU)", level=1)

add_para(
    "Bu klasördeki dokümanlar, kamu yapım ve danışmanlık sözleşmelerinin ana hukuki çatısını oluşturur. "
    "Sözleşme hükümlerinin mevzuata aykırı olamayacağı kuralı (4735 Madde 4) gereğince en üst önceliğe sahiptir."
)

tbl_kanun = doc.add_table(rows=1, cols=4)
format_table(
    table=tbl_kanun,
    col_widths=[1.8, 2.3, 1.5, 1.2],
    headers=["Doküman Adı / Yol", "Kapsadığı Kritik Maddeler ve Hükümler", "Denetim & Uyuşmazlık Odak Noktası", "Mevzuat Durumu / Kontrol"],
    data=[
        [
            "4734_Kamu_Ihale_Kanunu_Guncel.md\n(data/1_kanunlar/)",
            "• Madde 1: Amaç ve Kapsam\n• Madde 4: Temel Tanımlar\n• Madde 5: Temel İlkeler (Rekabet, Saydamlık)\n• Madde 9: Yaklaşık Maliyet Gizliliği\n• Madde 12: Şartnameler ve Standartlar (Marka Belirtme Yasağı)\n• Madde 29: Zeyilname Düzenleme Süreleri\n• Madde 38: Aşırı Düşük Teklif Sorgulaması\n• Madde 46: Sözleşmeye Davet ve Kesin Teminat",
            "Yüklenicinin şartname eksikliği veya marka kısıtlaması iddiaları; ihale dokümanındaki çelişkiler; yaklaşık maliyete itirazlar.",
            "[✔] Güncel\nResmi Gazete: 22.01.2002 - 24648 ve son değişiklikler işli."
        ],
        [
            "4735_Kamu_Ihale_Sozlesmeleri_Kanunu_Guncel.md\n(data/1_kanunlar/)",
            "• Madde 4: İlkeler (Sözleşmede Değişiklik Yasağı)\n• Madde 6: Sözleşme Türleri (Anahtar Teslim Götürü Bedel / Birim Fiyat)\n• Madde 8: Fiyat Farkı Verilebilme Koşulları\n• Madde 10: Mücbir Sebepler ve Süre Uzatımı (20 Günlük Yazılı Bildirim & Belgelendirme Şartı)\n• Madde 15: Sözleşmede Değişiklik Halleri\n• Madde 20: Yüklenicinin Temerrüdü ve Fesih İhtarı\n• Madde 24: İlave İşler (%10/%20 Sınırı), İş Eksilişi ve Tasfiye",
            "Süre uzatımı taleplerinde 20 günlük hak düşürücü süre denetimi; temerrüt ihtarları; ilave iş onayları; sözleşme bedeli aşımı.",
            "[✔] Güncel\n4735 Madde 10 süre uzatımında ana hukuki çıpadır."
        ],
        [
            "4735_Gecici_5_ve_6_Madde_Ek_Fiyat_Farki_ve_Sure_Uzatimi_Kararnameleri.md\n(data/1_kanunlar/)",
            "• 5202 Sayılı Cumhurbaşkanı Kararı (Geçici 5. Madde Esasları)\n• 5546 Sayılı Cumhurbaşkanı Kararı (Geçici 6. Madde Esasları)\n• Artırımlı ve Ek Fiyat Farkı Hesaplama Yöntemi\n• Ek Süre Uzatımı Verilme Şartları (İdarenin Onay Şartı)\n• Sözleşmenin Feshi ve Devri Kapsamındaki İstisnalar",
            "Yüklenicinin enflasyon/kur gerekçeli munzam zarar ve ek fiyat farkı talepleri; geçmişe dönük süre uzatımı başvuruları.",
            "[✔] Güncel\nKararname yürürlük ve başvuru takvimiyle uyumlu."
        ],
        [
            "yigs_ve_4735_maddeleri.md\n(data/1_kanunlar/)",
            "• 4735 Madde 10 ↔ YİGŞ Madde 29 (Süre Uzatımı Kesişimi)\n• 4735 Madde 24 ↔ YİGŞ Madde 22 (Yeni Birim Fiyat ve İş Artışı)\n• YİGŞ Madde 39 (Hakediş İtiraz Şerhi Prosedürü)",
            "Hukuki normlar hiyerarşisi (Kanun ↔ Genel Şartname çelişkilerinde Kanunun üstünlüğü denetimi).",
            "[✔] Doğrulandı\nHızlı çapraz başvuru rehberi."
        ]
    ]
)

add_callout(
    "KANUN DEĞİŞİKLİĞİ TAKİP KURALI: Resmi Gazete'de 4734 veya 4735 sayılı Kanunlarda madde değişikliği yayınlandığında; "
    "1) İlgili dosyadaki madde metni güncellenir, "
    "2) 1_ingest.py çalıştırılarak '4734_Kamu_Ihale_Kanunu_Guncel.md' veya '4735_Kamu_Ihale_Sozlesmeleri_Kanunu_Guncel.md' "
    "otomatik olarak artımlı (incremental) modda ChromaDB'ye yeniden işlenir.",
    prefix="MEVZUAT DEĞİŞİKLİK PROTOKOLÜ:",
    color_hex="198754"
)


# ==============================================================================
# BÖLÜM 3: 2_SOZLESME_VE_GENEL_SARTNAMELER
# ==============================================================================
add_header("3. 2_SÖZLEŞME VE GENEL ŞARTNAMELER (YAPIM VE DANIŞMANLIK)", level=1)

add_para(
    "Sistemimizde yapım işleri ile danışmanlık/müşavirlik işleri iki ayrı alt klasöre bölünmüştür. "
    "Böylece yapım projeleri denetlenirken müşavirlik şartnamesi, müşavirlik projeleri denetlenirken yapım şartnamesi "
    "asla arama havuzuna dahil edilmez."
)

add_header("A. Yapım İşleri Genel Şartnamesi ve Yönetmelikleri (procurement_type = 'yapim')", level=2)

tbl_yigs = doc.add_table(rows=1, cols=4)
format_table(
    table=tbl_yigs,
    col_widths=[1.8, 2.3, 1.5, 1.2],
    headers=["Doküman / Dosya", "Kapsadığı Kritik Maddeler", "Denetim & Hak Talebi (Claim) Önemi", "Kontrol Durumu"],
    data=[
        [
            "Yapim_Isleri_Genel_Sartnamesi_YIGS_Tam_Metin.md\n(yapim_isleri/)",
            "• Madde 4: Tanımlar (İdare, Yüklenici, Yapı Denetim Görevlisi)\n• Madde 14: Projelerin Uygulanması ve Şartnameler Önceliği\n• Madde 15: Sözleşmeye Uygunluk ve İşçilik Kontrolü\n• Madde 16: Malzeme Onay ve Denetim Prosedürü\n• Madde 17: İş Programı ve Revize İş Programı Esasları\n• Madde 18: Gecikme Cezaları (Günlük Ceza Kesintisi)\n• Madde 19: Şantiye Günlük Defteri ve Hava Durumu Kayıtları\n• Madde 22: Sözleşmede Bulunmayan İşlerin Fiyatının Tespiti (YBF Formülü)\n• Madde 29: Süre Uzatımı Verilebilecek Haller (Mücbir Sebep, İdare Kusuru)\n• Madde 30: Ödenek Dilimleri ve Revize Edilmesi\n• Madde 39: Hakediş Raporları ve İtiraz Şerhi Usulü (Aynı Gün Yazılı Dilekçe)\n• Madde 41-42: Geçici Kabul ve Kabul Noksanları Kesintisi (%5)\n• Madde 44-45: Kesin Kabul ve Teminatın Gelir Kaydı/İadesi",
            "TÜRK KAMU YAPIM İŞLERİNİN ANA DENETİM ÇATISIDIR. Yüklenici hakediş itirazı yaptıysa Madde 39'a uygun şerh koymuş mu? Süre uzatımı istiyorsa Madde 29'a göre yer teslim gecikmesi var mı? YBF istiyorsa Madde 22 analizi yapılmış mı?",
            "[✔] Tam Metin Esaslı\n12 ana madde eksiksiz işlendi."
        ],
        [
            "Yapim_Isleri_Ihaleleri_Uygulama_Yonetmeligi_Alt_Yuklenici_ve_Is_Artisi.md\n(yapim_isleri/)",
            "• Madde 62: Alt Yüklenicilerin Bildirimi ve İdare Onayı Zorunluluğu\n• Alt Yüklenicilerin Müteselsil Sorumluluğu\n• Madde 50: Teknik Personel Bildirimi, Şantiyede Bulundurma ve Cezalar\n• Madde 58: Revize İş Programı Hazırlama Yükümlülüğü\n• Madde 28: İş Artışı ve İlave İmalat Onay Prosedürü",
            "Taşeron uyuşmazlıkları; İdare onaysız taşeron çalıştırılması cezaları; şantiyede kilit personel bulundurmama cezaları.",
            "[✔] Güncel\nAlt yüklenici denetiminde kullanılır."
        ],
        [
            "Yapim_Isleri_Muayene_ve_Kabul_Yonetmeligi.md\n(yapim_isleri/)",
            "• Madde 5: Kabul Komisyonlarının Teşekkülü\n• Madde 8: Geçici Kabul Başvurusu ve İnceleme Usulü\n• Madde 10: Kabul Noksanları (Eksikliklerin %5'i aşmaması ve nefaset kesintisi)\n• Madde 13: Deneme İşletmesi (Trial Running) ve İşletme Testleri\n• Madde 16: Kesin Kabul Şartları ve Teminat Süresi (Asgari 12 Ay)",
            "Kabul noksanları kesintisine itirazlar; deneme işletmesinde çıkan arızaların geçici kabule etkisi; teminat süresi uzatmaları.",
            "[✔] Güncel\nKabul tutanakları denetiminde esastır."
        ]
    ]
)

add_header("B. Danışmanlık ve Müşavirlik Hizmet İşleri (procurement_type = 'danismanlik')", level=2)

tbl_musavir = doc.add_table(rows=1, cols=4)
format_table(
    table=tbl_musavir,
    col_widths=[1.8, 2.3, 1.5, 1.2],
    headers=["Doküman / Dosya", "Kapsadığı Bölüm ve Maddeler", "Müşavirlik Denetim Odak Noktası", "Kontrol Durumu"],
    data=[
        [
            "Danismanlik_Hizmet_Isleri_Genel_Sartnamesi_ve_Muayene_Kabul.md\n(danismanlik_ve_musavirlik/)",
            "• Bölüm 1: Genel Hükümler ve Bildirimler (Madde 1, 4)\n• Bölüm 2: Müşavirin Yükümlülükleri ve Özen Borcu (Madde 7)\n• Madde 10: Kilit Personel ve Teknik Personel Çalıştırma Zorunluluğu\n• Kilit Personel Değişikliği Şartları (Emsal Deneyim ve İdare Onayı)\n• Kilit Personel Şantiyede Bulunmama Günlük Cezaları\n• Bölüm 3: İşin Süresi, Süre Uzatımı ve Hakedişler (Madde 24, 31)\n• Puantaj Cetvelleri ve Adam/Ay Oranları Kontrolü\n• Bölüm 4: Muayene, Kabul ve Kusur Sorumluluğu (Madde 42)",
            "Müşavirlik firmalarının hakediş kesintisi itirazları; kilit personel değişikliği cezaları; yapım işi geciktiğinde müşavirin ek süre ve ek ücret talepleri.",
            "[✔] Güncel\nMüşavirlik sözleşmelerinde YİGŞ yerine bu şartname devreye girer."
        ]
    ]
)


# ==============================================================================
# BÖLÜM 4: 3_TEBLIGLER_VE_KARARNAMELER
# ==============================================================================
add_header("4. 3_TEBLİĞLER VE KARARNAMELER (FİYAT FARKI VE YENİ FİYAT)", level=1)

add_para(
    "Fiyat farkı ve yeni birim fiyat hesapları, yüklenici claim'lerinin (iddialarının) maliyet boyutunu belirleyen "
    "en hassas teknik-hukuki alandır. Sistemimizdeki iki temel dayanak:"
)

tbl_teblig = doc.add_table(rows=1, cols=4)
format_table(
    table=tbl_teblig,
    col_widths=[1.8, 2.3, 1.5, 1.2],
    headers=["Tebliğ / Kararname Dosyası", "Formüller ve Esaslar", "Denetimdeki Kritik Rolü", "Kontrol Durumu"],
    data=[
        [
            "Yapim_Islerinde_Fiyat_Farki_Esaslari_2013_5608.md\n(3_tebligler_ve_kararnameler/)",
            "• Temel Fiyat Farkı Formülü: F = An x B x (Pn - 1)\n• B Katsayısı (%0.90 veya %1.00 katsayı denetimi)\n• Ağırlık Oranları Temsil Katsayıları (a, b1, b2, b3, b4, b5, c)\n• TÜİK Yİ-ÜFE Endeksleri Kullanım İlkeleri\n• Avans Mahsubu Yapılan Hakedişlerde Fiyat Farkı Hesabı\n• Madde 5: Süre Uzatımı Hallerinde Fiyat Farkı (İş programına göre hak edilen endeks vs fiili hakediş endeksi karşılaştırması)",
            "Yüklenicinin gecikmeli yaptığı işlerde güncel yüksek endeksi talep etmesine karşı İdare koruması; süre uzatımı verilen ayların fiyat farkı endeks tespiti.",
            "[✔] Güncel (2013/5608)\nResmi Kararname formülleri birebir mevcuttur."
        ],
        [
            "Kamu_Ihale_Genel_Tebligi_Yapim_Isleri_ve_Yeni_Fiyat.md\n(3_tebligler_ve_kararnameler/)",
            "• Yeni Birim Fiyat (YBF) Analiz Formatı ve Öncelik Sıralaması:\n  1. İdarenin veya diğer idarelerin rayiç ve analizleri,\n  2. Yüklenicinin teklifindeki analiz girdileri,\n  3. Ticaret Odası onaylı fatura ve rayiçler,\n  4. Piyasa fiyat araştırması tutanakları.\n• YBF Analizinde %25 Yüklenici Kârı ve Genel Gider İlavesi İlkesi\n• Aşırı Düşük Teklif Açıklaması ve İş Kalemleri İncelemesi",
            "Yüklenicinin sunduğu yeni birim fiyat analizlerinin şişirilmiş piyasa tekliflerine dayanmasını engelleme; öncelik sırasına uygunluk denetimi.",
            "[✔] Güncel KİK Tebliği\nYBF anlaşmazlıklarında esastır."
        ]
    ]
)


# ==============================================================================
# BÖLÜM 5: 4_STANDART_NORMLAR (MÜHENDİSLİK DİSİPLİNLERİ VE TEKNİK STANDARTLAR)
# ==============================================================================
add_header("5. 4_STANDART NORMLAR (MÜHENDİSLİK DİSİPLİNLERİ VE KABUL KRİTERLERİ)", level=1)

add_para(
    "Teknik şartnamelerde ve malzeme onaylarında en çok başvurulan uluslararası (CENELEC, IEC, ISO, NFPA, UIC) "
    "ve ulusal (TS, AYGM) standartlar, ilgili mühendislik disiplin klasörlerinde toplanmıştır. "
    "Bu sayede sinyalizasyon denetiminde asansör standartları taranmaz; her uzman kendi normunu çeker:"
)

tbl_normlar = doc.add_table(rows=1, cols=4)
format_table(
    table=tbl_normlar,
    col_widths=[1.8, 2.3, 1.5, 1.2],
    headers=["Disiplin Klasörü / Dosya", "Kapsanan Standart Normlar ve Kodlar", "Kabul Kriteri / Emniyet Seviyesi", "Kontrol Durumu"],
    data=[
        [
            "sinyalizasyon_ve_cbtc/\nRayli_Sistemler_CENELEC_ve_EN_Standartlari_Kabul_Kriterleri_Rehberi.md",
            "• EN 50126 (IEC 62278): RAMS Yönetimi (Güvenilirlik, Kullanılabilirlik, Bakım Yapılabilirlik, Emniyet)\n• EN 50128 (IEC 62279): Demiryolu Yazılım Emniyeti (SIL 0 - SIL 4)\n• EN 50129: Elektronik Güvenlik Sinyalizasyon Sistemleri (SIL 4)\n• IEEE 1474.1 / 1474.2 / 1474.3: CBTC Tren Kontrol ve İletişim Standartları\n• EN 50159: Açık ve Kapalı Ağlarda Güvenli Haberleşme\n• IEC 62290: Kentsel Raylı Sistem Otomasyon Seviyeleri (GoA 1..GoA 4 UTO)",
            "Yüklenici yazılım tesliminde SIL 4 sertifikası ve ISA (Bağımsız Emniyet Değerlendirici) Onay Raporu sunmak zorundadır. Sunulmadan geçici kabul yapılamaz.",
            "[✔] Aktif Norm\nAlstom / CBTC test raporları denetiminde çekirdek referanstır."
        ],
        [
            "cer_gucu_ve_elektrifikasyon/\nCer_Gucu_Elektrifikasyon_EN_50122_50163_Standartlari.md",
            "• EN 50122-1: Elektriksel Güvenlik ve Topraklama (Adım ve Dokunma Gerilimleri)\n• EN 50122-2: Kaçak Akım (Stray Current) Korozyon Önleme Standartları\n• EN 50163 / IEC 60850: Raylı Sistem Besleme Gerilimleri (750V DC / 1500V DC Toleransları)\n• EN 50328 / IEC 61992: Cer Trafo Merkezleri, Diyotlu Redresörler ve Hızlı DC Kesiciler\n• EN 50119: Kataner ve 3. Ray (Third Rail) İletken Standartları",
            "Kaçak akım ölçüm değerleri (< 2.5 mA/km ray); ray-toprak potansiyeli aşımı; cer trafosu harmonik ve aşırı yük sınıfları (Class VI).",
            "[✔] Aktif Norm\nElektrifikasyon onaylarında esastır."
        ],
        [
            "zayif_akim_ve_scada/\nZayif_Akim_SCADA_Haberlesme_ve_PSD_Standartlari.md",
            "• EN 54 Serisi: Otomatik Yangın Algılama ve Alarm (Optik duman, sıcaklık, gaz algılama)\n• EN 50849 / IEC 60268-16: Acil Durum Sesli Anons (PA/VA) ve Konuşma Anlaşılırlığı (STI >= 0.50)\n• IEC 60870-5-104 / IEC 61850: SCADA / RTU / PLC Uzaktan İletişim Protokolleri\n• ETSI TETRA: Sayısal Telsiz Haberleşmesi ve Tünel Sızıntılı Kablo (Leaky Feeder)\n• Peron Ayırıcı Kapı (PSD / PAK) Standartları: SIL 3 / SIL 4 Ara Kilit Güvenliği",
            "Yangın anında SCADA senaryolarının otomatik tetiklenmesi; anons anlaşılabilirlik akustik raporu; PSD kapı sıkışma emniyeti.",
            "[✔] Aktif Norm\nZayıf akım malzeme onaylarında taranır."
        ],
        [
            "yangin_ve_havalandirma/\nYangin_ve_Tunel_Havalandirma_NFPA_130_EN_12101_Standartlari.md",
            "• NFPA 130: Sabit Kılavuzlu Transit ve Yolcu Demiryolu Sistemleri Standardı (Tünel yangın güvenliği, kaçış mesafeleri)\n• EN 12101-3: Duman ve Isı Kontrolü - Cebri Tahliye Fanları (F250 / F300 / F400 - 250°C/300°C 2 saat dayanım)\n• NFPA 13 / NFPA 14 / NFPA 20: Otomatik Yağmurlama (Sprinkler), Yangın Dolapları ve Yangın Pompaları\n• Tünel Havalandırma TVS Kriteri: Kritik Rüzgar Hızı (Critical Velocity) ile duman geri akışını (backlayering) engelleme",
            "Jet fan ve şaft fanı sıcaklık dayanım test sertifikaları; tünel kaçış kapıları aralığı (maks. 244 metre / NFPA 130).",
            "[✔] Aktif Norm\nMekanik TVS denetiminde kullanılır."
        ],
        [
            "asansor_ve_yuruyen_merdiven/\nAsansor_ve_Yuruyen_Merdiven_EN_115_EN_81_Standartlari.md",
            "• EN 115-1: Yürüyen Merdiven ve Yürüyen Bant Güvenlik Kuralları (Metro Tipi / Heavy Duty Gereksinimleri)\n• EN 81-20 / EN 81-50: Yolcu ve Yük Asansörleri Yapım ve Güvenlik Kuralları\n• EN 81-70: Engelli ve Hareket Kısıtlılığı Olan Bireyler İçin Erişilebilirlik Standartları\n• EN 81-72: İtfaiyeci Asansörleri Yangın Dayanımı ve Kuyu Basınçlandırma Kuralları",
            "Metro merdivenlerinde ticari tip yerine 'Heavy Duty (24 saat sürekli çalışma, IP55 motor)' zorunluluğu; itfaiyeci asansörü kuyu su izolasyonu.",
            "[✔] Aktif Norm\nDüşey taşıma malzeme itirazlarında taranır."
        ],
        [
            "demiryolu_ustyapi_ve_ray/\nDemiryolu_Ustyapi_ve_Ray_EN_13674_UIC_60_Standartlari.md",
            "• EN 13674-1: Demiryolu Rayları - Vignol Raylar (60 E1 / UIC 60 Profil, R260 ve R350HT Isıl İşlemli Raylar)\n• EN 13232 Serisi: Demiryolu Makasları ve Kesişmeler (Basit Makas, Kruvazman, Esnek Dil Tertibatı)\n• EN 14730-1 / 14730-2: Rayların Alüminotermit Kaynağı ve Ultrasonik Hata Muayenesi\n• EN 13146: Ray Bağlantı Sistemleri (Esnek Pedler, Mass-Spring Floating Slab Sistemleri)",
            "Ray eğrilik toleransları; ultrasonik kaynak kusur raporları; balastsız metro hattı (slab track) titreşim yalıtım kriterleri.",
            "[✔] Aktif Norm\nÜstyapı ve hat döşeme denetiminde esastır."
        ],
        [
            "insaat_ve_geoteknik/\ninsaat_teknik_sartnamesi.md",
            "• Madde 14: Betonarme Donatı Çeliği ve İlave Metrajlar\n• Donatı bindirme boyları (L = 40-50 phi), paspayı kuralları\n• Projede gösterilmeyen bindirme, kanca ve montaj donatılarının ödenmeyeceği kuralı",
            "Yüklenicinin statik projede gösterilmeyen bindirme çelikleri için ek metraj ve hakediş taleplerinin reddi dayanağı.",
            "[✔] Aktif Norm\nDemir metrajı ihtilaflarında kullanılır."
        ],
        [
            "genel_rayli_sistemler/\nMetro_Elektromekanik_Kapsamli_Standartlar_Katalogu.md &\nAYGM_Rayli_Sistemler_ve_Metro_Teknik_Standartlari.md",
            "• CENELEC & IEC Standartları Genel Fihristi\n• Kablolarda Yangın Dayanımı: EN 50575 (CPR B2ca-s1a,d0,a1), EN 50200 / IEC 60331 (Devre Bütünlüğü 180 dk)\n• EN 45545-2: Raylı Sistem Taşıt ve İstasyon Malzemelerinde Yangın Davranışı (HL3 Düzeyi)\n• AYGM Raylı Sistemler Tasarım Kriterleri (Peron boyları, gabari, elektrifikasyon, kataner)",
            "Kablo yangın uygunluk belgeleri; istasyon mimari bitirme malzemelerinde A1 yanmazlık sınıfı belgeleri.",
            "[✔] Master Katalog\nKarma (multi-discipline) aramalarda tüm alt sistemlere yönlendirilir."
        ]
    ]
)


# ==============================================================================
# BÖLÜM 6: 5_STANDART_FORMLAR
# ==============================================================================
add_header("6. 5_STANDART FORMLAR (İHALE, ŞANTİYE, HAKEDİŞ VE KABUL ŞABLONLARI)", level=1)

add_para(
    "Resmi süreçlerde şekil şartı ve usul kuralları esastan önce gelir. "
    "Yüklenicinin bir hakkı olsa dahi, başvuruyu doğru form şablonuyla ve süresinde yapmaması talebi usulden geçersiz kılar. "
    "Bu klasördeki resmi form formatları:"
)

tbl_formlar = doc.add_table(rows=1, cols=4)
format_table(
    table=tbl_formlar,
    col_widths=[1.8, 2.3, 1.5, 1.2],
    headers=["Standart Form Dosyası", "İçerdiği Resmi Şablon Formatları", "Usul & Hukuk Denetimi Rolü", "Kontrol Durumu"],
    data=[
        [
            "1_ihale_ve_sozlesme_standart_formlari.md\n(5_standart_formlar/)",
            "• Standart Form KİK015.1/Y: Birim Fiyat Teklif Mektubu Formatı\n• Standart Form KİK015.2/Y: Birim Fiyat Teklif Cetveli Tablosu\n• Standart Form KİK022.0/Y: Kesin Teminat Mektubu Formatı (%6)",
            "Teklif cetveli aritmetik hata kontrolleri; teminat mektubu geçerlilik tarihi ve teyit yazısı usulleri.",
            "[✔] KİK Standart Formu\nResmi tebliğ şablonlarıyla uyumlu."
        ],
        [
            "2_santiye_ve_denetim_standart_formlari.md\n(5_standart_formlar/)",
            "• Yer Teslim Tutanağı (YİGŞ Madde 6)\n• Şantiye Günlük Defteri / Günlük Rapor Formatı (YİGŞ Madde 19 - Hava durumu, çalışan işçi, çalışan makine, yapılan imalat)\n• Malzeme Onay Formu (MAF / Technical Submittal) Formatı",
            "Mücbir sebep ve hava şartları iddialarında Şantiye Günlük Defteri'ne zamanında itiraz işlenmiş mi? Malzeme onayı alınmadan imalata başlanmış mı?",
            "[✔] Resmi Saha Formu\nGünlük rapor denetiminde kullanılır."
        ],
        [
            "3_degisiklik_yeni_fiyat_ve_sure_formlari.md\n(5_standart_formlar/)",
            "• Yeni Birim Fiyat (YBF) Analiz Formatı Tablosu (Girdi cinsi, rayiç no, miktar, birim fiyat, %25 kâr)\n• Süre Uzatımı Resmi Talep Dilekçesi Formatı (YİGŞ Madde 29 - Gecikme gerekçesi, başlama tarihi, kanıt evrakı, talep edilen gün sayısı)",
            "Yüklenicinin süre uzatımı dilekçesinde 20 günlük süreyi geçirip geçirmediği ve mazereti somut delille ispatlayıp ispatlamadığı.",
            "[✔] Resmi Claim Şablonu\nDilekçe incelemelerinde esastır."
        ],
        [
            "4_hakedis_dosyasi_ve_yesil_defter_formatlari.md\n(5_standart_formlar/)",
            "• Hakediş Dosyası Dizi Pusulası (Fihrist Yapısı)\n• Geçici Hakediş Ön Kapağı ve İtiraz Şerhi Metni (YİGŞ Madde 39)\n• Yapılan İşler Listesi (Yeşil Defter Metraj Cetveli Formatı)",
            "Yüklenici hakediş kapağına 'Madde 39'a göre itirazi kayıt konulmuştur, gerekçesi ekli dilekçededir' şerhi koymamışsa hak düşer.",
            "[✔] Resmi Mali Form\nHakediş uyuşmazlıklarında kilit form."
        ],
        [
            "5_kabul_ve_hesap_kesme_standart_formlari.md\n(5_standart_formlar/)",
            "• Standart Form KİK024.0/Y: Geçici Kabul Tutanağı Formatı (YİGŞ Madde 41)\n• Standart Form KİK025.0/Y: Kesin Kabul Tutanağı Formatı (YİGŞ Madde 44)",
            "Kabul noksanları listesi ve bitirme tarihi; teminatın 1/2'sinin geçici kabulde iadesi, kalan 1/2'sinin kesin kabulde iadesi şartları.",
            "[✔] Resmi Kabul Formu\nKabul süreçlerinde kullanılır."
        ]
    ]
)


# ==============================================================================
# BÖLÜM 7: GELECEKTE EKLENECEK / EKSİK GÖRÜLEN STANDARTLAR LİSTESİ (CHECKLIST / BACKLOG)
# ==============================================================================
add_header("7. EKSİK GÖRÜLEN VE GELECEKTE EKLENECEK STANDARTLAR LİSTESİ (CHECKLIST)", level=1)

add_para(
    "Sistemin ölçeklenebilir yapısı gereği, yeni projeler (örneğin tünel yoğun bir hat, yüksek hızlı tren projesi "
    "veya uluslararası kredi finansmanlı FIDIC sözleşmesi) eklendikçe sisteme kazandırılabilecek "
    "aday standart ve mevzuat listesi aşağıda hazırlanmıştır. "
    "Bu tabloyu, eksik standartları tamamlamak ve kontrol etmek için bir denetim listesi (audit backlog) olarak kullanabilirsiniz:"
)

tbl_backlog = doc.add_table(rows=1, cols=5)
format_table(
    table=tbl_backlog,
    col_widths=[1.5, 1.4, 1.8, 1.3, 0.8],
    headers=["Kategori / Disiplin", "Standart No / Adı", "Kapsam ve Ekleme Gerekçesi", "Hedef Klasör Yolu", "Durum"],
    data=[
        [
            "Beton & Malzeme",
            "TS EN 206+A2 / TS 13515",
            "Beton - Özellik, performans, imalat ve uygunluk. Metro istasyon ve tünellerinde sülfata dayanıklı beton (C30/37, C40/50), su/çimento oranı ve klorür geçirimsizlik kriterleri.",
            "4_standart_normlar/\ninsaat_ve_geoteknik/",
            "[ ] Bekliyor"
        ],
        [
            "Betonarme İcra",
            "TS EN 13670",
            "Beton Yapıların İcrası (Kalıp alma süreleri, beton döküm sıcaklıkları, soğuk/sıcak derzler, vibrasyon ve kür standartları). Şantiyede beton çatlak ihtilaflarında gerekir.",
            "4_standart_normlar/\ninsaat_ve_geoteknik/",
            "[ ] Bekliyor"
        ],
        [
            "Donatı Çeliği",
            "TS 708 / EN 10080",
            "Betonarme Donatı Çeliği Standartları (B420C, B500C sünek çelik akma/çekme sınırları, kaynaklanabilirlik ve korozyon testleri).",
            "4_standart_normlar/\ninsaat_ve_geoteknik/",
            "[ ] Bekliyor"
        ],
        [
            "Geoteknik & Kazık",
            "TS EN 1536",
            "Özel Jeoteknik İşler - Delme Kazıklar (Fore Kazık). Taşıma gücü, bentonit kalitesi, boyuna donatı kafesi ve beton döküm boynu kriterleri.",
            "4_standart_normlar/\ninsaat_ve_geoteknik/",
            "[ ] Bekliyor"
        ],
        [
            "Geoteknik & Duvar",
            "TS EN 1538",
            "Diyafram Duvarlar (Diaphragm Walls). Aç-kapa metro istasyonlarında su sızdırmazlık (water-tightness), stop-end birleşimleri ve CWS derz profili kriterleri.",
            "4_standart_normlar/\ninsaat_ve_geoteknik/",
            "[ ] Bekliyor"
        ],
        [
            "Tünel NATM",
            "TS EN 14487",
            "Püskürtme Beton (Shotcrete). Çelik tel / polipropilen lif donatılı püskürtme beton erken dayanım (J1, J2, J3 eğrileri) ve enerji yutma kapasitesi.",
            "4_standart_normlar/\ninsaat_ve_geoteknik/",
            "[ ] Bekliyor"
        ],
        [
            "Tünel TBM / Segment",
            "ITA / AFTES Rehberleri",
            "TBM Tünellerinde Prefabrik Beton Segment Üretim ve Montaj Toleransları (Halka kaçıklığı, EPDM conta su sızdırmazlığı, harç enjeksiyonu basma dayanımı).",
            "4_standart_normlar/\ninsaat_ve_geoteknik/",
            "[ ] Bekliyor"
        ],
        [
            "Uluslararası Sözleşme",
            "FIDIC Red Book (1999/2017)",
            "İşveren Tarafından Tasarlanan Yapım İşleri Sözleşmesi (FIDIC Kırmızı Kitap Madde 20 - Hak Talepleri ve Tahkim). AYGM veya Dış Kredili projelerde YİGŞ karşılaştırması için.",
            "2_sozlesme_ve_genel_sartnameler/\nyapim_isleri/",
            "[ ] Bekliyor"
        ],
        [
            "Uluslararası Müşavirlik",
            "FIDIC White Book (Client/Consultant)",
            "Müşavir Sözleşme Modeli. Müşavirin sorumluluk sınırları, tazminat limitleri ve uluslararası mühendislik müşavirliği esasları.",
            "2_sozlesme_ve_genel_sartnameler/\ndanismanlik_ve_musavirlik/",
            "[ ] Bekliyor"
        ],
        [
            "BIM / Sayısal Model",
            "ISO 19650-1 / 19650-2",
            "Bina Bilgi Modellemesi (BIM) ile Tesis ve Altyapı Yönetimi. Metro projelerinde LOD 300 / LOD 400 teslim şartları ve As-Built onay kriterleri.",
            "4_standart_normlar/\ngenel_rayli_sistemler/",
            "[ ] Bekliyor"
        ],
        [
            "İş Güvenliği & Çevre",
            "Tünel İSG Tebliği & ISO 45001",
            "Yeraltı Maden ve Tünel İnşaatlarında İş Sağlığı ve Güvenliği Şartları (Gaz ölçüm sensörleri, metan/karbonmonoksit tahliyesi, acil kaçış odaları).",
            "4_standart_normlar/\nyangin_ve_havalandirma/",
            "[ ] Bekliyor"
        ]
    ]
)


# ==============================================================================
# BÖLÜM 8: YENİ DOKÜMAN EKLEME VE GÜNCELLEME KILAVUZU
# ==============================================================================
add_header("8. YENİ MEVZUAT VE STANDART EKLEME / GÜNCELLEME REHBERİ", level=1)

add_para(
    "Sisteme yeni bir standart, yönetmelik veya form eklemek istediğinizde "
    "aşağıdaki 4 adımlı standart protokolü uygulayınız:"
)

add_header("Adım 1: Doğru Klasörü Seçin", level=2)
add_para("• Genel bir kanun ise: 'data/1_genel_mevzuat_ve_standartlar/1_kanunlar/'", bullet=True)
add_para("• Yapım genel şartnamesi veya yönetmeliği ise: 'data/1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/yapim_isleri/'", bullet=True)
add_para("• Müşavirlik şartnamesi ise: 'data/1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/'", bullet=True)
add_para("• Mühendislik standardı ise: 'data/1_genel_mevzuat_ve_standartlar/4_standart_normlar/<ilgili_disiplin>/' (sinyalizasyon, cer_gucu, yangin, asansor, ray vb.)", bullet=True)
add_para("• Standart form ise: 'data/1_genel_mevzuat_ve_standartlar/5_standart_formlar/'", bullet=True)

add_header("Adım 2: Dosya Formatı ve Başlık Kuralları", level=2)
add_para("• Dosyayı tercihen '.md' (Markdown) formatında hazırlayın (PDF ise otomatik parse edilir ancak MD en hızlı ve temiz yoldur).", bullet=True)
add_para("• Dosyanın ilk satırına tek kare (#) ile tam başlık atın: '# TS EN 206 BETON STANDARTLARI VE KABUL KRİTERLERİ'", bullet=True)
add_para("• Maddeleri veya bölümleri çift kare (##) ile ayırın: '## Madde X - ...' veya '## 1. Giriş'", bullet=True)
add_para("• Metin içinde geçen standart kodlarını açıkça yazın (örn: 'EN 206', 'SIL 4', 'C30/37').", bullet=True)

add_header("Adım 3: Vektör Veritabanını Güncelleme", level=2)
add_para("Dosyayı kaydettikten sonra komut satırından projenin sanal ortamı ile artımlı indekslemeyi çalıştırın:")
add_para(".\\venv\\Scripts\\python.exe 1_ingest.py", bold=True)
add_para("Sistem diğer 112 dosyayı önbellekten koruyacak, yalnızca yeni eklediğiniz standardı milisaniyeler içinde indeksleyecektir.")

add_header("Adım 4: Bu Word Envanterini Güncelleyin", level=2)
add_para("Yeni eklediğiniz standardı bu Word belgesindeki Bölüm 7'deki 'Eklendi [✔]' kutusuna işaretleyin veya ilgili disiplin tablosuna yeni bir satır olarak kaydedin.")

# Çıktı dosyasını kaydet
output_path = Path(r"D:\mevzuatinceleme\GENEL_MEVZUAT_VE_STANDARTLAR_KONTROL_ENVANTERI.docx")
doc.save(str(output_path))
print(f"Başarıyla oluşturuldu: {output_path} ({output_path.stat().st_size} bayt)")
