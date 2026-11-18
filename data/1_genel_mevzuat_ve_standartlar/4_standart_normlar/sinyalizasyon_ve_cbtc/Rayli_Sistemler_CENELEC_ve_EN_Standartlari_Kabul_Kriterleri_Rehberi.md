# RAYLI SİSTEMLER VE METRO PROJELERİNDE CENELEC, EN VE ULUSLARARASI STANDARTLAR KABUL REHBERİ

## 1. Yüklenicinin Standartlara Uygunluğu İspat Külfeti (Hukuki ve Sözleşmesel İlke)
Metro yapım ve elektromekanik sözleşmelerinde (YİGŞ ve Proje Teknik Şartnameleri):
1. **İspat Külfeti Yükleniciye Aittir:** İdare mühendisi veya kontrol teşkilatı, uluslararası standartları (EN, ISO, IEC, DIN, UIC) satın alıp dedektif gibi satır satır aramak zorunda DEĞİLDİR. Şartnameler uyarınca; önerilen malzeme, ekipman veya sistemin ilgili standartlara uygun olduğunu ispatlama yükümlülüğü tamamen yükleniciye aittir.
2. **Madde Madde Uygunluk Matrisi (Clause-by-Clause Compliance Matrix):** Yüklenici, sunduğu her sistem ve malzeme onay dosyasında (Tasarım Tanım Raporu, Malzeme Onay Formu); şartnamede atıf yapılan standardın her bir maddesini tablo halinde listelemek, kendi tasarımının bu maddeyi nasıl karşıladığını açıklamak ve bunu akredite test raporuyla çapraz referanslamak zorundadır.
3. **Akredite Laboratuvar ve Kuruluş Şartı (TÜV, Dekra, TSE vb.):** Yüklenicinin kendi beyanı yeterli değildir. İlgili standarda göre testlerin bağımsız ve akredite (ISO/IEC 17025) laboratuvarlarda yapıldığına dair test raporu (Type Test Report / Rutin Test Raporu) sunulmalıdır.
4. **ISA (Independent Safety Assessor) Onayı:** Sinyalizasyon ve emniyet kritik sistemlerde (SIL 3, SIL 4), uluslararası akredite bir ISA kuruluşu (örn: ITALCERTIFER, TÜV SÜD, TÜV Rheinland vb.) tarafından hazırlanan Emniyet Değerlendirme Raporu (Safety Assessment Report) olmadan sistem kabulü yapılamaz.

---

## 2. Temel Demiryolu & Metro CENELEC / EN Standartları ve Kabul Kriterleri

### EN 50126: RAMS (Güvenilirlik, Kullanılabilirlik, Bakım Yapılabilirlik, Emniyet)
* **Kapsam:** Tüm demiryolu sisteminin yaşam döngüsü boyunca (Kavramsal tasarımdan işletmeden çekilmeye kadar) RAMS yönetimi.
* **Kabul Kriterleri:**
  * **V-Modeli Yaşam Döngüsü:** Tasarım, doğrulama (verification) ve geçerleme (validation) aşamalarının V-Modeli diyagramına uygun dokümante edilmesi.
  * **Tehlike Kaydı (Hazard Log):** Sistemdeki tüm olası tehlikelerin tanımlanması, risk matrisine işlenmesi ve geçici kabule kadar tüm kritik maddelerin kapatılmış (Closed) veya kabul edilebilir seviyeye indirilmiş (ALARP - As Low As Reasonably Practicable) olması.

### EN 50128: Demiryolu Kontrol ve Koruma Sistemleri İçin Yazılım
* **Kapsam:** Sinyalizasyon, anklaşman (interlocking), tren koruma (ATP) ve araç üstü (ATC) yazılımları.
* **Kabul Kriterleri:**
  * **SIL Seviyesi Doğrulaması:** Emniyet kritik sinyal yazılımlarının **SIL 4 (Safety Integrity Level 4)** seviyesine sahip olması zorunludur.
  * **Bağımsız V&V (Doğrulama ve Geçerleme):** Yazılımı geliştiren ekipten tamamen bağımsız bir test ekibi tarafından yazılım doğrulama testlerinin yapılmış olması.

