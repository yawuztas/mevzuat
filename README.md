# 🏗️ InsaatAudit - Yapay Zeka Destekli İnşaat Hakediş ve Mevzuat Denetim Sistemi

Bu sistem, kamu yapım ve danışmanlık/müşavirlik sözleşmelerinde yüklenicilerin sunduğu dilekçeleri (süre uzatımı, ek fiyat farkı, yeni birim fiyat, revize iş programı, malzeme onayı, test ve emniyet raporları vb.) ve hakediş evraklarını; **4734 Sayılı Kamu İhale Kanunu (KİK)**, **4735 Sayılı Kamu İhale Sözleşmeleri Kanunu**, **Yapım İşleri Genel Şartnamesi (YİGŞ)**, **Danışmanlık Hizmet İşleri Genel Şartnamesi**, İdari ve Teknik Şartnameler ile uluslararası mühendislik standartları (CENELEC, IEC, NFPA, UIC, Eurocode) ışığında inceleyen **LangGraph tabanlı çoklu ajan (Multi-Agent)** denetim platformudur.

---

## 🏛️ Mimari Özeti (3 Seviyeli Veri İzolasyonu + İhale Türü & Disiplin Etiketleme)

```
InsaatAudit/
│
├── data/
│   ├── 1_genel_mevzuat_ve_standartlar/               # [SEVİYE 1 - GLOBAL] Resmi Tam Metin Mevzuat & Disiplin Normları
│   │   ├── .mevzuat_registry.json                    # Resmi kaynak sürüm & body_sha256 kayıt defteri
│   │   ├── 1_kanunlar/                               # 4734, 4735 (+Geçici 5/6/7), 4686, 6098, 6100, 5018, 6085, 6331, 4857, 2872
│   │   ├── 2_sozlesme_ve_genel_sartnameler/
│   │   │   ├── yapim_isleri/                         # YİGŞ tam metin, Yapım Uygulama Yön., Tip Sözleşme, Yapım Muayene-Kabul
│   │   │   └── danismanlik_ve_musavirlik/            # Danışmanlık & Hizmet Uygulama Yön., Tip Sözleşme, Muayene-Kabul, 2013/5215 FF
│   │   ├── 3_tebligler_ve_kararnameler/              # KİK Genel Tebliği, 2013/5217-5216 FF, Benzer İş, Başvurular, Mahalli İdareler (11509), Yangın (2007/12937), İSG (18928), Hafriyat (5401), Deprem/Tünel (34909, 34912)
│   │   ├── 4_standart_normlar/                       # Disiplin Bazlı Mühendislik Normları [subsystem etiketli]
│   │   │   ├── sinyalizasyon_ve_cbtc/                # EN 50126/128/129, IEEE 1474 [subsystem='sinyalizasyon_cbtc']
│   │   │   ├── cer_gucu_ve_elektrifikasyon/          # EN 50122, EN 50163, 750V/1500V DC [subsystem='cer_gucu_ve_elektrifikasyon']
│   │   │   ├── zayif_akim_ve_scada/                  # SCADA, TETRA, CCTV, EN 54, PSD [subsystem='zayif_akim_ve_scada']
│   │   │   ├── yangin_ve_havalandirma/               # NFPA 130, EN 12101, TVS Jet Fan [subsystem='havalandirma_ve_yangin_tvs']
│   │   │   ├── asansor_ve_yuruyen_merdiven/          # EN 115-1, EN 81-20/50/70/72 [subsystem='asansor_ve_yuruyen_merdiven']
│   │   │   ├── demiryolu_ustyapi_ve_ray/             # EN 13674, UIC 60, Slab Track [subsystem='demiryolu_ustyapi_ve_ray']
│   │   │   ├── insaat_ve_geoteknik/                  # TBDY 2018, TS 500, Eurocode 2/7, TBM/NATM
│   │   │   └── genel_rayli_sistemler/                # AYGM Katalogları ve Çok Disiplinli Rehberler
│   │   └── 5_standart_formlar/                       # Şantiye defteri, yeşil defter, hakediş ve kabul şablonları
│   │
│   ├── _arsiv/mevzuat_surumleri/                     # Mevzuat güncellendiğinde eski sürümlerin korunduğu tarihli arşiv
│   ├── 2_proje_evraklari/                            # [SEVİYE 2 - PROJE İZOLASYONU] Projeye Özgü Sözleşme ve Şartnameler
│   │   ├── ikitelli_atakoy_metro/                    # M9 Hattı (318 sf Sözleşme, 660 sf Teknik Şartname, Test PDF'leri)
│   │   ├── kirazli_halkali_metro/                    # Kirazlı-Halkalı Metro Hattı (Sözleşme, İdari, Teknik, BIM)
│   │   └── ikitelli_atakoy_musavirlik/               # Müşavirlik Sözleşmesi ve İdari Şartnameleri
│   │
│   ├── 3_yuklenici_talepleri/                        # [SEVİYE 3 - TALEPLER] Denetlenecek Yüklenici Dilekçe ve Raporları
│   │   ├── ikitelli_atakoy_metro/                    # Alstom hassas duruş test raporu, ISA emniyet raporu
│   │   └── ornek_proje/                              # Süre uzatımı ve fiyat farkı talep dilekçeleri
│   │
│   └── raporlar/                                     # Üretilen nihai resmi denetim raporları (.md ve .docx)
│   └── project_graph.db                              # SQLite 4 tablolu Yazışma Çizgesi & Durum Makinesi
│
├── vector_db/                                        # ChromaDB yerel vektör veri tabanı + ingested_manifest.json
├── 1_ingest.py                                       # Artımlı, İhale Türü, Disiplin & Standart Etiketli Vektörleştirme
├── 2_agents_graph.py                                 # LangGraph 6 Düğümlü Çoklu Ajan + Vaka Hafızası Denetim Akışı
├── ingest_history.py                                 # Geçmiş Yazışmaları SQLite + Chroma'ya Besleyici (2 Turlu İlgi)
├── SISTEM_MIMARISI_VE_CALISMA_REHBERI.docx           # Sistemin tüm çalışma mantığını anlatan yaşayan teknik rehber
├── scripts/
│   ├── sync_mevzuat.py                               # Katman 1 resmi mevzuat kontrol, sürüm arşivli diff ve senkronizasyon CLI'ı
│   ├── review_queue.py                               # Eksik tarih/sayılı kartlar için insan onay CLI'ı
│   ├── close_loop_reply.py                           # İdare/Müşavir cevabı kapalı döngü kayıt & durum kapatma CLI'ı
│   └── run_pilot_eval.py                             # 25 gerçek yazılık Adım 5 pilot ölçüm aracı
└── utils/
    ├── config.py                                     # Dizin yolları, ortam değişkenleri ve LLM ayarları
    ├── text_tr.py                                    # Türkçe karakter duyarlı dönüşüm motoru (tr_lower, ascii_fold)
    ├── standards.py                                  # EN/IEC/TS EN/ISO/NFPA kanonik standart çıkarıcı
    ├── mevzuat_sync.py                               # mevzuat.gov.tr & ihale.gov.tr senkronizasyon + madde diff + arşiv motoru
    ├── project_db.py                                 # SQLite yazışma grafiği, CTE zinciri ve onaylı durum makinesi
    ├── card_extractor.py                             # Kimlik Kartı (Regex + DMY dateparser + instructor + langextract)
    ├── case_context_builder.py                       # Vaka Hafızası bağlam toplayıcı ([KANIT TÜRÜ] ağırlıklı, 90k bütçe)
    ├── closed_loop.py                                # Cevap eşleştirme & durum geçiş önerici (confirmed_by_human=1)
    ├── retriever.py                                  # ChromaDB + BM25 + BGE-M3 + Reranker + Hop-2 Standart Genişletme
    └── document_parser.py                            # Hibrit Triage (Docling GPU / PyMuPDF / RapidOCR CUDA + .cache_ocr)
```

