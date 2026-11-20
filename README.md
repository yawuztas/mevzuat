# ⚖️ InsaatAudit — AI-Powered Construction Claim & Regulation Audit System

A LangGraph-based **multi-agent audit platform** that reviews construction
contractor petitions (time extensions, price adjustments, new unit rates,
revised schedules, material approvals, safety reports ...) and progress-payment
documents against Turkish public procurement law and international engineering
standards.

> **Türkçe özet için aşağı kaydırın** — detaylı Türkçe dokümantasyon için
> [README_TR.md](README_TR.md) dosyasına bakın.

## ✨ What It Audits Against

| Scope | Sources |
|---|---|
| 🇹🇷 Procurement law | 4734 (KİK), 4735, YİG (Yapım İşleri Genel Şartnamesi), consultancy general specifications |
| 📜 Regulations | KİK General Communique, 2013/5215-5217 FF, Benzer İş, mahalli idareler (11509), fire safety (2007/12937), OSG (18928), excavation, earthquake/tunnel decrees |
| 🌍 Engineering standards | CENELEC, IEC, NFPA 130, EN 50126/128/129, EN 50122/50163, IEEE 1474 (CBTC), EN 54, Eurocode, TBDY 2018, TS 500, UIC 60 |

Every document carries a **subsystem tag** (signalling/CBTC, catenary &
electrification, low-current & SCADA, fire & ventilation, elevators, railway
superstructure, construction & geotechnics) so agents retrieve only the norms
relevant to the claim.

## ✨ Key Capabilities

- **Multi-agent graph** (`2_agents_graph.py`): orchestrates legislation
  retrieval, claim classification, norm matching and report drafting agents
- **3-level data isolation** (`data/`): global legislation → project documents
  → standard forms, with a SHA-256 versioned registry (`.mevzuat_registry.json`)
- **Vector search** (`vector_db/`): ChromaDB with BAAI/bge-m3 embeddings and
  bge-reranker-v2.5 reranking
- **Visual audit studio** (`ui_app.py`): NiceGUI + ECharts + Cytoscape UI with
  live multi-node streaming and `.docx` export
- **Final report generation** (`generate_final_report.py`)
- **LLM provider switch**: Anthropic Claude or Google Gemini via `.env`

## 🚀 Getting Started

```bash
pip install -r requirements.txt
cp .env.example .env          # add GOOGLE_API_KEY or ANTHROPIC_API_KEY

python 1_ingest.py            # ingest legislation into the vector DB
python 2_agents_graph.py      # run the audit agent graph
python ui_app.py              # visual audit studio
```

## 📁 Project Structure

```
data/1_genel_mevzuat_ve_standartlar/   global laws & discipline norms
data/2_projeler/                       per-project claim documents
utils/                                 config, extraction, vector utils
vector_db/                             ChromaDB persistence
scripts, tests                         helpers & checks
```

## 📚 Documentation

Detailed Turkish documentation (architecture, data isolation levels, agent
design, ingest pipeline): **[README_TR.md](README_TR.md)**

## 📄 License

All rights reserved. Professional engineering tool — see repository settings.

---

## 🇹🇷 Türkçe Özet

**InsaatAudit**, kamu yapım ve danışmanlık sözleşmelerinde yüklenici dilekçeleri
(süre uzatımı, ek fiyat farkı, yeni birim fiyat, revize program, malzeme onayı...)
ile hakediş evraklarını; **4734/4735 sayılı kanunlar, YİG, idari-teknik
şartnameler** ve **CENELEC, IEC, NFPA, UIC, Eurocode** standartlarına göre
inceleyen **LangGraph tabanlı çoklu ajan denetim platformudur**.

- **3 seviyeli veri izolasyonu:** global mevzuat → proje evrakları → standart formlar;
  SHA-256 sürümlü kayıt defteri
- **Disiplin etiketli norm havuzu:** sinyalizasyon (CBTC), cer gücü, zayıf akım/SCADA,
  yangın/havalandırma, asansör, demiryolu üstyapısı, inşaat/geoteknik
- **Vektör arama:** ChromaDB + BAAI/bge-m3 embedding + bge-reranker
- **Görsel denetim stüdyosu:** NiceGUI + ECharts + Cytoscape ile canlı çok-düğüm
  akış izleme ve `.docx` rapor çıktısı
- **LLM seçimi:** Anthropic Claude veya Google Gemini (`.env` ile)

**Kullanım:** `python 1_ingest.py` (mevzuat ingest) → `python 2_agents_graph.py`
(denetim) → `python ui_app.py` (stüdyo). Ayrıntılı dokümantasyon:
[README_TR.md](README_TR.md)