### EN 50129: Demiryolu İçin Elektronik Emniyet Sistemleri
* **Kapsam:** Sinyalizasyon donanımı, emniyet mimarisi ve güvenlik kanıtı (Safety Case).
* **Kabul Kriterleri:**
  * **Safety Case (Emniyet Dosyası) Yapısı:** Yüklenici, 6 ana bölümden oluşan Safety Case sunmak zorundadır:
    1. Sistem Tanımı
    2. Kalite Yönetim Raporu
    3. Emniyet Yönetim Raporu
    4. Fonksiyonel ve Teknik Emniyet Raporu (Fail-Safe prensipler, MTBF, MTTR hesapları)
    5. İlgili Emniyet Şartları (Safety Related Application Conditions - SRAC)
    6. Sonuç ve ISA Uygunluk Görüşü.
  * **Hata Güvenliği (Fail-Safe):** Herhangi bir donanım arızasında (örneğin sinyal lambası kesilmesi, işlemci arızası) sistemin derhal en güvenli duruma (trenleri acil durdurma ve sinyalleri kırmızıya çekme) geçmesi şarttır.

### EN 50159: Demiryolu İletişim, Sinyalizasyon ve İşleme Sistemleri - İletim Sistemlerinde Emniyetle İlgili Haberleşme
* **Kapsam:** Ray boyu kontrol merkezleri ile araç üstü sistemler arasındaki kablosuz (WLAN/LTE-R) ve kablolu sinyalizasyon iletişimi.
* **Kabul Kriterleri:**
  * Açık İletim Sistemleri (Open Transmission Systems) için; mesaj kaybı, gecikme, yetkisiz müdahale (siber saldırı), mesaj sırasının bozulması ve yinelenmesi gibi tehditlere karşı kriptografik şifreleme ve emniyet protokollerinin (kriptolu zaman damgası, sequence number, MAC/HMAC) bulunması.

### EN 50121: Demiryolu Uygulamaları - Elektromanyetik Uyumluluk (EMC)
* **Kapsam:** Metro hatlarında cer akımının (750V / 1500V DC 3. ray veya katener) sinyalizasyon, haberleşme ve istasyon elektronik sistemleri üzerinde parazit oluşturmaması.
* **Kabul Kriterleri:**
  * EN 50121-3-2 (Araç üstü donanım emisyon ve bağışıklık testleri), EN 50121-4 (Sinyalizasyon ve telekomünikasyon donanımı bağışıklık sertifikaları) akredite laboratuvar onaylı olmalıdır.

### EN 50122: Demiryolu Uygulamaları - Sabit Tesisler - Elektriksel Güvenlik ve Topraklama
* **Kapsam:** Yolcu ve personel dokunma gerilimi güvenliği, ray dönüş akımı ve kaçak akım korozyonu (Stray Current).
* **Kabul Kriterleri:**
  * DC cer cer güç sistemlerinde tünel betonarme demirlerine ve istasyon boru hatlarına kaçak akım sızmasını önleyen kaçak akım izleme ve drenaj sistemlerinin bulunması.

### IEC 62290 / EN 62267: Raylı Transit Kentsel Otomasyon Sistemleri (CBTC & GoA)
* **Otomasyon Dereceleri (Grade of Automation):**
  * **GoA 1:** Manuel sürüş (ATP korumalı)
  * **GoA 2:** Yarı otomatik sürüş (ATO - Sürücü kapıları kapatır ve hareketi başlatır)
  * **GoA 3:** Sürücüsüz sürüş (Trende görevli personel var, kabin yok)
  * **GoA 4:** Tam Otomatik Sürücüsüz İşletme (İkitelli-Ataköy gibi hatlarda: Trende personel yok, peron ayırıcı kapılar - PAK/PSD ve otomatik depolama/manevra).

---

## 3. İdarenin Denetim Stratejisi (Yüklenici Karşısında Ne Yapılmalı?)

1. **Yüklenici "Standartlar paralı, bende yok" derse:**
   - İdare cevabı: *"Sözleşme ve Teknik Şartname hükümleri uyarınca teklif ettiğiniz ürünün şartname standartlarına uygunluğunu akredite test raporu ve madde madde uygunluk matrisi ile tevsik etme sorumluluğu yükleniciye aittir. Belge sunuluncaya kadar malzeme/tasarım onayı BEKLETİLMİŞTİR."*
2. **Yüklenici kendi iç test raporunu sunarsa:**
   - İdare cevabı: *"Sunulan test raporu yüklenici iç raporu olup, ISO/IEC 17025 akreditasyonuna sahip bağımsız üçüncü taraf test kuruluşu (TÜV, Dekra vb.) veya TSE onaylı Tip Test Raporu (Type Test) sunulması zorunludur."*
3. **ISA Raporunda Açık Madde Varsa:**
   - ISA raporunda "Open Item" veya "Unresolved Hazard" varsa, geçici kabul komisyonu sistemi işletmeye açamaz. Emniyet riskinin kapatıldığına dair ISA tamamlama zeyilnamesi (Addendum) istenmelidir.