---

## 🚀 Çalışma Akışı (6 Düğümlü LangGraph + Vaka Hafızası Mimarisi)

```
[Yüklenici Evrakı]
        │
        ▼
  [1. Reader Node] ────────► Proje Kapsamı (project_id) & İhale Türü (yapim / danismanlik) Tespiti
        │
        ▼
  [2. Case Builder Node] ──► Kimlik Kartı + SQLite CTE İlgi Zinciri + Kanıt Ağırlığı ([RESMİ POZİSYON / İDDİA])
        │
        ▼
  [3. Router Node] ────────► Talep Türü, Uzman Domainler & Hedef Disiplinler (target_subsystems)
        │
   ┌────┴───────────────────────┬────────────────────────┬────────────────────────┐
   ▼                            ▼                        ▼                        ▼
[Mevzuat Uzmanı]         [İdari Uzmanı]          [İnşaat Uzmanı]        [Elektromekanik Uzmanı]
   │                            │                        │                        │
   └──────────────┬─────────────┴────────────────────────┴────────────────────────┘
                  │  (Hop-1 Disiplin Filtreli Hibrit Arama + Döngü Korumalı Hop-2 Standart Genişletme)
                  ▼
      [5. Baş Denetçi / Sentez]
                  │
                  ▼
    [6. Citation Verifier Node] ──► Madde, Fiziksel Sayfa & Kanonik Standart Doğrulaması
```

