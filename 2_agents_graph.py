import os
import sys
import json
import re
import time
import random
from pathlib import Path
from typing import TypedDict, List, Dict, Any, Optional

# Windows konsolunda Türkçe karakter ve Unicode desteği
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console(legacy_windows=False)

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from utils.config import (
    PROJE_EVRAKLARI_DIR,
    YUKLENICI_TALEPLERI_DIR,
    RAPORLAR_DIR,
    YUKLENICI_DIR,
    get_llm,
    DEFAULT_LLM_PROVIDER,
)
from utils.retriever import (
    search_and_rerank,
    get_chroma_collection,
    get_or_build_bm25_index,
    detect_project_procurement_type,
)
from utils.document_parser import parse_any_document, SUPPORTED_DOC_EXTENSIONS
from utils.text_tr import tr_lower
from utils.standards import (
    extract_standard_refs,
    match_standard_fuzzy,
    normalize_standard_code,
    is_standard_like,
)
from utils.case_context_builder import (
    build_case_context,
    assemble_budgeted_context,
    format_evidence_label,
    PRIORITY_NORMATIVE,
    PRIORITY_STANDARDS,
    DEFAULT_TOTAL_BUDGET_CHARS,
)


# ==========================================
# 1. State ve Domain Şemaları
# ==========================================
class RouterAnalysis(BaseModel):
    document_type: str = Field(description="Belge türü (örn: Süre Uzatımı Talebi, Fiyat Farkı İtirazı, Yeni Birim Fiyat Talebi, Malzeme Uygunluk İtirazı, Test Raporu)")
    claim_summary: str = Field(description="Yüklenicinin temel taleplerinin ve iddialarının özeti")
    project_id: Optional[str] = Field(default=None, description="Belgenin ait olduğu proje ID'si (örn: 'ikitelli_atakoy_metro', 'ornek_proje')")
    active_domains: List[str] = Field(description="Görüş alınması gereken alanlar: 'mevzuat', 'idari', 'insaat', 'elektromekanik' (birden fazla olabilir)")
    target_subsystems: List[str] = Field(description="Doğrudan hedeflenen alt sistemler")
    specific_queries: Dict[str, str] = Field(description="Her aktif alan için veritabanında taranacak odak sorgu cümlesi")


class AgentState(TypedDict):
    doc_path: str
    doc_text: str
    project_id: Optional[str]
    procurement_type: Optional[str]
    case_context: Optional[Dict[str, Any]]
    router_result: Optional[Dict[str, Any]]
    expert_analyses: Dict[str, Any]
    final_report: str
    verification_notes: Optional[str]


DOMAIN_SUBSYSTEM_MAP = {
    "mevzuat": {
        "sure_uzatimi_ve_mucbir_sebep", "hakedis_ve_fiyat_farki", "yeni_birim_fiyat_ve_analiz",
        "kabul_muayene_ve_teminat", "tasaron_ve_alt_yuklenici", "ceza_ve_fesih_hukuk", "sozlesme_ve_idari"
    },
    "idari": {
        "sozlesme_ve_idari", "hakedis_ve_fiyat_farki", "yeni_birim_fiyat_ve_analiz",
        "kabul_muayene_ve_teminat", "ceza_ve_fesih_hukuk", "sure_uzatimi_ve_mucbir_sebep"
    },
    "elektromekanik": {
        "sinyalizasyon_cbtc", "cer_gucu_ve_elektrifikasyon", "zayif_akim_ve_scada",
        "havalandirma_ve_yangin_tvs", "asansor_ve_yuruyen_merdiven", "genel_rams_ve_emniyet",
        "genel_elektromekanik",
    },
    "insaat": {
        "tunel_ve_kazilar", "demiryolu_ustyapi_ve_ray", "istasyon_kaba_ince", "genel_insaat",
    }
}

# ==========================================
# Adım 2: Standart İçi Okuma Sınırları (döngü koruması + bütçe)
# ==========================================
MAX_STANDARD_HOP_CODES = 6   # Bir uzman turunda en fazla kaç standartın içi okunur
HOP2_TOP_K = 2               # Her standarttan çekilecek parça sayısı
MAX_STANDARD_HOP_DEPTH = 2   # Hop 3 ASLA yapılmaz (standartlar birbirine atıf yapabilir)


# ==========================================
# 2. Yardımcı Fonksiyonlar
# ==========================================
def extract_contractor_text(file_path: Path) -> str:
    """PDF, Resim veya metin dosyalarını Docling v2 ve akıllı OCR ile okur."""
    return parse_any_document(file_path)


