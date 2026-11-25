# ⚖️ InsaatAudit — AI-Powered Construction Claim & Regulation Audit System

A LangGraph-based **multi-agent audit platform** that reviews construction
contractor petitions (time extensions, price adjustments, new unit rates,
revised schedules, material approvals, safety & SAT reports...) and progress-payment
documents against Turkish public procurement law, project contract specifications,
and international engineering standards.

> **Türkçe özet için aşağı kaydırın** — detaylı Türkçe dokümantasyon için
> [README_TR.md](README_TR.md) dosyasına bakın.

## ✨ What It Audits Against

| Scope | Sources |
|---|---|
| 🇹🇷 Procurement law | 4734 (KİK), 4735 (+Geçici 5/6/7), YİGŞ (Yapım İşleri Genel Şartnamesi), consultancy general specifications, 4686 (MTK), 6098 (TBK) |
| 📜 Regulations | KİK General Communique, 2013/5215–5217 Price Adjustment Decrees, Benzer İş, Mahalli İdareler (11509), Fire Safety (2007/12937), OHS (18928), Excavation, Earthquake/Tunnel Decrees |
| 🌍 Engineering standards | CENELEC, IEC, NFPA 130, EN 50126/128/129, EN 50122/50163, IEEE 1474 (CBTC), EN 54, Eurocode, TBDY 2018, TS 500, UIC 60 |

Every document carries a **procurement type** (`yapim` / `danismanlik` / `ortak`),
**subsystem tag** (signalling/CBTC, catenary & electrification, low-current & SCADA,
fire & ventilation, elevators, railway superstructure, construction & geotechnics),
and canonical **standard codes** so agents retrieve only the norms relevant to the claim.

## ✨ Key Capabilities

- **Physically Separated Dual Vector DB Architecture**:
  - `vector_db/` (`insaat_mevzuat`): **100% pure normative rules** — Layer 1 official legislation/standards + Layer 2 project contracts & specifications (BGE-M3 + BM25 + BGE-Reranker-v2-m3).
  - `vector_db_yazismalar/` (`proje_yazismalari`) + `data/project_graph.db` (SQLite): dedicated physically isolated store for Layer 3 contractor/administration/consultant correspondence, `İlgi:` reference graphs, and human-approved state machine (`confirmed_by_human=1`). Contractor claims can **never** pollute normative rule lookups.
- **6-Node LangGraph Multi-Agent Pipeline** (`2_agents_graph.py`):
  `reader` → `case_builder` → `router` → `experts` (Hop-1 + loop-safe Hop-2 standard expansion) → `chief_auditor` → `citation_verifier`.
- **Version-Protected Legislation Sync** (`scripts/sync_mevzuat.py`):
  Checks 35 official sources from `mevzuat.gov.tr` & `ihale.gov.tr`, archives superseded versions, and produces clause-level diff reports.
- **Visual Audit Studio** (`ui_app.py`): NiceGUI + Apache ECharts + Cytoscape.js studio with live 6-node streaming, correspondence graph approval queue, memory tree inspector, and formatted `.docx` export.
- **LLM Provider Switch**: Google Gemini (`gemini-2.5-flash`) or Anthropic Claude via `.env`.

## 🚀 Getting Started

```bash
pip install -r requirements.txt
cp .env.example .env                                              # add GOOGLE_API_KEY or ANTHROPIC_API_KEY

python 1_ingest.py                                                # ingest Layer 1 + Layer 2 into vector_db/
python ingest_history.py --project <project_id>                   # ingest Layer 3 letters into vector_db_yazismalar/ + project_graph.db
python 2_agents_graph.py <petition.pdf> --project <project_id>    # run 6-node multi-agent audit
python ui_app.py                                                  # launch visual studio on http://127.0.0.1:8080
```

## 📁 Project Structure

```text
data/
├── 1_genel_mevzuat_ve_standartlar/   Layer 1: official laws, regulations & discipline standards
├── 2_proje_evraklari/                Layer 2: per-project contracts & specifications (5-pillar layout)
├── 3_yuklenici_talepleri/            Layer 3: per-project correspondence & contractor claims
├── project_graph.db                  SQLite 4-table correspondence graph & state machine
└── raporlar/                         Generated .md / .docx audit reports
vector_db/                            ChromaDB #1: Pure Normative DB (insaat_mevzuat)
vector_db_yazismalar/                 ChromaDB #2: Physically Isolated Correspondence DB (proje_yazismalari)
utils/                                Config, OCR/DOCX parser, dual-DB retriever, graph & UI services
scripts/                              Legislation sync, human review queue, closed-loop reply & test suites
```

## 📚 Documentation

Detailed Turkish documentation (architecture, dual-DB isolation, agent graph, ingest & closed-loop workflows): **[README_TR.md](README_TR.md)**

## 📄 License

All rights reserved. Professional engineering tool — see repository settings.

---

## 🇹🇷 Türkçe Özet

**InsaatAudit**, kamu yapım ve danışmanlık sözleşmelerinde yüklenici dilekçeleri
(süre uzatımı, ek fiyat farkı, yeni birim fiyat, revize iş programı, malzeme onayı,
test/SAT raporları...) ile hakediş evraklarını; **4734/4735 sayılı kanunlar, YİGŞ,
idari-teknik şartnameler** ve **CENELEC, IEC, NFPA, UIC, Eurocode** standartlarına
göre inceleyen **LangGraph tabanlı 6 düğümlü çoklu ajan denetim platformudur**.

- **Fiziksel Çift Vektör Veritabanı İzolasyonu:**
  - `vector_db/` (`insaat_mevzuat`): Yalnızca **Katman 1 Mevzuat/Standartlar + Katman 2 Proje Sözleşme/Şartnameleri** (%100 saf bağlayıcı kurallar).
  - `vector_db_yazismalar/` (`proje_yazismalari`) + `data/project_graph.db`: Yalnızca **Katman 3 Yüklenici/İdare/Müşavir Yazışmaları**, `İlgi:` soy ağacı ve insan onaylı durum makinesi.
- **Disiplin & İhale Türü Etiketli Norm Havuzu:** Sinyalizasyon (CBTC), cer gücü, zayıf akım/SCADA, yangın/havalandırma, asansör, demiryolu üstyapısı, inşaat/geoteknik.
- **Görsel Denetim Stüdyosu (`ui_app.py`):** NiceGUI + Apache ECharts + Cytoscape.js ile canlı 6 düğümlü akış izleme, bilgi ağacı, onay kuyruğu ve `.docx` rapor çıktısı.
- **Detaylı Türkçe Dokümantasyon:** [README_TR.md](README_TR.md)
