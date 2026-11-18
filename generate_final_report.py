import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
import os

doc = docx.Document()

# Page Margins
for s in doc.sections:
    s.top_margin = Inches(0.8)
    s.bottom_margin = Inches(0.8)
    s.left_margin = Inches(0.8)
    s.right_margin = Inches(0.8)

COLOR_PRIMARY = RGBColor(16, 44, 87)     # Deep Navy
COLOR_SECONDARY = RGBColor(53, 95, 142)  # Slate Blue
COLOR_ACCENT = RGBColor(186, 24, 27)     # Crimson / Alert
COLOR_DARK = RGBColor(33, 37, 41)        # Dark Charcoal
COLOR_MUTED = RGBColor(108, 117, 125)    # Gray

def set_cell_background(cell, fill_hex):
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._element.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)

def add_header(title, level=1):
    h = doc.add_heading(level=level)
    run = h.add_run(title)
    run.font.name = 'Calibri'
    run.bold = True
    if level == 1:
        run.font.size = Pt(15)
        run.font.color.rgb = COLOR_PRIMARY
        h.paragraph_format.space_before = Pt(14)
        h.paragraph_format.space_after = Pt(4)
    elif level == 2:
        run.font.size = Pt(12)
        run.font.color.rgb = COLOR_SECONDARY
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(3)
    elif level == 3:
        run.font.size = Pt(10.5)
        run.font.color.rgb = COLOR_ACCENT
        h.paragraph_format.space_before = Pt(8)
        h.paragraph_format.space_after = Pt(2)
    return h

def add_para(text, bold=False, italic=False, bullet=False):
    p = doc.add_paragraph(style='List Bullet' if bullet else 'Normal')
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run(text)
    run.font.name = 'Calibri'
    run.font.size = Pt(9.5)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = COLOR_DARK
    return p