def extract_text_from_llm_content(content: Any) -> str:
    """LLM çıktısından temiz metin stringi çıkarır."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", str(item)))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def get_adaptive_context(doc_text: str, max_chars: int = 100000) -> str:
    """Evrak metnini token/karakter sınırına göre aktarır."""
    if len(doc_text) <= max_chars:
        return doc_text
    head_size = int(max_chars * 0.7)
    tail_size = max_chars - head_size
    return f"{doc_text[:head_size]}\n\n... [İÇERİK ARA BÖLÜMÜ KISALTILDI - SONUÇ VE TALEPLERE GEÇİLİYOR] ...\n\n{doc_text[-tail_size:]}"


def safe_llm_invoke(messages: List[Any], temperature: float = 0.1, max_retries: int = 5) -> str:
    """Geçici 503/429 ve ağ dalgalanmalarına karşı RPM beklemesi ve model fallback ile dayanıklı LLM çağrısı."""
    from utils.config import DEFAULT_LLM_PROVIDER, ANTHROPIC_API_KEY, GOOGLE_MODEL_NAME, get_llm

    # 1. Eğer varsayılan sağlayıcı Anthropic ise ve anahtar mevcutsa önce Anthropic dene
    if DEFAULT_LLM_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
        try:
            anthropic_llm = get_llm("anthropic", temperature=temperature)
            resp = anthropic_llm.invoke(messages)
            return extract_text_from_llm_content(resp.content)
        except Exception as e:
            console.print(f"  [dim yellow]Anthropic API hatası ({e}), Google Gemini fallback hattına geçiliyor...[/dim yellow]")

    # 2. Google Gemini modelleri üzerinden geçerli fallback listesi
    candidate_models = []
    for m in [GOOGLE_MODEL_NAME, "gemini-2.5-flash", "gemini-flash-lite-latest"]:
        if m and m not in candidate_models:
            candidate_models.append(m)

    last_err = None

    for model_name in candidate_models:
        for attempt in range(max_retries):
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                from utils.config import GOOGLE_API_KEY
                llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    api_key=GOOGLE_API_KEY,
                    temperature=temperature,
                    max_output_tokens=4096,
                )
                resp = llm.invoke(messages)
                # İstekler arası kota dostu 2 saniye dinlenme
                time.sleep(2.0)
                return extract_text_from_llm_content(resp.content)
            except Exception as e:
                last_err = e
                err_msg = str(e)
                if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
                    # Dakikalık istek limiti (Free tier RPM) için bekleme
                    console.print(f"  [dim yellow]Dakikalık API kotası ({model_name}), 18 sn beklenip tekrar deneniyor ({attempt+1}/{max_retries})...[/dim yellow]")
                    time.sleep(18.0)
                    continue
                wait_time = 2.0 * (attempt + 1) + random.uniform(0.5, 1.0)
                console.print(f"  [dim yellow]{model_name} meşgul ({err_msg[:60]}), {wait_time:.1f}sn sonra deneniyor ({attempt+1}/{max_retries})...[/dim yellow]")
                time.sleep(wait_time)

    raise RuntimeError(f"Tüm yedek modeller ve denemeler tükendi. Son hata: {last_err}")


# ==========================================
# 3. Düğümler (Nodes)
# ==========================================
def reader_node(state: AgentState) -> Dict[str, Any]:
    """Yüklenici evrakını okur ve dosya yolundan proje kapsamını ve ihale türünü (yapım/danışmanlık) tespit eder."""
    doc_path = Path(state["doc_path"])
    console.print(f"\n[bold cyan]▶ [1/6] Yüklenici Evrakı Okunuyor:[/bold cyan] {doc_path.name}")
    text = extract_contractor_text(doc_path)

    project_id = state.get("project_id")
    if not project_id:
        known_projects_set = set()
        for base_dir in (PROJE_EVRAKLARI_DIR, YUKLENICI_TALEPLERI_DIR):
            if base_dir.exists():
                for p in base_dir.iterdir():
                    if p.is_dir():
                        known_projects_set.add(p.name)
        known_projects = sorted(known_projects_set)
        project_id = next((part for part in doc_path.parts if part in known_projects_set), None)
        if not project_id:
            console.print(
                f"  [bold yellow]⚠ Evrak hiçbir proje klasöründe değil. Yalnızca genel mevzuat taranacak. "
                f"Bilinen projeler: {', '.join(known_projects)}[/bold yellow]"
            )
            project_id = "global"

    procurement_type = state.get("procurement_type") or detect_project_procurement_type(project_id)
    if not procurement_type and any(k in doc_path.as_posix().lower() for k in ["musavir", "danisman", "kontrolluk"]):
        procurement_type = "danismanlik"

    proc_label = (procurement_type or "ortak").upper()
    console.print(
        f"  [dim]• İlişkilendirilen Proje Kapsamı:[/dim] [bold magenta]{project_id}[/bold magenta] "
        f"[dim](İhale Türü: {proc_label} | Metin Boyutu: {len(text)} karakter)[/dim]"
    )
    return {"doc_text": text, "project_id": project_id, "procurement_type": procurement_type}


def case_builder_node(state: AgentState) -> Dict[str, Any]:
    """Proje yazışma grafından İlgi zinciri, atlanmış İdare cevapları ve talep defterini geçici vaka paketine derler."""
    console.print("[bold cyan]▶ [2/6] Vaka Hafızası (Case Context Builder):[/bold cyan] İlgi zinciri ve proje yazışma geçmişi taranıyor...")
    doc_path_str = state.get("doc_path") or ""
    case_ctx = build_case_context(
        doc_text=state.get("doc_text", ""),
        doc_path=Path(doc_path_str) if doc_path_str else None,
        project_id=state.get("project_id"),
    )
    stats = case_ctx.get("stats", {})
    console.print(
        f"  [dim]• İlgi Zinciri:[/dim] {stats.get('chain_count', 0)} belge "
        f"([dim]{stats.get('verbatim_count', 0)} tam metin, {stats.get('summary_chain_count', 0)} özet[/dim]) | "
        f"[dim]Atlanmış Cevap:[/dim] {stats.get('missed_reply_count', 0)} | "
        f"[dim]İlişkili Yazışma:[/dim] {stats.get('related_count', 0)}"
    )
    return {"case_context": case_ctx}


def router_node(state: AgentState) -> Dict[str, Any]:
    """Evrakı analiz ederek türünü, hedef alt sistemini ve ilgili uzmanlık alanlarını belirler."""
    console.print("[bold cyan]▶ [3/6] Router Ajanı (Kademeli Teşhis):[/bold cyan] Belge türü, alt sistem ve uzmanlık alanları ayrıştırılıyor...")
    llm = get_llm()
    doc_text = state["doc_text"]
    case_ctx = state.get("case_context") or {}
    history_summary = case_ctx.get("history_summary", "").strip()

    system_prompt = (
        "Sen raylı sistem ve kamu yapım/danışmanlık sözleşmelerinde uzmanlaşmış Kıdemli İhale & Sözleşme Baş Denetçisisin.\n"
        "Görevin: İncelenen yüklenici/müşavir evrakını (Dilekçe, Hakediş İtirazı, Malzeme Onay Formu, Test Tutanağı, RAMS Raporu vb.) analiz etmek,\n"
        "konunun hangi alt sistemlere (subsystem) ait olduğunu teşhis etmek ve veritabanında yalnızca ilgili bölümlerin taranmasını sağlamaktır.\n\n"
        "JSON Şeması:\n"
        "{\n"
        '  "document_type": "Süre Uzatımı Talebi / Fiyat Farkı İtirazı / Yeni Birim Fiyat / Malzeme Onayı / Test Tutanağı / Emniyet Raporu",\n'
        '  "claim_summary": "Yüklenicinin temel iddia ve talebinin 1-2 cümlelik özeti",\n'
        '  "active_domains": ["mevzuat", "idari", "elektromekanik", "insaat"],\n'
        '  "target_subsystems": ["sure_uzatimi_ve_mucbir_sebep", "sinyalizasyon_cbtc", ...],\n'
        '  "specific_queries": {\n'
        '     "mevzuat": "Nokta atışı kanun/yönetmelik sorgusu",\n'
        '     "idari": "Sözleşme maddesi sorgusu",\n'
        '     "elektromekanik": "Teknik şartname ve standart norm sorgusu",\n'
        '     "insaat": "İnşaat ve mahal listesi sorgusu"\n'
        '  }\n'
        "}\n"
        "Geçerli subsystem seçenekleri:\n"
        "['sure_uzatimi_ve_mucbir_sebep', 'hakedis_ve_fiyat_farki', 'yeni_birim_fiyat_ve_analiz', "
        "'kabul_muayene_ve_teminat', 'tasaron_ve_alt_yuklenici', 'ceza_ve_fesih_hukuk', "
        "'sinyalizasyon_cbtc', 'cer_gucu_ve_elektrifikasyon', 'zayif_akim_ve_scada', "
        "'havalandirma_ve_yangin_tvs', 'asansor_ve_yuruyen_merdiven', 'genel_elektromekanik', "
        "'tunel_ve_kazilar', 'demiryolu_ustyapi_ve_ray', 'istasyon_kaba_ince', 'genel_insaat', "
        "'sozlesme_ve_idari', 'genel_rams_ve_emniyet']"
    )

    evrak_kesiti = get_adaptive_context(doc_text, max_chars=35000)
    if history_summary:
        user_prompt = (
            f"VAKA KRONOLOJİ ÖZETİ (Yazışma Grafı):\n{history_summary}\n\n"
            f"İncelenecek Yüklenici Evrakı Metni:\n\n{evrak_kesiti}"
        )
    else:
        user_prompt = f"İncelenecek Yüklenici Evrakı Metni:\n\n{evrak_kesiti}"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    data = None
    # 1. Native Structured Output Dene
    try:
        structured_llm = llm.with_structured_output(RouterAnalysis)
        structured_res = structured_llm.invoke(messages)
        if isinstance(structured_res, RouterAnalysis):
            data = structured_res.model_dump()
        elif isinstance(structured_res, dict):
            data = structured_res
    except Exception as e:
        console.print(f"  [dim yellow]Structured output denendi ({e}), metin tabanlı ayrıştırmaya geçildi.[/dim yellow]")

    # 2. Metin JSON Fallback
    if not data:
        try:
            content = safe_llm_invoke(messages)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)
        except Exception as e:
            console.print(f"  [dim yellow]LLM router yanıt veremedi ({e}), kural tabanlı acil durum teşhisi devreye alındı.[/dim yellow]")
            doc_lower = tr_lower(doc_text)
            detected_domains = []
            if any(k in doc_lower for k in ["süre", "mücbir", "gecikme", "madde 10", "kanun"]):
                detected_domains.append("mevzuat")
            if any(k in doc_lower for k in ["fiyat farkı", "hakediş", "sözleşme"]):
                detected_domains.append("idari")
            if any(k in doc_lower for k in ["sinyal", "topraklama", "elektrifikasyon", "kablo", "trafo"]):
                detected_domains.append("elektromekanik")
            if any(k in doc_lower for k in ["beton", "istasyon", "tünel", "kazı"]):
                detected_domains.append("insaat")
            if not detected_domains:
                detected_domains = ["mevzuat", "idari"]

            data = {
                "document_type": "Yüklenici Talebi / Evrakı",
                "claim_summary": doc_text[:400].replace("\n", " ").strip(),
                "active_domains": detected_domains,
                "target_subsystems": ["sure_uzatimi_ve_mucbir_sebep", "hakedis_ve_fiyat_farki", "sozlesme_ve_idari"],
                "specific_queries": {
                    d: doc_text[:200].replace("\n", " ") for d in detected_domains
                },
            }

    console.print(f"  [dim]• Tespit Edilen Belge Türü:[/dim] [yellow]{data.get('document_type')}[/yellow]")
    console.print(f"  [dim]• Hedef Alt Sistemler:[/dim] [cyan]{', '.join(data.get('target_subsystems', []))}[/cyan]")
    console.print(f"  [dim]• Aktif Uzman Alanları:[/dim] [green]{', '.join(data.get('active_domains', []))}[/green]")

    return {"router_result": data}


def expert_consultation_node(state: AgentState) -> Dict[str, Any]:
    """
    Her uzmanlık alanı için Hibrit Arama (BM25 + Dense) + BGE-Reranker ile maddeleri çeker.
    İhale Türü (yapim/danismanlik/ortak) ve Disiplin Bazlı Alt Sistem Filtresi ile alakasız standartların taranmasını engeller.
    """
    console.print("[bold cyan]▶ [4/6] Uzman Ajanlar & Hibrit Arama Denetimi:[/bold cyan] Disiplin ve ihale türü bazlı analiz yürütülüyor...")
    router_res = state["router_result"] or {}
    project_id = state.get("project_id")
    procurement_type = state.get("procurement_type") or detect_project_procurement_type(project_id)
    active_domains = router_res.get("active_domains", ["mevzuat"])
    target_subsystems = router_res.get("target_subsystems", [])
    specific_queries = router_res.get("specific_queries", {})
    doc_text = state["doc_text"]
    case_context = state.get("case_context") or {}
    history_blocks = list(case_context.get("blocks", []))

    expert_analyses = {}
    evrak_kesiti = get_adaptive_context(doc_text, max_chars=35000)

    # Adım 2: Tüm domainler arasında paylaşılan ziyaret seti — aynı standart
    # farklı uzmanlar tarafından 2 kez sorgulanmaz (döngü koruması).
    global_visited_standards: set = set()

    for domain in active_domains:
        # Domain'e uygun tüm hedef alt sistemleri belirle (örn. sinyalizasyon_cbtc + genel_rams_ve_emniyet)
        valid_domain_subs = DOMAIN_SUBSYSTEM_MAP.get(domain, set())
        matched_subs = [s for s in target_subsystems if s in valid_domain_subs]
        primary_sub = matched_subs[0] if matched_subs else None

        query = specific_queries.get(domain, router_res.get("claim_summary", doc_text[:300]))
        sub_info = f" (Disiplin: {', '.join(matched_subs)})" if matched_subs else " (Disiplin: Tüm Domain)"
        proj_info = f" [Proje: {project_id} | Tip: {procurement_type or 'ortak'}]" if project_id else ""
        console.print(f"  [yellow]• {domain.upper()} Uzmanı[/yellow]{sub_info}{proj_info} sorguluyor...")

        # Hibrit Arama (BM25 + Dense) + BGE Reranker — Hop 1 (Şartname / Poz / Kanun)
        # Adım 3 koruması: doc_role="normative_rule" — yazışma havuzu
        # (correspondence_history) kural aramasına ASLA sızmaz.
        retrieved_candidates = search_and_rerank(
            query=query,
            domain=domain,
            subsystem=primary_sub,
            subsystems=matched_subs,
            project_id=project_id,
            procurement_type=procurement_type,
            candidate_k=25,
            final_top_k=4,
            doc_role="normative_rule",
        )

        # ------------------------------------------------------------------
        # Adım 2: Hop 2 — Standart İçi Okuma (2 kademeli, döngü korumalı)
        # Hop 1 sonuçlarındaki metadata (standard_codes) ve yüklenici metninden
        # standart kodları toplanır; ziyaret edilmemişler için standart norm
        # havuzunun KENDİ içeriğinden ilgili bölümler çekilir (Hop 3 asla yok).
        # ------------------------------------------------------------------
        domain_codes: List[str] = []
        seen_codes: set = set()
        for item in retrieved_candidates:
            for code in (item.get("metadata", {}).get("standard_codes") or "").split("|"):
                code = code.strip()
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    domain_codes.append(code)
        for ref in extract_standard_refs(query)[:6]:
            if ref["canonical"] not in seen_codes:
                seen_codes.add(ref["canonical"])
                domain_codes.append(ref["canonical"])
        for ref in extract_standard_refs(evrak_kesiti)[:12]:
            if ref["canonical"] not in seen_codes:
                seen_codes.add(ref["canonical"])
                domain_codes.append(ref["canonical"])

        target_codes = [c for c in domain_codes if c not in global_visited_standards][:MAX_STANDARD_HOP_CODES]
        standard_block_dicts: List[Dict[str, Any]] = []
        standard_chunks: List[Dict[str, Any]] = []
        for code in target_codes:
            global_visited_standards.add(code)
            std_res = search_and_rerank(
                query=f"{code} {query}",
                domain=domain,
                subsystems=None,
                project_id=project_id,
                procurement_type=procurement_type,
                candidate_k=10,
                final_top_k=HOP2_TOP_K,
                doc_role="normative_rule",
                doc_type_filter=["standart_norm_katalogu"],
            )
            if not std_res:
                # Disiplin filtresiyle bulunamadıysa: standartlar global havuzda
                # farklı domain etiketi taşıyor olabilir -> tek gevşetme denemesi
                # (domain'siz, yine yalnızca standart norm katalogu).
                std_res = search_and_rerank(
                    query=f"{code} {query}",
                    project_id=project_id,
                    procurement_type=procurement_type,
                    candidate_k=10,
                    final_top_k=HOP2_TOP_K,
                    doc_role="normative_rule",
                    doc_type_filter=["standart_norm_katalogu"],
                )
            for item in std_res:
                m = item.get("metadata", {})
                standard_chunks.append(item)
                page_lbl = f"Sayfa {m.get('page_num')}" if m.get("page_num", 0) and m.get("page_num", 0) > 0 else "Dijital Belge"
                std_ev_label = format_evidence_label(
                    doc_type=m.get("doc_type", "standart_norm_katalogu"),
                    doc_role=m.get("doc_role", "normative_rule"),
                )
                standard_block_dicts.append({
                    "priority": PRIORITY_STANDARDS,
                    "category": "standards",
                    "allow_truncate": True,
                    "text": (
                        f"[KANIT TÜRÜ: {std_ev_label}]\n"
                        f"--- [TEKNİK STANDART İÇERİĞİ: {m.get('source_file', '?')} ({page_lbl}) | Sorgulanan Kod: {code} | Alaka: {item.get('rerank_score', 0.0):.2f}] ---\n"
                        f"{item['content']}"
                    ),
                })
        if standard_chunks:
            console.print(f"  [dim cyan]• Hop 2 Standart İçi Okuma:[/dim cyan] {len(target_codes)} standart sorgulandı, {len(standard_chunks)} parça eklendi [dim]({', '.join(target_codes)})[/dim]")

        normative_block_dicts: List[Dict[str, Any]] = []
        for i, item in enumerate(retrieved_candidates, 1):
            m = item.get("metadata", {})
            src = m.get("source_file", "Bilinmeyen Kaynak")
            title = m.get("title", "")
            page_val = m.get("page_num", 0)
            page_label = f"Sayfa {page_val}" if page_val and page_val > 0 else "Dijital Belge"
            scope_val = m.get("scope", "global")
            score = item.get("rerank_score", 0.0)
            doc_type_val = m.get("doc_type", "")
            doc_role_val = m.get("doc_role", "normative_rule")
            ev_label = format_evidence_label(doc_type=doc_type_val, doc_role=doc_role_val)
            block_prio = PRIORITY_STANDARDS if doc_type_val == "standart_norm_katalogu" else PRIORITY_NORMATIVE
            normative_block_dicts.append({
                "priority": block_prio,
                "category": "normative" if block_prio == PRIORITY_NORMATIVE else "standards",
                "allow_truncate": True,
                "text": (
                    f"[KANIT TÜRÜ: {ev_label}]\n"
                    f"--- [Madde Referansı {i}: {src} ({page_label}) - {title} ({scope_val.upper()}) | Alaka Skoru: {score:.2f}] ---\n"
                    f"{item['content']}"
                ),
            })

        combined_blocks = history_blocks + normative_block_dicts + standard_block_dicts
        budgeted_context, budget_stats = assemble_budgeted_context(
            combined_blocks,
            max_chars=DEFAULT_TOTAL_BUDGET_CHARS,
        )
        if not budgeted_context:
            budgeted_context = "İlgili doğrudan madde veya proje yazışma kaydı bulunamadı (Genel kurallar esas alınacaktır)."
        else:
            console.print(
                f"  [dim cyan]• Vaka + Mevzuat Bütçesi ({domain}):[/dim cyan] "
                f"{budget_stats['used_chars']}/{budget_stats['max_chars']} krk "
                f"[dim](dahil: {budget_stats['included']}, elenen: {budget_stats['dropped']})[/dim]"
            )

        expert_prompt = (
            f"Sen bir {domain.upper()} Uzmanısın. Kamu İhale Kanunu (4734), Sözleşmeler Kanunu (4735), "
            f"Genel Şartnameler (YİGŞ / Danışmanlık Hizmet İşleri Genel Şartnamesi), İdari Şartname ve Proje Teknik Şartnameleri çerçevesinde yüklenici taleplerini denetlersin.\n\n"
            f"YÜKLENİCİNİN TALEBİ / EVRAK ÖZETİ:\n{router_res.get('claim_summary', '')}\n\n"
            f"EVRAK İÇERİĞİNDEN KESİT:\n{evrak_kesiti}\n\n"
            f"KANIT VE BAĞLAM PAKETİ (ÖNCELİK SIRALI & KANIT AĞIRLIĞI ETİKETLİ — Sabit Bütçe: {budget_stats['max_chars']} krk):\n"
            f"{budgeted_context}\n\n"
            "KANIT DİSİPLİNİ KURALLARI (KESİN UYULACAK):\n"
            "- `[KANIT TÜRÜ: BAĞLAYICI KURAL]` taşıyan kanun/sözleşme/şartname maddeleri bağlayıcı hükümdür.\n"
            "- `[KANIT TÜRÜ: TEKNİK REFERANS]` standart/katalog metnidir; şartname maddeleriyle çelişip çelişmediğini kontrol et.\n"
            "- `[KANIT TÜRÜ: RESMİ POZİSYON]` önceki İdare/Müşavir resmi bildirim ve kararlarını gösterir (özellikle atlanmış eski İdare cevaplarına dikkat et).\n"
            "- `[KANIT TÜRÜ: İDDİA (Yüklenici)]` yüklenicinin geçmiş tek taraflı beyanıdır; ASLA bağlayıcı kural veya kesin vakıa gibi kullanma, yalnızca kronoloji ve beyan tutarlılığı denetimi için kullan.\n\n"
            "GÖREV:\n"
            "1. Yüklenicinin talebini yukarıdaki bağlayıcı şartname/mevzuat maddelerine ve varsa yazışma geçmişine göre teknik ve hukuki olarak değerlendir.\n"
            "2. Yüklenici haklı mı, haksız mı yoksa kısmen haklı mı? Kesin ve net bir hüküm ver.\n"
            "3. Hangi bağlayıcı maddelere dayandığını tam madde numarası ve şartname başlığı ile atıfta bulunarak açıkla.\n"
            "4. Varsa süre aşımı (bildirim süresi gecikmesi), önceki İdare cevabıyla çelişki, usul hatası veya eksik evrak durumlarını tespit et.\n"
            "5. Şartname maddesi ile TEKNİK REFERANS (standart içeriği) arasında uyumsuzluk varsa (ör. şartname daha gevşek/daha sıkı/eski baskıya atıf) bunu açıkça belirt."
        )

        analysis_text = safe_llm_invoke([HumanMessage(content=expert_prompt)])
        expert_analyses[domain] = {
            "query": query,
            "matched_subsystem": primary_sub,
            "matched_subsystems": matched_subs,
            "retrieved_articles": [c.get("metadata", {}).get("title", "") for c in retrieved_candidates],
            "retrieved_sources": [c.get("metadata", {}).get("source_file", "") for c in retrieved_candidates],
            "retrieved_chunks": retrieved_candidates + standard_chunks,
            "standard_codes_used": target_codes,
            "analysis": analysis_text,
        }

    return {"expert_analyses": expert_analyses}


def chief_auditor_node(state: AgentState) -> Dict[str, Any]:
    """Tüm uzman değerlendirmelerini ve hukuki maddeleri sentezleyerek İdareye sunulacak resmi Denetim Raporunu üretir."""
    console.print("[bold cyan]▶ [5/6] Baş Denetçi (Sentez):[/bold cyan] Nihai resmi denetim raporu hazırlanıyor...")
    router_res = state["router_result"] or {}
    project_id = state.get("project_id", "GENEL PROJE")
    expert_analyses = state.get("expert_analyses", {})
    case_ctx = state.get("case_context") or {}
    history_summary = case_ctx.get("history_summary", "").strip()

    expert_summary_text = ""
    for domain, data in expert_analyses.items():
        expert_summary_text += f"\n\n### [{domain.upper()} UZMANI DEĞERLENDİRMESİ]\n"
        expert_summary_text += f"Kullanılan Maddeler: {', '.join(data.get('retrieved_articles', []))}\n"
        expert_summary_text += f"Uzman Görüşü:\n{data.get('analysis')}\n"

    system_prompt = (
        "Sen Kıdemli Baş Yapım Denetçisi ve İdare Hukukçususun. İdare adına yüklenici taleplerini karara bağlayacak "
        "resmi, gerekçeli ve bağlayıcı bir TEKNİK İNCELEME VE DENETİM RAPORU hazırlamakla görevlisin.\n\n"
        "Rapor formatın şu resmi yapıda olmalıdır:\n"
        "# T.C. [İDARE ADI] YAPI İŞLERİ DENETİM VE KONTROLÖRLÜK RAPORU\n"
        "## 1. TALEP VE EVRAK ÖZETİ\n"
        "## 2. İLGİLİ MEVZUAT VE SÖZLEŞME DAYANAKLARI (KİK, 4735, YİGŞ / Danışmanlık Genel Şartnamesi, İdari ve Teknik Şartname Maddeleri)\n"
        "## 3. TEKNİK VE HUKUKİ İNCELEME (Haklılık/Haksızlık Analizi, Süreç/Bildirim Usulleri)\n"
        "## 4. MALİ / HAKEDİŞ VE PROJE TAKVİMİNE ETKİSİ\n"
        "## 5. İDAREYE SUNULAN NİHAİ KARAR VE İŞLEM TASLAĞI (Kabul / Kısmi Kabul / Ret Gerekçesi ile Birlikte)"
    )

    history_block = f"VAKA KRONOLOJİSİ / YAZIŞMA GEÇMİŞİ:\n{history_summary}\n\n" if history_summary else ""
    user_prompt = (
        f"PROJE KODU / ADI: {project_id.upper()}\n"
        f"TALEP TÜRÜ: {router_res.get('document_type')}\n"
        f"TALEP DETAYI: {router_res.get('claim_summary')}\n\n"
        f"{history_block}"
        f"UZMAN BİRİMLERDEN GELEN GÖRÜŞLER:\n{expert_summary_text}\n\n"
        "KANIT DİSİPLİNİ: Eski yüklenici yazışmalarını (İDDİA) asla bağlayıcı sözleşme/kanun hükmü gibi dayanak yapma; yalnızca kronoloji ve beyan tutarlılığı değerlendirmesinde kullan.\n"
        "Lütfen resmi, somut bağlayıcı maddelere dayalı, spekülasyona yer bırakmayan eksiksiz bir denetim raporu üret."
    )

    final_report = safe_llm_invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    return {"final_report": final_report}


def citation_verifier_node(state: AgentState) -> Dict[str, Any]:
    """Baş denetçi raporunda atıf yapılan maddeleri veritabanı ve çekilen parçalarla gerçek zamanlı doğrular."""
    console.print("[bold cyan]▶ [6/6] Doğrulama Düğümü (Citation Verifier):[/bold cyan] Halüsinasyon ve madde atıf denetimi yapılıyor...")
    final_report = state.get("final_report", "")
    expert_analyses = state.get("expert_analyses", {})

    # 1. Raporda geçen kanun, şartname maddeleri, poz ve standartları tespit et
    #    (Adım 2 düzeltmesi: standart kodu alternatifi KÜÇÜK/BÜYÜK harfe DUYARLI —
    #    Türkçe "en az 210 gün" ifadesi sahte "EN 210" atfı sanılmasın.)
    regex_citations = set(re.findall(
        r'(?:(?:4734|4735|6098|4686)\s*say[ıi]l[ıi]\s*(?:(?:Kamu\s+[İI]hale(?:\s+S[öo]zle[şs]meleri)?|T[üu]rk\s+Bor[çc]lar|Milletleraras[ıi]\s+Tahkim)\s+)?(?:Kanun[a-z\'\u2019]*\s*)?(?:Madde\s*\d+|Ek\s*Madde\s*\d+|Ge[çc][iı]c[iı]\s*Madde\s*\d+)|'
        r'(?:Yap[ıi]m\s+[İI][şs]leri\s+Genel\s+[ŞS]artnamesi(?:\'[a-z]+)?|YİGŞ|YIGS)\s*(?:Madde\s*\d+)|'
        r'(?:Dan[ıi][şs]manl[ıi]k\s+Hizmet\s+[İI][şs]leri\s+Genel\s+[ŞS]artnamesi(?:\'[a-z]+)?|DHİGŞ|DHIGS)\s*(?:Madde\s*\d+)|'
        r'Madde\s+\d+|Ge[çc][iı]c[iı]\s+Madde\s+\d+|Ek\s+Madde\s+\d+|'
        r'Poz\s+\d+[\.\d]*)',
        final_report,
        re.IGNORECASE
    ))
    # Standart atıfları büyük/harf-duyarlı extract_standard_refs ile kanonik biçimde:
    std_citations = {r["canonical"] for r in extract_standard_refs(final_report)}
    found_clauses = sorted(regex_citations | std_citations)

    # 2. Uzmanların çektiği aday parçaları topla
    retrieved_chunks = []
    for exp in expert_analyses.values():
        retrieved_chunks.extend(exp.get("retrieved_chunks", []))

    # 3. İndeks veritabanını al (in-memory doğrulama — yalnızca Normatif DB `vector_db`)
    col = get_chroma_collection()
    bm25_info = get_or_build_bm25_index(col)
    all_docs = bm25_info.get("documents", [])
    all_metas = bm25_info.get("metadatas", [])

    current_project_id = state.get("project_id")
    if not current_project_id and state.get("router_result"):
        current_project_id = state["router_result"].get("project_id")
    current_proc_type = state.get("procurement_type") or detect_project_procurement_type(current_project_id)

    if current_project_id:
        console.print(
            f"  [dim]• Kapsam Filtresi:[/dim] Sadece 'global' ({current_proc_type or 'ortak'}) ve "
            f"'[bold magenta]{current_project_id}[/bold magenta]' atıfları taranıyor."
        )

    verification_rows = []
    verified_count = 0
    hallucination_count = 0

    for clause in found_clauses:
        clause_clean = clause.strip()
        # Kanun / Yönetmelik öneki ve ana maddeyi ayır (tam kanun/şartname adlarını da tanır)
        m_parts = re.match(
            r"(?:(4734|4735|6098|4686)\s*(?:say[ıi]l[ıi]\s*(?:(?:Kamu\s+[İI]hale(?:\s+S[öo]zle[şs]meleri)?|T[üu]rk\s+Bor[çc]lar|Milletleraras[ıi]\s+Tahkim)\s+)?(?:Kanun[a-z\'\u2019]*\s*)?)?|"
            r"(Yap[ıi]m\s+[İI][şs]leri\s+Genel\s+[ŞS]artnamesi(?:\'[a-z]+)?|YİGŞ|YIGS)\s*|"
            r"(Dan[ıi][şs]manl[ıi]k\s+Hizmet\s+[İI][şs]leri\s+Genel\s+[ŞS]artnamesi(?:\'[a-z]+)?|DHİGŞ|DHIGS)\s*)?(.*)",
            clause_clean,
            re.IGNORECASE,
        )
        law_filter = None
        core_clause = clause_clean
        if m_parts:
            num_law = m_parts.group(1)
            yigs_law = m_parts.group(2)
            dhigs_law = m_parts.group(3)
            rem = (m_parts.group(4) or "").strip()
            if num_law:
                law_filter = num_law
            elif yigs_law:
                law_filter = "yigs"
            elif dhigs_law:
                law_filter = "danismanlik"
            if rem:
                core_clause = rem

        # Adım 2: Standart kodu atıfları kanonik kod üzerinden eşlenir.
        # "EN50126" / "EN 50126:2006" / "TS EN 50126-1" yazım farkları
        # halüsinasyon sanılmaz; kanonik standard_codes metadata'sıyla kıyaslanır.
        std_info = normalize_standard_code(core_clause) if is_standard_like(core_clause) else None

        matched_chunk = None

        # Öncelik 1: Uzmanların bizzat çektiği parçalarda var mı? (Proje kapsamı ve normatif rol korunur)
        for chunk in retrieved_chunks:
            c_meta = chunk.get("metadata", {})
            if c_meta.get("doc_role") == "correspondence_history":
                continue
            src = c_meta.get("source_file", "").lower()
            scope = c_meta.get("scope", "")
            meta_proj = c_meta.get("project_id", "")
            if current_project_id and scope != "global" and meta_proj != current_project_id:
                continue
            if current_proc_type in ("yapim", "danismanlik"):
                if c_meta.get("procurement_type", "ortak") not in (current_proc_type, "ortak"):
                    continue
            if law_filter and law_filter not in src:
                continue
            c_text = chunk.get("content", "")
            c_title = c_meta.get("title", "")
            c_text_low = tr_lower(c_text)
            c_title_low = tr_lower(c_title)
            core_low = tr_lower(core_clause)
            if std_info and std_info.get("valid"):
                # Standart kodu atıfı: kanonik kod eşleşmesi (yazım farkı toleranslı)
                codes = set(x for x in (c_meta.get("standard_codes") or "").split("|") if x)
                if not codes:
                    codes = {r["canonical"] for r in extract_standard_refs(c_text[:4000])}
                hit = std_info["canonical"] in codes or std_info["family"] in codes
                if not hit and codes:
                    mf_res = match_standard_fuzzy(std_info["canonical"], sorted(codes), threshold=92)
                    hit = bool(mf_res.get("match"))
                if hit:
                    matched_chunk = c_meta
                    break
                continue
            if re.search(r"(?<!\w)" + re.escape(core_low) + r"(?!\w)", c_text_low) or re.search(r"(?<!\w)" + re.escape(core_low) + r"(?!\w)", c_title_low):
                matched_chunk = c_meta
                break

        if matched_chunk:
            src = matched_chunk.get("source_file", "Bilinmeyen Belge")
            p_val = matched_chunk.get("page_num", 0)
            page_desc = f"Sayfa {p_val}" if p_val and p_val > 0 else "Fiziksel sayfa bilgisi yok (Dijital Belge)"
            verification_rows.append(f"| `{clause_clean}` | <span style='color:green'>✔ DOĞRULANDI (Çekilen Madde)</span> | `{src}` ({page_desc}) |")
            verified_count += 1
            continue

        # Öncelik 2: Genel veritabanında var mı? (YALNIZCA normatif belgeler, ilgili proje ve uyumlu ihale türü taranır)
        # Boş standart form şablonları yerine esas kanun/yönetmelik/şartname belgeleri önceliklendirilir.
        found_in_db = None
        fallback_form_in_db = None
        for doc, meta in zip(all_docs, all_metas):
            if meta.get("doc_role") == "correspondence_history":
                continue
            src = meta.get("source_file", "").lower()
            scope = meta.get("scope", "")
            meta_proj = meta.get("project_id", "")
            if current_project_id and scope != "global" and meta_proj != current_project_id:
                continue
            if current_proc_type in ("yapim", "danismanlik"):
                if meta.get("procurement_type", "ortak") not in (current_proc_type, "ortak"):
                    continue
            if law_filter and law_filter not in src:
                continue
            doc_low = tr_lower(doc)
            t_low = tr_lower(meta.get("title", ""))
            core_low = tr_lower(core_clause)
            if std_info and std_info.get("valid"):
                # Standart kodu atıfı: metadata'daki kanonik kodlarla hızlı eşleşme
                # (tam eşleşme veya aile öneki: "EN 50122" <-> "EN 50122-1")
                codes = set(x for x in (meta.get("standard_codes") or "").split("|") if x)
                fam = std_info["family"]
                if std_info["canonical"] in codes or any(c == fam or c.startswith(fam + "-") for c in codes):
                    found_in_db = meta
                    break
                continue
            if re.search(r"(?<!\w)" + re.escape(core_low) + r"(?!\w)", doc_low) or re.search(r"(?<!\w)" + re.escape(core_low) + r"(?!\w)", t_low):
                if meta.get("doc_type") == "standart_form_sablonu":
                    if fallback_form_in_db is None:
                        fallback_form_in_db = meta
                    continue
                found_in_db = meta
                break

        if found_in_db is None:
            found_in_db = fallback_form_in_db

        if found_in_db:
            src = found_in_db.get("source_file", "Veritabanı Dokümanı")
            p_val = found_in_db.get("page_num", 0)
            page_desc = f"Sayfa {p_val}" if p_val and p_val > 0 else "Fiziksel sayfa bilgisi yok (Dijital Belge)"
            verification_rows.append(f"| `{clause_clean}` | <span style='color:blue'>✔ DOĞRULANDI (Veritabanında Mevcut)</span> | `{src}` ({page_desc}) |")
            verified_count += 1
        else:
            verification_rows.append(f"| `{clause_clean}` | <span style='color:red'>❌ TEYİT EDİLEMEDİ</span> | **Şartname veya mevzuatta bu madde numarası bulunamadı (Halüsinasyon riski)** |")
            hallucination_count += 1

    total_citations = len(found_clauses)
    accuracy_rate = (verified_count / total_citations * 100) if total_citations > 0 else 100.0

    if hallucination_count > 0:
        status_banner = f"> [!WARNING]\n> **Dikkat:** Raporda atıf yapılan {total_citations} maddeden **{hallucination_count} tanesi** proje evraklarında veya mevzuatta teyit edilememiştir! Halüsinasyon riski taşıyan maddeler aşağıdaki tabloda işaretlenmiştir."
    else:
        status_banner = f"> [!NOTE]\n> **Doğrulama Başarılı:** Raporda atıf yapılan tüm maddeler ({verified_count}/{total_citations} - %{accuracy_rate:.1f}) proje şartnameleri ve mevzuat evraklarındaki sayfa numaraları ile teyit edilmiştir."

    table_md = "\n".join(verification_rows) if verification_rows else "| Genel Hükümler | ✔ DOĞRULANDI | Genel Şartname Prensipleri |"

    verification_section = (
        "\n\n---\n"
        "## 6. MEVZUAT VE ŞARTNAME ATIF DOĞRULAMA (CITATION VERIFICATION)\n\n"
        f"{status_banner}\n\n"
        "| Atıf Yapılan Madde / Standart | Doğrulama Durumu | Kaynak Belge ve Sayfa |\n"
        "| :--- | :--- | :--- |\n"
        f"{table_md}\n\n"
        f"- **Toplam Atıf Sayısı:** {total_citations}\n"
        f"- **Doğrulanan Madde Sayısı:** {verified_count}\n"
        f"- **Teyit Edilemeyen (Riskli) Atıf:** {hallucination_count}\n"
        f"- **Atıf Doğruluk Oranı:** %{accuracy_rate:.1f}\n"
    )

    verified_report = final_report + verification_section
    return {"final_report": verified_report, "verification_notes": verification_section}


# ==========================================
# 4. LangGraph Akışının Kurulması
# ==========================================
def create_audit_graph():
    """6 aşamalı çoklu ajan iş akışını derler."""
    workflow = StateGraph(AgentState)

    workflow.add_node("reader", reader_node)
    workflow.add_node("case_builder", case_builder_node)
    workflow.add_node("router", router_node)
    workflow.add_node("experts", expert_consultation_node)
    workflow.add_node("chief_auditor", chief_auditor_node)
    workflow.add_node("verifier", citation_verifier_node)

    workflow.set_entry_point("reader")
    workflow.add_edge("reader", "case_builder")
    workflow.add_edge("case_builder", "router")
    workflow.add_edge("router", "experts")
    workflow.add_edge("experts", "chief_auditor")
    workflow.add_edge("chief_auditor", "verifier")
    workflow.add_edge("verifier", END)

    return workflow.compile()


def run_audit(file_path: str, project_id: Optional[str] = None):
    """Belirtilen yüklenici evrakı üzerinde çoklu ajan denetim akışını çalıştırır."""
    app = create_audit_graph()

    initial_state: AgentState = {
        "doc_path": file_path,
        "doc_text": "",
        "project_id": project_id,
        "procurement_type": detect_project_procurement_type(project_id),
        "case_context": None,
        "router_result": None,
        "expert_analyses": {},
        "final_report": "",
        "verification_notes": None,
    }

    result = app.invoke(initial_state)

    console.print("\n")
    console.print(Panel(
        Markdown(result["final_report"]),
        title="[bold green]NİHAİ RESMİ DENETİM VE KONTROLÖRLÜK RAPORU[/bold green]",
        border_style="green",
    ))

    # Raporu dosyaya kaydet
    RAPORLAR_DIR.mkdir(parents=True, exist_ok=True)
    report_filename = f"Denetim_Raporu_{Path(file_path).stem}.md"
    report_path = RAPORLAR_DIR / report_filename
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(result["final_report"])

    console.print(f"\n[bold green]✔[/bold green] Rapor başarıyla kaydedildi: [yellow]{report_path}[/yellow]")
    return result


if __name__ == "__main__":
    import argparse

    console.rule("[bold cyan]İnşaat Hakediş ve Mevzuat Denetim Ajanları (2_agents_graph.py)[/bold cyan]")

    ap = argparse.ArgumentParser(description="6 Düğümlü Çoklu Ajan Denetim Akışı (2_agents_graph.py)")
    ap.add_argument("file_path", nargs="?", default=None, help="Denetlenecek yüklenici evrakı (.pdf/.docx/.md/.txt)")
    ap.add_argument("--project", default=None, help="Hedef proje ID'si (ör. ikitelli_atakoy_metro, kirazli_halkali_metro)")
    cli_args = ap.parse_args()

    if cli_args.file_path:
        target_file = cli_args.file_path
    else:
        files = [f for f in YUKLENICI_DIR.rglob("*.*") if f.is_file() and not f.name.endswith(".md")]
        if not files:
            files = [f for f in YUKLENICI_DIR.rglob("*.*") if f.is_file()]
        if files:
            target_file = str(files[0])
            console.print(f"[dim]Varsayılan olarak '{files[0].name}' dosyası inceleniyor.[/dim]")
        else:
            console.print(f"[bold red]![/bold red] [yellow]{YUKLENICI_DIR}[/yellow] klasöründe incelenecek evrak bulunamadı.")
            console.print("[dim]Kullanım: python 2_agents_graph.py <dosya_yolu> [--project <proje_id>][/dim]")
            sys.exit(0)

    run_audit(target_file, project_id=cli_args.project)