1. **Reader Node**: Evrakı okur, hangi projeye (`project_id`) ve hangi ihale türüne (`yapim` veya `danismanlik`) ait olduğunu otomatik tespit eder.
2. **Case Builder Node (Adım 4)**: Yazıdaki `Tarih/Sayı/İlgi` alanlarını çıkarır; `project_graph.db` üzerinden özyinelemeli CTE ile önceki yazışma zincirini, açık talepleri ve geçmiş İdare/Müşavir cevaplarını `[KANIT TÜRÜ]` ağırlığıyla 90.000 karakterlik bütçeye derler.
3. **Router Ajanı**: Yüklenici dilekçesini veya teknik raporu analiz eder; görevlendirilecek uzman ajanları (`mevzuat`, `idari`, `elektromekanik`, `insaat`) ve nokta atışı alt disiplinleri (`sinyalizasyon_cbtc`, `cer_gucu_ve_elektrifikasyon`, `sure_uzatimi_ve_mucbir_sebep` vb.) belirler.
4. **Uzman Ajanlar & Hop-2 Standart Korumalı Hibrit Arama**: Her uzman ajan uyumlu ihale türü ve disiplin sınırları içinde **BM25 + BGE-M3 + BGE-Reranker-v2-m3** (Hop 1) çalıştırır; çekilen şartnamede atıf yapılan standartları döngü kilidiyle (`MAX_HOP2_STANDARDS=3`) ilgili teknik normlardan (Hop 2) tamamlar.
5. **Baş Denetçi (Sentez)**: Uzman görüşlerini ve vaka hafızasındaki geçmiş İdare pozisyonlarını birleştirip resmi denetim raporunu üretir.
6. **Citation Verifier (Doğrulama Düğümü)**: Raporda atıf yapılan tüm kanun, şartname maddesi, poz ve kanonikleştirilmiş standartları (`extract_standard_refs`) veritabanıyla karşılaştırır; fiziksel sayfa numaralarını ayırt ederek doğrular.

---

## ⚙️ Kurulum ve Kullanım

### 1. Katman 1 Resmi Mevzuat Güncelleme Kontrolü ve İndeksleme (`sync_mevzuat.py` + `1_ingest.py`)
`mevzuat.gov.tr` ve `ihale.gov.tr` (KİK) kaynaklarında değişiklik kontrolü yapmak için:
```powershell
.\venv\Scripts\python.exe -X utf8 scripts\sync_mevzuat.py --check --deep
```
Güncellenen mevzuatı eski sürümü `data/_arsiv/mevzuat_surumleri/` altına yedekleyip madde-bazlı fark (`diff`) raporuyla senkronize etmek ve ChromaDB'yi güncellemek için:
```powershell
.\venv\Scripts\python.exe -X utf8 scripts\sync_mevzuat.py --sync --ingest
```
Yalnızca yeni/değişen dokümanları artımlı (incremental) olarak indekslemek veya veritabanını sıfırlamak için:
```powershell
.\venv\Scripts\python.exe -X utf8 1_ingest.py
.\venv\Scripts\python.exe -X utf8 1_ingest.py --reset
```

### 2. Geçmiş Yazışma Arşivi, Onay Kuyruğu & Kapalı Döngü (`Adım 3–5`)
```powershell
.\venv\Scripts\python.exe -X utf8 ingest_history.py "<yazisma_klasoru>" --project ikitelli_atakoy_metro
.\venv\Scripts\python.exe -X utf8 scripts\review_queue.py
.\venv\Scripts\python.exe -X utf8 scripts\close_loop_reply.py --project ikitelli_atakoy_metro --file "<idare_cevabi>" --confirm
.\venv\Scripts\python.exe -X utf8 scripts\run_pilot_eval.py --limit 25
```

### 3. Çoklu Ajan Denetiminin Çalıştırılması (`2_agents_graph.py`)
```powershell
.\venv\Scripts\python.exe -X utf8 2_agents_graph.py "data/3_yuklenici_talepleri/ikitelli_atakoy_metro/sinyalizasyon/alstom_atc_onboard_precision_stop_test_raporu.md"
```