def add_callout(text, prefix="DİKKAT / TAAHHÜT:"):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Inches(6.8)
    cell = table.cell(0, 0)
    set_cell_background(cell, "F8F9FA")
    set_cell_margins(cell, top=120, bottom=120, left=180, right=180)
    
    tcPr = cell._element.get_or_add_tcPr()
    borders = parse_xml(f'<w:tcBorders {nsdecls("w")}><w:left w:val="single" w:sz="36" w:space="0" w:color="BA181B"/><w:top w:val="none"/><w:right w:val="none"/><w:bottom w:val="none"/></w:tcBorders>')
    tcPr.append(borders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r1 = p.add_run(prefix + " ")
    r1.bold = True
    r1.font.name = 'Calibri'
    r1.font.size = Pt(9.5)
    r1.font.color.rgb = COLOR_ACCENT
    
    r2 = p.add_run(text)
    r2.font.name = 'Calibri'
    r2.font.size = Pt(9)
    r2.font.color.rgb = COLOR_DARK
    doc.add_paragraph().paragraph_format.space_after = Pt(3)

# Document Title
p_title = doc.add_paragraph()
p_title.paragraph_format.space_before = Pt(0)
p_title.paragraph_format.space_after = Pt(2)
p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_title = p_title.add_run("İKİTELLİ - ATAKÖY METRO HATTI (M9) İNŞAAT VE ELEKTROMEKANİK İŞLERİ")
r_title.bold = True
r_title.font.name = 'Calibri'
r_title.font.size = Pt(17)
r_title.font.color.rgb = COLOR_PRIMARY

p_sub = doc.add_paragraph()
p_sub.paragraph_format.space_after = Pt(14)
p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_sub = p_sub.add_run("24 AYLIK İŞLETME VE BAKIM GÖZETİMİ HİZMETİ KAPSAMLI YÖNETİM REHBERİ,\nYÜKLENİCİ TAAHHÜTLERİ, EĞİTİM & EKİPMAN ENVANTERİ VE CEZAİ YAPTIRIMLAR RAPORU")
r_sub.bold = True
r_sub.font.name = 'Calibri'
r_sub.font.size = Pt(11.5)
r_sub.font.color.rgb = COLOR_SECONDARY

# Metadata Table
meta_tbl = doc.add_table(rows=4, cols=2)
meta_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
meta_tbl.columns[0].width = Inches(2.2)
meta_tbl.columns[1].width = Inches(4.6)
meta_data = [
    ("İhale Kayıt No (İKN) & Sözleşme:", "2015/74736 | Sözleşme Tarihi: 02/02/2016"),
    ("Sözleşme Bedeli & Süresi:", "338.272.200,00 EURO + KDV | 1140 Takvim Günü"),
    ("İşletme ve Bakım Gözetimi Süresi:", "24 Ay (En Az 2 Yıl - Kesin Kabule Kadar Kesintisiz)"),
    ("Yasal ve Teknik Dayanaklar:", "Teknik Şartname (Md. 9.15 Sayfa 660, EK-9.1), Sözleşme (Md. 3, 6, 10, 14, 15), YİGŞ, 4735 S.K.")
]
for idx, (label, val) in enumerate(meta_data):
    row = meta_tbl.rows[idx]
    c1, c2 = row.cells[0], row.cells[1]
    set_cell_background(c1, "E9ECEF")
    set_cell_background(c2, "F8F9FA")
    set_cell_margins(c1, 50, 50, 90, 90)
    set_cell_margins(c2, 50, 50, 90, 90)
    p1 = c1.paragraphs[0]
    p1.paragraph_format.space_after = Pt(1)
    r1 = p1.add_run(label)
    r1.bold = True
    r1.font.name = 'Calibri'
    r1.font.size = Pt(8.5)
    r1.font.color.rgb = COLOR_PRIMARY
    
    p2 = c2.paragraphs[0]
    p2.paragraph_format.space_after = Pt(1)
    r2 = p2.add_run(val)
    r2.font.name = 'Calibri'
    r2.font.size = Pt(8.5)
    r2.font.color.rgb = COLOR_DARK

doc.add_paragraph().paragraph_format.space_after = Pt(6)

# -------------------------------------------------------------
# BÖLÜM 1: GENEL ÇERÇEVE VE YASAL DAYANAKLAR
# -------------------------------------------------------------
add_header("1. GENEL ÇERÇEVE, KAPSAM VE YASAL/SÖZLEŞMESEL DAYANAKLAR", level=1)
add_para("İkitelli - Ataköy Metro Hattı (M9) projesinde 24 aylık işletme ve bakım gözetimi süreci, geçici kabul ile kesin kabul arasındaki 2 yıllık dönemi kapsayan, yüklenicinin (Aga Enerji) ve alt yüklenicilerinin (Alstom, Siemens vb.) sahada fiilen 7/24 teknik personel, yedek parça, özel alet/cihaz bulundurmasını ve işletmeci Metro İstanbul A.Ş. personeline derinlemesine eğitim vermesini zorunlu kılan sözleşmesel bir hizmettir.")

add_para("Bu sürecin resmi dayanakları şunlardır:")
add_para("Teknik Şartname Madde 9.15 (Sayfa 660): 'Yüklenici, Geçici Kabul Sertifikası'nın verilişinden sonra 24 aylık bir süre için Metro'nun ücretli servis işletmesinin Sözleşme'de belirtilen şartlar dahilinde İşletme ve Bakım Gözetimini üstlenecektir.'", bullet=True)
add_para("Teknik Şartname EK-9.1 (Sayfa 658): '2 Yıllık İşletme Bakım ve Organizasyon Şeması' başlığı altında yüklenicinin kurmak zorunda olduğu saha bakım teşkilatını tanımlar.", bullet=True)
add_para("Teknik Şartname Madde 9.5-j (Sayfa 653): Sistem seviyesi test kategorileri arasında 10. ana aşama olarak '2 yıllık İşletme ve Bakım Gözetimi Dönemi' resmi test ve kabul süreci olarak tescil edilmiştir.", bullet=True)
add_para("Sözleşme Madde 3.3: İşin kapsamı tanımlanırken 'Test, devreye alma ve 24 ay süreli işletme ve bakım gözetimi hizmeti' işin ana unsurları arasında açıkça sayılmıştır.", bullet=True)
add_para("Sözleşme Madde 10: 'Teminat süresi, geçici kabul tarihinden kesin kabul tarihine kadar olan süredir ve en az 24 aydır (2 yıldır).' hükmüyle bakım gözetimi süresi teminat süresiyle eşleştirilmiştir.", bullet=True)
add_para("Yapım İşleri Genel Şartnamesi (YİGŞ) Md. 14, 41, 42, 44 ve 4735 Sayılı Kanun Md. 20-22: Yüklenicinin geçici kabul sonrası kusur giderme, bakım gözetimi, taahhütlerini ifa etmemesi halinde yaptırım, ceza ve fesih kurallarını düzenler.", bullet=True)

# -------------------------------------------------------------
# BÖLÜM 2: BAKIM GÖZETİM ÖNCESİ HAZIRLIKLAR (GEÇİCİ KABUL ÖNCESİ)
# -------------------------------------------------------------
add_header("2. BAKIM GÖZETİM ÖNCESİ HAZIRLIK DÖNEMİ (GEÇİCİ KABUL ÖNCESİ YÜKÜMLÜLÜKLER)", level=1)
add_para("24 aylık bakım gözetim döneminin başlayabilmesi için Geçici Kabulün yapılması şarttır. Ancak Geçici Kabul Tutanağı imzalanmadan önce Yüklenicinin aşağıdaki teknik, idari ve lojistik hazırlıkları eksiksiz tamamlamış olması şartname gereğidir:")

add_header("2.1. Test ve Devreye Alma Silsilesinin Tamamlanması", level=2)
add_para("Teknik Şartname Madde 9.3 - 9.14 (Sayfa 645-660) uyarınca Yüklenici sırasıyla şu test aşamalarını tamamlamak ve onaylı test raporlarını İdareye teslim etmek zorundadır:")
add_para("1. Fabrika Kabul Testleri (FAT): IEC ve EN normlarına göre imalatçı tesislerinde gerçekleştirilen tip ve üretim testleri (Sayfa 653).", bullet=True)
add_para("2. Montaj Sonrası Testler ve Denetimi: Ekipmanların montaj sahasındaki statik kontrolleri (Sayfa 653).", bullet=True)
add_para("3. Sistem Entegrasyon ve Arayüz (Çakışma) Testleri (SIT): Sinyalizasyon-PAKS, Sinyalizasyon-Araç, Cer Gücü-Araç, Demiryolu-Araç, Katener-Araç ve Haberleşme-Araç arayüz testleri (Madde 9.10, Sayfa 656).", bullet=True)
add_para("4. Sistem Testleri: İşletme Testleri (Normal, regülasyon, tehir telafi, tarife değişikliği), Arıza Durumu Testleri (Merkezi anklaşman arızası, ATC/ATS arızası, haberleşme kaybı, cer kesintisi), Acil Durum Testleri (Duman tahliye, PESB/CESB butonları, acil fren) (Madde 9.11, Sayfa 656-659).", bullet=True)
add_para("5. Sistem Demonstrasyon Testi (SDT): Deneme işletmesinin provası mahiyetinde sistemi zorlama testi (Madde 9.13, Sayfa 660).", bullet=True)
add_para("6. Deneme İşletmesi (Trial Running): Sözleşme Md. 14.3 uyarınca yolculu işletmeye açılış öncesinde en az 30 gün boyunca boş trenlerle simüle edilmiş işletme takviminde arızasız çalıştırılma şartı (Madde 9.14, Sayfa 660).", bullet=True)
add_para("7. Bağımsız Emniyet Değerlendiricisi (ISA) Emniyet Onayı: EN 50126/50128/50129 kapsamında tüm kritik emniyet risklerinin (Hazard Log) kapatıldığını onaylayan SIL 4 nihai güvenlik raporu (Sözleşme Md. 14.4).", bullet=True)

add_header("2.2. Bütünleşik Çalışma ve Donanım/Yazılım Uyum Sorumluluğu (Merkez Sunucu Uyuşmazlığı)", level=2)
add_callout(
    "Teknik Şartname Madde 3.1 (Sayfa 301) & Madde 4.1 (Sayfa 340):\n"
    "• 'Mevcutta kurulmuş olan sistemle bütünleşik çalışma için yazılım ve donanım uyum sorumluluğu tamamen bu işin yüklenicisinin sorumluluğunda olup, HİÇBİR GEREKÇE VEYA SAV İLERİ SÜREREK BU SORUMLULUĞUNDAN İMTİNA EDEMEZ, EK SÜRE VE İLAVE BEDEL TALEP EDEMEZ.' (Madde 3.1 - Sinyalizasyon).\n"
    "• 'Metrokent-Olimpiyat-Kirazlı Metrosu bünyesinde kurulmuş olan sistemlerle bütünleşik çalışma için yazılım ve donanım uyum sorumluluğu tamamen bu işin yüklenicisindedir. Yüklenici tarafından HİÇBİR GEREKÇE VEYA SAV İLERİ SÜREREK BU SORUMLULUKTAN İMTİNA EDİLEMEZ VE EK SÜRE YA DA İLAVE BEDEL TALEP EDİLEMEZ.' (Madde 4.1 - Kontrol ve Haberleşme).\n\n"
    "HUKUKİ YAPTIRIM: AGA Enerji'nin mevcut HP ProLiant DL380 G5 sinyalizasyon merkez sunucuları veya eski ekipmanlar için 'ekonomik ömrü doldu, donanım eskiydi, yenilemek için ilave bedel isteriz' yönündeki tüm iddiaları doğrudan şartnameye aykırıdır. Sinyalizasyon ve SCADA'nın SIL-4 seviyesinde kesintisiz çalışması için gereken tüm merkez sunucu, donanım ve yazılım revizyonları Poz 301 ve Şartname gereğince Yüklenicinin bila-bedel taahhüdüdür.",
    prefix="MERKEZ SUNUCU VE BÜTÜNLEŞİK ÇALIŞMA KURALI:"
)

add_header("2.3. BİM, CAD, Simülasyon Verileri ve SDK Mülkiyet Haklarının Devri", level=2)
add_callout(
    "Teknik Şartname Madde A.1.32.9 (Model Üzerindeki Haklar, Sayfa 46) & Madde 4.17 (Sayfa 416):\n"
    "• Madde A.1.32.9-a: 'Yapı Denetim Görevlisi/İdare bu proje için üretilen TÜM CAD, BİM, ÖZEL SİMÜLASYON VE TESİS VERİLERİNİN SAHİBİDİR.'\n"
    "• Madde A.1.32.9-b: 'Yapı Denetim Görevlisi/İdare bu dokümanları istediği yerde kullanabilir.'\n"
    "• Madde A.1.32.9-c: 'Yüklenici bunun için EK BİR ÜCRET TALEP EDEMEZ.'\n"
    "• Madde 4.17: 'Yüklenici, tüm kontrol ve haberleşme ekipmanında kullanılan her yazılım lisanına ait \"language computer\"ın lisanslı kopyasını, uygulama ve işletme sistemleri hariç TÜM YAZILIMA AİT SDK (Software Development Kit - Yazılım Geliştirme Kiti) temin edecektir.'\n\n"
    "HUKUKİ YAPTIRIM: Bu veriler, BİM modelleri ve SDK kitleri eksiksiz teslim edilmeden Geçici ve Kesin Kabul Tutanakları onaylanamaz.",
    prefix="BİM, CAD VE YAZILIM MÜLKİYET DEVRİ:"
)

add_header("2.4. Teslim Edilmesi Zorunlu Fiziksel Alet, Test Cihazı ve Donanım Envanteri", level=2)
add_para("Geçici kabul öncesinde Yüklenici, şartnamede açıkça tanımlanan aşağıdaki takım, teçhizat ve cihazları İdareye eksiksiz olarak tutanakla teslim etmek zorundadır:")

# Table of Physical Tools
tools_tbl = doc.add_table(rows=1, cols=4)
tools_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
tools_tbl.columns[0].width = Inches(1.5)
tools_tbl.columns[1].width = Inches(1.3)
tools_tbl.columns[2].width = Inches(0.8)
tools_tbl.columns[3].width = Inches(3.2)

headers = ["Sistem / Disiplin", "Şartname Maddesi", "Adet/Miktar", "Ekipman / Cihaz Adı ve Temel Özellikleri"]
hdr_row = tools_tbl.rows[0]
for idx, h_text in enumerate(headers):
    cell = hdr_row.cells[idx]
    set_cell_background(cell, "102C57")
    set_cell_margins(cell, 70, 70, 90, 90)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(h_text)
    r.bold = True
    r.font.name = 'Calibri'
    r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor(255, 255, 255)

tools_list = [
    ("Aydınlatma & İstasyon Elektrik", "Md. 6.5.6 (Sayfa 552)\nMd. 6.5.1 (Sayfa 540)", "1 Adet", "Portatif MANLİFT: En yüksek armatür buatına erişebilen, asansör ve trene sığabilen, emniyet donanımlı, İSG uyumlu."),
    ("Aydınlatma & İstasyon Elektrik", "Md. 6.5.6 (Sayfa 552)", "1 Adet", "Luxmetre: Yapı Denetim onaylı, profesyonel aydınlatma şiddeti ölçüm cihazı."),
    ("Aydınlatma & İstasyon Elektrik", "Md. 6.5.6 (Sayfa 552)", "1 Takım", "Profesyonel El Aletleri Takımı: Çanta içinde pense, kargaburnu, tornavida, anahtar, yan keski vb."),
    ("Orta Gerilim (OG) Şalt", "Md. 2.4.7 (Sayfa 245-246)", "Her OG Odası İçin 1 Set", "Duvar Tipi İSG Panosu (Life Saving Kit): Kurtarma kancası (izole stanka), örümcek topraklama aparatı (izole, Klas 6), kablo makası."),
    ("Orta Gerilim (OG) Şalt", "Md. 2.4.7 (Sayfa 245)", "Oda Başına 1 Adet", "36 kV OG İzole Sehpa & Dielektrik İzole Halı (OG için 36kV, DC için 45kV, 1m genişlikte)."),
    ("Orta Gerilim (OG) Şalt", "Md. 2.4.7 (Sayfa 246)", "2 Adet", "OG Kesici Taşıma Arabası: Çekmeceli tip kesiciler için orijinal üretici ürünü, 4 tekeri frenli araba."),
    ("AG Dağıtım Panoları", "Md. 2.4.7 (Sayfa 246)", "1 Adet", "AG Şalter Bakım Sehpası: Motorlu şalterler için pano yüksekliğinde, 4 tekeri frenli bakım sehpası."),
    ("OG & DC Şalt Manevra", "Md. 2.4.7 & 2.7.7\n(Sayfa 246, 269)", "Set Halinde", "Manevra Panosu ve Istakaları: 34,5 kV izole stanka, 1500V DC gerilim kontrol stankası, topraklama kolları."),
    ("Cer Gücü Akü & UPS Aküleri", "Md. 2.12.3 (Sayfa 290)\nMd. 6.4.7.7 (Sayfa 538)", "2 TAM SET\n(1 DC Akü, 1 UPS)", "Termal Kamera (5\" LCD, tam radyometrik), Akü Test Cihazı (İç direnç ölçer + hidrometre), Bomemetre, Torkmetre, Portatif Akü Şarj Cihazı (12V-6V), Dijital True RMS Multimetre (50.000 count, 1µV), İzole Takım Çantası, Asit KKD."),
    ("Röle & Güç Sistemleri", "Md. 2.3 (Sayfa 234-235)", "1 Adet", "Röle Programlama ve Test Dizüstü Bilgisayarı (Laptop): Lisanslı yazılımlar kurulu, parametre set değerleri yüklü, kablo aparatlı."),
    ("SCADA ve ECS Kontrol", "Md. 4.10.1 (Sayfa 392)", "1 Adet", "SCADA/ECS Bakım Dizüstü Bilgisayarı: Sunucu/RTU konfigürasyon programları lisanslı yüklü, tüm as-built ve manueller yüklü laptop."),
    ("Haberleşme & Network", "Md. 4.3.3.3 (Sayfa 351)\nMd. 4.17 (Sayfa 416)", "En az 3 Raf\n+ SDK Kiti", "Kabin İçi Bakım Laptopu Rafları + Tüm yazılımlar için SDK (Yazılım Geliştirme Kiti), Language Computer lisansları."),
    ("Sinyalizasyon & Tren Kontrol", "Md. 3 (Sayfa 305-306)\nMd. 3.10 (Sayfa 328)", "1 Adet Simülatör\n+ Test Kiti", "Sinyalizasyon Sistemi Simülatörü: PC tabanlı, offline çalışabilen birebir prototip simülatör + Sinyalizasyon Arıza Tespit ve Test Ekipmanları."),
    ("Rijit Katener (Havai Ray)", "Md. 2.9.9 (Sayfa 280)", "200 Metre Komple\n+ 2 Takım Alet", "200m Komple Sistem Yedek Malzemesi + 2 Takım Montaj/Bakım Alet-Edevatı (İletken ray açma ve tel çekme cihazı) + 1500V Kontrol Kiti (2 ad)."),
    ("Yürüyen Merdiven & Asansör", "Md. 7.2.1, 7.3.1, 7.2.14\n(Sayfa 581, 593, 598)", "Set Halinde", "ISO 18738 Sürüş Kalitesi ve Titreşim Test Cihazı (FFT Cihazı) + PLC Özel Bakım-Onarım ve Konfigürasyon Test Ekipmanları."),
    ("Demiryolu Üstyapı", "Md. 8.6.1 (Sayfa 616)\nMd. 8.8 (Sayfa 622)", "Set Halinde", "Makineli Özel Ray Bükme Aleti (R<150m raylar için) + Vakumlu Metal Tozu Toplayıcılı Ray Taşlama Aracı."),
    ("Tünel Emniyet Teçhizatı", "Md. 1.15.6.7 (Sayfa 166)", "20 Paket\n+ 12 Lamba", "20 Adet Kurtarma Paketi (Çanta ve kemerli) + 12 Adet Şarj Edilebilir Kafa Lambası ve 6 Adet Şarj Cihazı.")
]

for row_data in tools_list:
    row = tools_tbl.add_row()
    for idx, text in enumerate(row_data):
        cell = row.cells[idx]
        set_cell_margins(cell, 50, 50, 70, 70)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(text)
        r.font.name = 'Calibri'
        r.font.size = Pt(8)
        if idx == 0:
            r.bold = True
            r.font.color.rgb = COLOR_PRIMARY
        elif idx == 2:
            r.bold = True
            r.font.color.rgb = COLOR_ACCENT
        else:
            r.font.color.rgb = COLOR_DARK

doc.add_paragraph().paragraph_format.space_after = Pt(6)

add_header("2.5. Yedek Parçaların (Spare Parts) Depo Teslimi", level=2)
add_para("Yüklenici, geçici kabul öncesinde 24 aylık işletme süresi boyunca meydana gelebilecek tüm aşınma ve arızaları karşılayacak 'İlk Yatırım / Garanti Süresi Yedek Parçalarını' (Madde 3, Sayfa 306) temin edip İdarenin belirlediği depolara tutanakla teslim etmek zorundadır. Bu yedek parçalar; Alstom CBI2 interlocking kartları, aks sayıcılar, empedans kuponları, balizler, makas motor parçaları, OG/DC hücre röleleri, doğrultucu diyotları, SCADA RTU modülleri, havalandırma kayış-kasnak ve yatakları, yürüyen merdiven basamak ve zincir parçalarını kapsar.")

add_header("2.6. As-Built Projeler ve İşletme-Bakım (O&M) El Kitapları", level=2)
add_para("YİGŞ Madde 14 ve Teknik Şartname Madde 1.16.15.15 (Sayfa 210), Madde 2.4.7 (Sayfa 246) ve Madde 4.10.1 (Sayfa 392) uyarınca:")
add_para("1. As-Built Projeleri: Sahada fiilen imal edilen son durumu gösteren, Yapı Denetim onaylı revizyon paftaları ve tek hat şemaları hem basılı hem CAD/PDF formatında teslim edilecek, ayrıca OG/DC odalarındaki metal proje havuzlarına yerleştirilecektir.", bullet=True)
add_para("2. İşletme ve Bakım El Kitapları (O&M Manuals): Türkçe ve İngilizce dillerinde hazırlanmış; sistem işletme prosedürleri, periyodik koruyucu bakım takvimleri, adımlı arıza bulma ve giderme kılavuzları (Troubleshooting Guides) dijital ve ciltli basılı nüshalar halinde teslim edilecektir.", bullet=True)

# -------------------------------------------------------------
# BÖLÜM 3: SÜRECİN BAŞLANGICI, ORGANİZASYON VE EĞİTİMLER
# -------------------------------------------------------------
add_header("3. SÜRECİN BAŞLANGICI, TEKNİK EKİP ORGANİZASYONU VE EĞİTİM PROGRAMI", level=1)

add_header("3.1. Sürecin Başlangıç Miladı", level=2)
add_para("Teknik Şartname Madde 9.15 (Sayfa 660) ve Sözleşme Madde 10 gereğince, 24 aylık bakım gözetimi süreci, Geçici Kabul Komisyonu'nun tutanağı imzaladığı ve İdare Makamı'nın kabul tutanağını onayladığı tarihte resmen başlar. Bu tarihten itibaren hat ticari yolculu işletmeye açılır ve Yüklenicinin 'İşletme ve Bakım Gözetimi Hizmeti' fiilen devreye girer.")

add_header("3.2. Yüklenicinin Saha Organizasyon Şeması ve Personel Yükümlülükleri (EK-9.1)", level=2)
add_para("Teknik Şartname Sayfa 658'de yer alan 'EK-9.1: 2 Yıllık İşletme Bakım ve Organizasyon Şeması' doğrultusunda Yüklenici, hatta kesintisiz hizmet verecek aşağıdaki uzman kadroyu 7/24 esasına göre istihdam etmek zorundadır:")
add_para("Proje Bakım Direktörü / Elektromekanik Başmühendisi: İdare ve Metro İstanbul ile tüm teknik koordinasyonu yürüten tam yetkili yönetici.", bullet=True)
add_para("Sinyalizasyon ve Tren Kontrol Ekibi (Alstom Sertifikalı Uzmanlar): Interlocking (CBI2), ATS (Ebiscreen), ATO/ATP ve hat boyu sinyal teçhizatına 7/24 müdahale edecek sertifikalı mühendis ve teknisyenler.", bullet=True)
add_para("Güç Temini ve Cer Gücü Ekibi: 34,5 kV OG şalt, 1500V DC redresörler, rijit katener ve trafo merkezleri bakım uzmanları.", bullet=True)
add_para("SCADA, ECS ve Telekomünikasyon Ekibi: İstasyon/tünel SCADA, RTU, yangın senaryoları, CCTV, telsiz (TETRA) ve iletim şebekesi uzmanları.", bullet=True)
add_para("Mekanik ve TVS Ekibi: Tünel havalandırma fanları, jet fanlar, yangın ve drenaj pompa istasyonları bakım personeli.", bullet=True)
add_para("Yürüyen Merdiven ve Asansör Acil Müdahale Ekibi: İstasyon dikey sirkülasyon ünitelerine derhal müdahale edebilecek nöbetçi teknik ekip.", bullet=True)

add_header("3.3. Servis Seviyesi Taahhütleri (SLA) ve Müdahale Süreleri", level=2)
add_para("Yüklenici, bakım gözetimi süresince İdareye yazılı SLA taahhüdü vermek zorundadır. Metro işletme standartlarına göre geçerli müdahale süreleri:")
add_para("Kritik Arızalar (Seferi durduran, tren tehirine yol açan veya can/mal emniyetini etkileyen arızalar): En geç 15 dakika içinde sahada müdahale, en geç 2 saat içinde arızanın giderilmesi ve hattın normale döndürülmesi zorunludur.", bullet=True)
add_para("Tali Arızalar (İşletmeyi doğrudan durdurmayan ancak yedekliliği bozan arızalar): En geç 4 saat içinde müdahale; işletme saatleri dışındaki gece bakım penceresinde (01:00 - 05:00) kesin onarım tamamlanacaktır.", bullet=True)

add_header("3.4. Zorunlu Personel Eğitim Programı (Kimlere, Ne Zaman, Hangi Kapsamda?)", level=2)
add_para("Yüklenici, Metro İstanbul A.Ş.'nin işletme ve bakım personeline teorik ve işbaşı pratik eğitimleri vermekle yükümlüdür. Şartnamede yer alan eğitim şartları şunlardır:")

add_para("1. İki Kademeli Eğitim Takvimi (Light ve Heavy Training):", bold=True)
add_para("Teknik Şartname Madde 7.2.15 (Sayfa 594) ve Madde 3.5 (Sayfa 306) uyarınca eğitimler iki aşamalı yapılacaktır:")
add_para("Aşama 1 (Light Training): Sistem işletmeye açılmadan en az 6 ay önce sınıf içi (off-the-job) temel eğitim ve işletme oryantasyonu.", bullet=True)
add_para("Aşama 2 (Heavy Training): Sistemin geçici kabulü yapıldıktan en erken 6 ay sonra derinlemesine arıza tespiti, bakım ve onarım odaklı işbaşı (on-the-job) eğitimi.", bullet=True)

add_para("2. Sinyalizasyon & Simülatör Eğitimi (Madde 3, Sayfa 305-306):", bold=True)
add_para("Metrokent, Olimpiyat, Kirazlı ve İkitelli-Ataköy entegre sistemini tanıtan, arıza simülasyonları yapabilen PC tabanlı simülatör üzerinde Metro İstanbul sinyal bakım ve kumanda operatörlerine iki aşamalı tam eğitim verilecektir.", bullet=True)

add_para("3. İletim / Haberleşme Şebekesi CCNA Seviyesi Eğitimi (Madde 4.3.3.4, Sayfa 353):", bold=True)
add_para("'Yüklenici teklif ettiği Sistem'in tüm ekipman kapasitesi ile birlikte... bu sistem için en az CCNA sertifikasyonu seviyesinde eğitim verecektir.' hükmü amirdir.", bullet=True)

add_para("4. SCADA ve ECS 3 Seviyeli Yazılım Eğitimi (Madde 4.10.1, Sayfa 392):", bold=True)
add_para("İşletme ve bakım personeli için ayrı ayrı düzenlenecek olup, bakım personeline verilecek eğitimler her 3 seviyedeki yazılımın (sunucu, iş istasyonu, RTU) konfigürasyon ve teşhis eğitimlerini kapsayacaktır.", bullet=True)

add_para("5. AG Şalter ve Güç Dağıtım Yazılım Eğitimi (Madde 2.11, Sayfa 286):", bold=True)
add_para("İdarenin tayin edeceği en fazla 5 kişilik bir teknik mühendislik ekibine, şalter ayarları ve seçicilik yazılımlarının kullanım eğitimi verilecektir.", bullet=True)

add_para("6. Peron Ayırıcı Kapı Sistemleri (PAKS) Eğitimi (Madde 1.16.15.15, Sayfa 210):", bold=True)
add_para("PAKS işletme, mekanik/elektronik bakım ve acil mod yönetim eğitimleri İdare onaylı uzman eğiticiler tarafından verilecek, ders müfredatı ve eğiticilerin CV'leri önceden onaylatılacaktır.", bullet=True)

# -------------------------------------------------------------
# BÖLÜM 4: 24 AYLIK SÜREÇ BOYUNCA SORUMLULUKLAR VE YÜRÜTÜM
# -------------------------------------------------------------
add_header("4. 24 AYLIK SÜREÇ BOYUNCA YÜKLENİCİNİN SORUMLULUKLARI VE İŞ YÜRÜTÜMÜ", level=1)
add_para("2 yıllık süreç boyunca Yüklenici yalnızca gözlemci değil, sistemin performansından ve sürekliliğinden birinci derecede sorumlu teknik taraftır:")

add_para("1. Periyodik Koruyucu Bakımların İcrası:", bold=True)
add_para("O&M el kitaplarında belirtilen günlük, haftalık, aylık, 3 aylık, 6 aylık ve yıllık koruyucu bakım takvimleri Yüklenici gözetiminde ve Yüklenicinin sağladığı kalibre test cihazları (Megger, akü iç direnç test cihazı, FFT titreşim cihazı, termal kamera) ile gerçekleştirilecektir.")

add_para("2. RAMS İzleme ve Düzenli Raporlama (Madde 9.3.1.4, Sayfa 649-650):", bold=True)
add_para("CENELEC EN 50126 standardına uygun olarak sistemin Güvenilirlik (Reliability), Kullanılabilirlik (Availability) ve Bakım Yapılabilirlik (Maintainability) değerleri sürekli ölçülecektir. Yüklenici:")
add_para("Sistemin hedeflenen kullanılabilirlik oranını (>%99.9x) sağladığını belgeleyen Aylık ve 3 Aylık RAMS Raporlarını İdareye sunacaktır.", bullet=True)
add_para("MDBF (Mean Distance Between Failures - İki Arıza Arası Ortalama Mesafe) ve MTBF (Mean Time Between Failures - İki Arıza Arası Ortalama Süre) istatistiklerini raporlayacaktır.", bullet=True)

add_para("3. Yazılım Garanti ve Hata Düzeltme Taahhüdü (Software SLA) (Madde 4.17, Sayfa 416):", bold=True)
add_para("24 ay boyunca CBTC, CBI, ATS, SCADA, PLC ve transmisyon sistemlerinde ortaya çıkabilecek tüm yazılım hataları (software bugs), güvenlik açıkları ve donanımsal sürücü uyumsuzlukları Yüklenici tarafından bila-bedel giderilecek, güncellemeler ve yamalar (patch) ücretsiz yüklenecektir.")

add_para("4. Reaktif Güç, Harmonik ve Fliker Fatura Cezalarının Yükleniciye Rücu Edilmesi (Madde 2.2.4, Sayfa 232):", bold=True)
add_callout(
    "Teknik Şartname Madde 2.2.4 (Sayfa 232):\n"
    "• 'Reaktif kullanım bedeli faturalandırılmasına ve harmonik ve fliker ile ilgili yerel elektrik şirketi yaptırımlarına maruz kalmamak için ilgili güncel mevzuat çerçevesinde Yüklenici, kuracağı tesisin... reaktif tüketim bedelinin, akım/gerilim toplam harmonik distorsiyonlarının ve flikerlerin izin verilen limitleri hiç bir şekilde aşmamasından sorumludur.'\n"
    "• 'YÜKLENİCİ, GARANTİ DÖNEMİNİN SONUNA KADAR; BAHSEDİLEN LİMİTLERİN HERHANGİ BİR FATURADA AŞILMASI DURUMUNDA FATURAYA YANSITILAN İLAVE BEDELİ ÖDEMEKLE YÜKÜMLÜDÜR.'\n\n"
    "HUKUKİ YAPTIRIM: İşletme döneminde BEDAŞ/TEDAŞ tarafından İdareye tahakkuk ettirilecek her türlü reaktif ceza, harmonik faturası ve fliker cezası doğrudan Yüklenici hakedişinden kesilir veya rücu edilir.",
    prefix="REAKTİF GÜÇ VE HARMONİK CEZA RÜCU KURALI:"
)

add_para("5. Yürüyen Merdiven ve Asansörlerde %20 Kronik Problem Değişim Kuralı (Bölüm 7, Sayfa 581):", bold=True)
add_callout(
    "Teknik Şartname Bölüm 7 (Sayfa 581):\n"
    "• 'Alım yapılan ekipmanların %20'sinde aynı malzemede problem olduğu tespit edilirse, YÜKLENİCİ SÖZ KONUSU PARÇALARIN TAMAMINI BİR YIL İÇERİSİNDE DEĞİŞTİRMEKLE SORUMLUDUR.'\n"
    "• 'Çalışan hatlarda işletme şartları göz önüne alınarak iş programı idare tarafından oluşturulacaktır. Böyle bir durumda, ekipmanın devre dışı kalması sebebiyle, oluşabilecek masraflar ve ayarlanan parçaların yeniden test edilmesi için yapılacak ziyaretin masrafları Yüklenici tarafından karşılanacaktır.'\n\n"
    "HUKUKİ YAPTIRIM: Yürüyen merdiven veya asansör parçalarında kronik üretim/tasarım hatası oluşması halinde Yüklenici tüm hattaki o parçaların %100'ünü 1 yıl içinde bedelsiz değiştirmek zorundadır.",
    prefix="DİKEY SİRKÜLASYON %20 KRONİK DEĞİŞİM KURALI:"
)

add_para("6. Kullanılan Yedek Parçaların Anında Stok Tamamlaması:", bold=True)
add_para("Garanti süresi içinde meydana gelen arızalarda depodan kullanılan her türlü yedek parça, yüklenici tarafından derhal yenisi sipariş edilerek en geç sözleşmede belirlenen tedarik süresi içinde depoya iade edilecek, stok seviyesi hiçbir zaman eksilmeyecektir.")

# -------------------------------------------------------------
# BÖLÜM 5: 2 YILIN SONU VE KESİN KABUL ŞARTLARI
# -------------------------------------------------------------
add_header("5. 2 YILLIK SÜRECİN SONU VE KESİN KABUL ŞARTLARI (BİTİM YÜKÜMLÜLÜKLERİ)", level=1)
add_para("24 aylık sürenin tamamlanması kendiliğinden kesin kabul anlamına gelmez. Kesin Kabulün yapılabilmesi ve kesin teminatın iade edilebilmesi için şu şartların yerine getirilmesi zorunludur:")

add_para("1. Kesin Kabul Heyetinin Sahada Denetimi (YİGŞ Md. 44):", bold=True)
add_para("İdare tarafından teşkil edilecek Kesin Kabul Komisyonu tüm hattı, istasyonları, cer gücü ve sinyalizasyon merkezlerini inceler. 24 aylık işletme boyunca ortaya çıkan fen ve sanat kurallarına aykırı hususlar ve malzeme kusurları tespit edilir.")

add_para("2. Demiryolu Makaslarında 2 Ay İçinde Bedelsiz Değişim Zorunluluğu (Madde 8.11, Sayfa 633):", bold=True)
add_callout(
    "Teknik Şartname Madde 8.11 (Sayfa 633):\n"
    "• 'Firma üretmiş olduğu makasları son parti kabul tarihinden itibaren 4 yıl süre ile herhangi bir üretim kusuru ile kabul sırasında saptanamayan kusurlara karşı garanti edecektir. Garanti süresi sonrasında bakım onarım ve yedek parça için yüklenici firma 3 yıl boyunca bedeli mukabilinde yedek parça verme taahhüdünde bulunacaktır.'\n"
    "• 'BU SÜRE İÇERİSİNDE KUSURLARI NEDENİYLE SERVİSTEN KALDIRILAN KOMPLE MAKAS VEYA MAKAS PARÇALARI VE AHŞAP TRAVERSLERİ YÜKLENİCİ YA YENİLERİNİ 2 AY İÇERİSİNDE BEDELSİZ VERECEK YA DA BEDELLERİNİ ÖDEYECEKTİR. YENİSİNİ VERMESİ DURUMUNDA ÜRETİCİ GÜMRÜK VERGİLERİ VE ULAŞIM MASRAFLARINI DA KARŞILAYACAKTIR.'",
    prefix="MAKAS 2 AYDA BEDELSİZ DEĞİŞİM ZORUNLULUĞU:"
)

add_para("3. Yedek Parça Deposunun Eksiksiz Olarak İdareye Devri:", bold=True)
add_para("2 yıllık işletme sürecinde depodan çekilen tüm yedekler yerine konulmuş olacak; sözleşme eki yedek parça listesindeki tüm kalemler ambalajlı, etiketli ve yeni olarak İdareye sayımla devredilecektir.")

add_para("4. Geleceğe Yönelik 10 Yıllık ve 3 Yıllık Garanti/Tedarik Belgelerinin Teslimi:", bold=True)
add_para("Demiryolu Makasları için 3 Yıllık Yedek Parça Taahhüdü (Madde 8.11, Sayfa 633).", bullet=True)
add_para("Sinyalizasyon için Garanti Sonrası 3 Yıllık Yedek Parça Temini (Madde 3.5, Sayfa 305).", bullet=True)
add_para("İstasyon Elektrik/Aydınlatma için 10 Yıllık Parça Temin Garantisi (Madde 6.4, Sayfa 548).", bullet=True)

add_para("5. Kesin Teminatın İadesi (Sözleşme Md. 10 & YİGŞ Md. 44):", bold=True)
add_para("Kesin kabul tutanağının İdarece onaylanması, SGK ilişiksizlik belgesinin getirilmesi, kesin hesabın çıkarılması ve varsa yükleniciye ait gecikme cezaları veya ceza kesintilerinin mahsubundan sonra sözleşme bedelinin %6'sı tutarındaki kesin teminat mektubu iade edilir.")

# -------------------------------------------------------------
# BÖLÜM 6: CEZAİ, MALİ VE HUKUKİ YAPTIRIMLAR
# -------------------------------------------------------------
add_header("6. YÜKLENİCİNİN TAAHHÜTLERİNİ YERİNE GETİRMEMESİ HALİNDE UYGULANACAK CEZA VE YAPTIRIMLAR", level=1)
add_para("Yüklenicinin şartname taahhütlerini aksatması halinde Yapı Denetim ve İdare tarafından işletilecek cezai yaptırımlar şunlardır:")

add_header("6.1. Maktu İSG ve Saha İhlal Cezaları (Madde A.1.30 Fıkra 64, Sayfa 32-33)", level=2)
add_callout(
    "Teknik Şartname Madde A.1.30 Fıkra 64 (Sayfa 32-33):\n"
    "İş güvenliği kurallarına uyulmaması halinde Yapı Denetim Görevlisi tarafından hakedişten doğrudan kesilecek günlük maktu cezalar:\n\n"
    "• Md. 64-a (KKD / İş Elbisesi İhlali): Şantiye ve bakım sahasında reflektif iş elbisesi, baret, toz maskesi veya KKD donanımı eksik olan HER BİR PERSONEL İÇİN GÜNLÜK 200 TL CEZA KESİLİR.\n"
    "• Md. 64-b (Emniyet Tedbiri Alınmayan Saha): Çevre emniyeti, ışıklı uyarıcı, barikat ve trafik yönlendirici tedbirleri alınmayan HER BİR ÇALIŞMA SAHASI İÇİN GÜNLÜK 3.000 TL CEZA KESİLİR.\n"
    "• Md. 64-c (İSG Bildirimi Yapılmadan İşe Başlama): Yapı Denetim ve İSG birimine yazılı bildirim yapılmadan başlanan HER BİR SAHA İÇİN GÜNLÜK 1.000 TL CEZA KESİLİR.",
    prefix="MAKTU İSG VE SAHA İHLAL CEZALARI:"
)

add_header("6.2. Sözleşme İçi Günlük Gecikme Cezası (Sözleşme Madde 15.1)", level=2)
add_callout(
    "Sözleşme Madde 15.1:\n"
    "• Sözleşme Bedelinin ON BİNDE 3'Ü (0,0003) oranında günlük gecikme cezası uygulanır.\n"
    "• Sözleşme Bedeli: 338.272.200,00 EURO\n"
    "• GÜNLÜK GECİKME CEZASI: 338.272.200 x 0,0003 = 101.481,66 EURO / GÜN\n"
    "• AYLIK GECİKME CEZASI: ~3.044.450,00 EURO / AY",
    prefix="GECİKME CEZASI HESABI:"
)

add_header("6.3. Yedek Parçaların, Aletlerin ve Manliftin Teslim Edilmemesi Halinde Yaptırımlar", level=2)
add_para("1. Kabul Noksanları Kesintisi (%5 Bloke): YİGŞ Md. 41 gereğince teslim edilmeyen alet, cihaz ve yedek parçaların bedeli tespit edilerek hakedişten %5 kabul noksanları kesintisi yapılır ve ödenmez.", bullet=True)
add_para("2. İdare Namı Hesabına Satın Alma (YİGŞ Md. 41 & 42): Yüklenici Manlift, Luxmetre, Akü Test Cihazları, Simülatör veya Yedek Parçaları teslim etmezse; İdare bunları doğrudan üreticisinden namı hesabına satın alır. Satın alma bedeli, gümrük, navlun ve %20 cezai idare masrafları yüklenicinin teminatından tahsil edilir.", bullet=True)

add_header("6.4. Eğitimin Yapılmaması veya Eksik Yapılması Halinde Yaptırımlar", level=2)
add_para("Şartnamede emredilen CCNA seviyesi telekom eğitimi, Alstom sinyalizasyon simülatör eğitimi, SCADA ve şalter yazılım eğitimleri yapılmazsa:")
add_para("İdare, personeli yurtiçi/yurtdışı akredite kurumlara veya imalatçı merkezlerine gönderir; tüm kurs, yol ve harcırah bedelleri yüklenici hakedişinden kesilir.", bullet=True)
add_para("Eğitim tutanakları tamamlanmadan Kesin Kabul Tutanağı imzalanmaz.", bullet=True)

add_header("6.5. 20 Günlük İhtarname Süreci ve Sözleşmenin Feshi (4735 Sayılı Kanun Md. 20)", level=2)
add_para("Yüklenicinin taahhütlerini yerine getirmemesi durumunda İdare:")
add_para("1. En az 20 gün süreli noter ihtarnamesi çekerek eksikliklerin giderilmesini talep eder.", bullet=True)
add_para("2. İhtara rağmen yükümlülükler yerine getirilmezse sözleşme tek taraflı feshedilir.", bullet=True)

add_header("6.6. Kesin Teminatın Gelir (İrat) Kaydedilmesi (Sözleşme Md. 10 & 4735 S.K. Md. 22)", level=2)
add_callout(
    "Sözleşmenin feshedilmesi durumunda:\n"
    "• Sözleşme Bedelinin %6'sı oranındaki Kesin Teminat Mektubu:\n"
    "  338.272.200,00 x %6 = 20.296.332,00 EURO (Yirmi Milyon İki Yüz Doksan Altı Bin Üç Yüz Otuz İki Euro)\n"
    "• Hüküm almaya gerek kalmaksızın HAZİNEYE / İDAREYE GELİR (İRAT) KAYDEDİLİR.",
    prefix="TEMİNATIN İRAT KAYDEDİLMESİ:"
)

add_header("6.7. Kamu İhalelerinden Yasaklama Kararı (4735 S.K. Md. 26 & 4734 S.K. Md. 58)", level=2)
add_para("Sözleşmesi feshedilen Yüklenici şirket ve ortakları hakkında Kamu İhale Kurumu (KİK) tarafından 1 yıldan 2 yıla kadar TÜM KAMU İHALELERİNE KATILMAKTAN YASAKLAMA KARARI verilir.", bullet=True)

desktop_dir = r"C:\Users\yvzta\OneDrive\Masaüstü"
out_path = os.path.join(desktop_dir, "IKITELLI_ATAKOY_2_YILLIK_BAKIM_GOZETIM_VE_YAPTIRIM_RAPORU.docx")
doc.save(out_path)
print(f"Report updated successfully to {out_path}")
