# -*- coding: utf-8 -*-
"""
Dinamik Vaka Hafızası (Case Context Builder — Adım 4).

Amaç:
    Yeni bir yüklenici/müşavir evrakı geldiğinde arka plandaki tüm yazışmaları
    körlemesine LLM'e vermek yerine, SQLite Proje Grafiği + (isteğe bağlı)
    ChromaDB correspondence_history üzerinden ilgili bağlamı sabit bir karakter
    bütçesi içinde öncelik sırasıyla toplar ve her bloğa KANIT AĞIRLIGI
    etiketi basar.

Kanıt Ağırlığı Kuralları (İddia asla kural gibi davranmaz):
    - BAĞLAYICI KURAL    : Kanun / Yönetmelik / Sözleşme / İdari & Teknik Şartname
    - TEKNİK REFERANS    : EN / IEC / NFPA / TS standart içi metin ve tabloları
    - RESMİ POZİSYON     : İdare veya Müşavir tarafından gönderilmiş resmi yazılar
    - ORTAK TUTANAK      : Tarafların müşterek imzaladığı tutanak ve tespitler
    - İDDİA (Yüklenici)  : Doğrulanmaya muhtaç yüklenici beyan ve talepleri

Bütçe Öncelik Sırası (varsayılan 90.000 karakter):
    1. İlgi / cevap zinciri (en yakın 2 yazı tam metin + geriye 3 seviye kronolojik özet)
    2. Açık / kısmen cevaplı talep defteri kayıtları + paylaşılan etiketli yazılar
    3. Sözleşme / Şartname / Mevzuat maddeleri (BAĞLAYICI KURAL)
    4. Standart içi tablolar ve norm metinleri (TEKNİK REFERANS)
    5. Benzer eski yazışma özetleri (semantik / ikincil eşleşmeler)
"""
import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from utils.card_extractor import _RE_ILGI_TARIH, extract_card_regex, parse_tr_date
from utils.config import YUKLENICI_TALEPLERI_DIR
from utils.project_db import (
    DEFAULT_DB_PATH,
    connect,
    find_related_by_tags,
    iter_chain,
    list_open_claims,
    match_doc_no_in_project,
)
from utils.standards import extract_standard_refs

# Varsayılan bütçe ve zincir derinlik sabitleri (aşılabilir parametreler)
DEFAULT_TOTAL_BUDGET_CHARS = 90000
DEFAULT_HISTORY_BUDGET_CHARS = 38000
DEFAULT_VERBATIM_CHAIN_COUNT = 2
DEFAULT_SUMMARY_CHAIN_LEVELS = 3
MAX_SINGLE_VERBATIM_CHARS = 14000

KANONIK_SON_EK = "__kanonik.md"

# Öncelik sırası sayısal anahtarları (küçük sayı = yüksek öncelik)
PRIORITY_ILGI_CHAIN = 1
PRIORITY_LEDGER = 2
PRIORITY_NORMATIVE = 3
PRIORITY_STANDARDS = 4
PRIORITY_SIMILAR_HISTORY = 5

EVIDENCE_LABELS = {
    "BAĞLAYICI_KURAL": "BAĞLAYICI KURAL (Kanun / Sözleşme / Şartname)",
    "BAGLAYICI_KURAL": "BAĞLAYICI KURAL (Kanun / Sözleşme / Şartname)",
    "TEKNİK_REFERANS": "TEKNİK REFERANS (Standart Norm)",
    "TEKNIK_REFERANS": "TEKNİK REFERANS (Standart Norm)",
    "RESMI_POZISYON_IDARE": "RESMİ POZİSYON (İdare / Müşavir)",
    "TUTANAK_ORTAK": "ORTAK TUTANAK / TESPİT",
    "IDDIA_YUKLENICI": "İDDİA (Yüklenici) — Doğrulanmaya Muhtaç Beyan",
}


def format_evidence_label(
    evidence_weight: Optional[str] = None,
    *,
    sender_role: Optional[str] = None,
    doc_type: Optional[str] = None,
    doc_role: Optional[str] = None,
) -> str:
    """Belge veya chunk meta verisinden zorunlu kanıt ağırlığı etiketini üretir."""
    if doc_role == "normative_rule":
        if doc_type == "standart_norm_katalogu":
            return EVIDENCE_LABELS["TEKNİK_REFERANS"]
        return EVIDENCE_LABELS["BAĞLAYICI_KURAL"]

    ew = (evidence_weight or "").strip().upper()
    if ew in EVIDENCE_LABELS:
        return EVIDENCE_LABELS[ew]
    if doc_type == "standart_norm_katalogu":
        return EVIDENCE_LABELS["TEKNİK_REFERANS"]

    sr = (sender_role or "").strip().lower()
    if doc_type == "tutanak" or sr in ("joint", "ortak_tutanak"):
        return EVIDENCE_LABELS["TUTANAK_ORTAK"]
    if sr in ("administration", "consultant", "resmi_idare", "resmi_musavir", "idare", "musavir"):
        return EVIDENCE_LABELS["RESMI_POZISYON_IDARE"]
    return EVIDENCE_LABELS["IDDIA_YUKLENICI"]


def _load_document_text(
    doc_row: Dict[str, Any],
    base_dir: Path = YUKLENICI_TALEPLERI_DIR,
) -> Tuple[str, str]:
    """
    SQLite kaydındaki belgenin tam kanonik metnini diskten yükler.
    Döndürür: (metin, kaynak_türü: 'file'|'kanonik_ocr'|'summary')
    """
    rel = (doc_row.get("file_path") or "").strip()
    if rel:
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = base_dir / rel
        if candidate.exists() and candidate.is_file():
            if candidate.suffix.lower() in (".md", ".txt"):
                return candidate.read_text(encoding="utf-8", errors="ignore"), "file"
            kanonik = candidate.parent / ".cache_ocr" / (candidate.stem + KANONIK_SON_EK)
            if kanonik.exists() and kanonik.is_file():
                return kanonik.read_text(encoding="utf-8", errors="ignore"), "kanonik_ocr"
    return (doc_row.get("summary") or "").strip(), "summary"


def _format_card_summary_line(doc_row: Dict[str, Any], extra_note: str = "") -> str:
    """Tek bir yazışma kartını kronolojik özet satırına biçimlendirir."""
    label = format_evidence_label(
        doc_row.get("evidence_weight"),
        sender_role=doc_row.get("sender_role"),
        doc_type=doc_row.get("doc_type"),
    )
    d_date = doc_row.get("doc_date") or "Tarih yok"
    d_no = doc_row.get("doc_no") or "Sayı yok"
    d_state = doc_row.get("state") or "Acik"
    d_subj = (doc_row.get("subject") or "").strip()
    d_sum = (doc_row.get("summary") or "").strip()
    if len(d_sum) > 260:
        d_sum = d_sum[:257] + "..."
    note_part = f" | Not: {extra_note}" if extra_note else ""
    return (
        f"- [KANIT TÜRÜ: {label}] **{d_date} | {d_no}** (Durum: `{d_state}`{note_part})\n"
        f"  Konu: {d_subj or '-'}\n"
        f"  Özet: {d_sum or '-'}"
    )


def _format_verbatim_block(
    doc_row: Dict[str, Any],
    full_text: str,
    relation_note: str,
    max_single_chars: int = MAX_SINGLE_VERBATIM_CHARS,
) -> str:
    """Zincirdeki yakın yazıyı KANIT TÜRÜ başlığıyla tam metin bloğu yapar."""
    label = format_evidence_label(
        doc_row.get("evidence_weight"),
        sender_role=doc_row.get("sender_role"),
        doc_type=doc_row.get("doc_type"),
    )
    d_date = doc_row.get("doc_date") or "Tarih yok"
    d_no = doc_row.get("doc_no") or "Sayı yok"
    d_state = doc_row.get("state") or "Acik"
    body = full_text.strip()
    if len(body) > max_single_chars:
        head = int(max_single_chars * 0.7)
        tail = max_single_chars - head
        body = (
            f"{body[:head]}\n\n... [TEK YAZI TAVANI ({max_single_chars} krk) NEDENİYLE ARA BÖLÜM KISALTILDI] ...\n\n{body[-tail:]}"
        )
    return (
        f"--- [KANIT TÜRÜ: {label} | İlişki: {relation_note} | Tarih: {d_date} | Sayı: {d_no} | Durum: {d_state}] ---\n"
        f"{body}"
    )


def _find_incoming_responses(
    conn: sqlite3.Connection,
    anchor_doc_ids: Sequence[str],
    exclude_ids: set,
) -> List[Dict[str, Any]]:
    """
    Zincirdeki eski yazılara sonradan gönderilmiş cevap/takip yazılarını yakalar.
    Örn: Yüklenici yeni dilekçesinde İdare cevabını atlayıp eski talebine İlgi
    vermişse, o eski talebi yanıtlayan İdare cevabını graf üzerinden yine de bulur.
    """
    if not anchor_doc_ids:
        return []
    placeholders = ",".join("?" for _ in anchor_doc_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT d.*, l.link_type AS via_link_type, l.to_ref AS answered_doc_id
        FROM links l
        JOIN documents d ON d.doc_id = l.from_doc_id
        WHERE l.resolved=1
          AND l.link_type IN ('ilgi_zinciri', 'cevaplar')
          AND l.to_ref IN ({placeholders})
        ORDER BY d.doc_date DESC
        """,
        tuple(anchor_doc_ids),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        rd = dict(r)
        if rd["doc_id"] not in exclude_ids:
            out.append(rd)
    return out


def assemble_budgeted_context(
    blocks: Sequence[Dict[str, Any]],
    max_chars: int = DEFAULT_TOTAL_BUDGET_CHARS,
    separator: str = "\n\n",
) -> Tuple[str, Dict[str, Any]]:
    """
    Verilen bağlam bloklarını KESİN öncelik sırasıyla sabit karakter bütçesi
    içine paketler.

    Her blok: {"priority": int (1..5), "category": str, "text": str,
               "allow_truncate": bool (varsayılan True)}

    Garanti:
        - Dönen metin uzunluğu <= max_chars.
        - Düşük öncelikli blok (ör. 5=benzer yazışmalar) asla yüksek öncelikli
          bloğu (ör. 1=ilgi zinciri veya 3=şartname) dışarı atamaz.
    """
    if max_chars <= 0 or not blocks:
        return "", {"used_chars": 0, "max_chars": max_chars, "included": 0, "dropped": len(blocks), "truncated": 0}

    ordered = sorted(
        enumerate(blocks),
        key=lambda pair: (int(pair[1].get("priority", 99)), pair[0]),
    )

    parts: List[str] = []
    used = 0
    included = 0
    dropped = 0
    truncated = 0
    by_category: Dict[str, int] = {}

    for _, blk in ordered:
        txt = (blk.get("text") or "").strip()
        if not txt:
            continue
        sep_len = len(separator) if parts else 0
        remaining = max_chars - used - sep_len
        if remaining <= 0:
            dropped += 1
            continue

        cat = blk.get("category") or f"p{blk.get('priority', 99)}"
        if len(txt) <= remaining:
            parts.append(txt)
            used += sep_len + len(txt)
            included += 1
            by_category[cat] = by_category.get(cat, 0) + 1
        elif blk.get("allow_truncate", True) and remaining >= 350:
            marker = "\n... [BÜTÇE SINIRI NEDENİYLE KIRPILDI] ..."
            cut_limit = remaining - len(marker)
            if cut_limit > 120:
                snippet = txt[:cut_limit]
                last_nl = snippet.rfind("\n")
                if last_nl > cut_limit * 0.6:
                    snippet = snippet[:last_nl]
                parts.append(snippet.rstrip() + marker)
                used += sep_len + len(snippet.rstrip()) + len(marker)
                included += 1
                truncated += 1
                by_category[cat] = by_category.get(cat, 0) + 1
            else:
                dropped += 1
        else:
            dropped += 1

    assembled = separator.join(parts)
    if len(assembled) > max_chars:
        assembled = assembled[:max_chars]

    return assembled, {
        "used_chars": len(assembled),
        "max_chars": max_chars,
        "included": included,
        "dropped": dropped,
        "truncated": truncated,
        "by_category": by_category,
    }


def build_case_context(
    doc_text: str,
    *,
    doc_path: Optional[Path] = None,
    project_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
    history_base_dir: Path = YUKLENICI_TALEPLERI_DIR,
    verbatim_chain_count: int = DEFAULT_VERBATIM_CHAIN_COUNT,
    summary_chain_levels: int = DEFAULT_SUMMARY_CHAIN_LEVELS,
    history_budget_chars: int = DEFAULT_HISTORY_BUDGET_CHARS,
    use_semantic_history: bool = True,
) -> Dict[str, Any]:
    """
    Gelen bir evrak için geçici Vaka Hafızası paketini oluşturur.

    Döndürür:
        {
          "blocks": [...],           # assemble_budgeted_context için öncelikli bloklar
          "history_text": str,       # yalnızca yazışma tarihçesi bütçelenmiş metni
          "history_summary": str,    # Router / Baş Denetçi için kısa kronoloji özeti
          "chain_docs": [...],       # çözümlenen İlgi zinciri kartları
          "incoming_responses": [...],
          "related_docs": [...],     # paylaşılan etiket / açık talep / semantik
          "detected_refs": {...},    # gelen belgeden çıkarılan tarih/sayı/ilgi/standart/poz
          "stats": {...},
        }
    """
    empty_result = {
        "blocks": [],
        "history_text": "",
        "history_summary": "",
        "chain_docs": [],
        "incoming_responses": [],
        "related_docs": [],
        "detected_refs": {},
        "stats": {"used_chars": 0, "chain_count": 0, "related_count": 0},
    }

    if not doc_text or not project_id or project_id == "global":
        return empty_result

    effective_db = Path(db_path) if db_path else DEFAULT_DB_PATH
    owns_conn = False
    if conn is None:
        if not effective_db.exists():
            return empty_result
        conn = connect(effective_db)
        owns_conn = True

    try:
        proj_count = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        if proj_count == 0:
            return empty_result

        filename = doc_path.name if doc_path else "incoming_doc.md"
        doc_sha = hashlib.sha256(doc_text.encode("utf-8")).hexdigest()
        stage1 = extract_card_regex(doc_text, filename=filename)
        card = stage1["card"]
        ilgi_refs = stage1["ilgi_refs"]
        std_refs = [r["canonical"] for r in extract_standard_refs(doc_text)]
        poz_refs = [
            re.sub(r"(?i)^poz\s+", "", p).strip()
            for p in re.findall(r"Poz\s+\d+(?:[.\-]\d+)*", doc_text, re.IGNORECASE)
        ]

        # Gelen evrak zaten DB'de kayıtlıysa (ör. yeniden denetim) kendisini hariç tut
        self_row = conn.execute(
            "SELECT * FROM documents WHERE project_id=? AND doc_sha256=? LIMIT 1",
            (project_id, doc_sha),
        ).fetchone()
        self_doc_id = self_row["doc_id"] if self_row else None
        seen_ids = {self_doc_id} if self_doc_id else set()

        # 1. Doğrudan İlgi / Cevap Zincirini Yürüt
        chain_docs: List[Dict[str, Any]] = []
        max_chain_items = verbatim_chain_count + summary_chain_levels

        if self_doc_id:
            for item in iter_chain(conn, self_doc_id, max_depth=max_chain_items + 2):
                if item["doc_id"] not in seen_ids:
                    seen_ids.add(item["doc_id"])
                    chain_docs.append(item)

        # Yeni (henüz ingest edilmemiş) evrak için İlgi: referanslarından köprü kur
        ilgi_dates = [r for r in ilgi_refs if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r)]
        if card.get("ilgi_raw"):
            def_y = int(card["doc_date"][:4]) if card.get("doc_date") else None
            for mm in _RE_ILGI_TARIH.finditer(card["ilgi_raw"]):
                iso, _ = parse_tr_date(mm.group(0), default_year=def_y)
                if iso and iso not in ilgi_dates:
                    ilgi_dates.append(iso)

        for ref in ilgi_refs:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}", ref):
                continue
            target = match_doc_no_in_project(conn, project_id, ref, ilgi_dates=ilgi_dates)
            if target and target["doc_id"] not in seen_ids:
                t_copy = dict(target)
                t_copy["depth"] = 0
                seen_ids.add(t_copy["doc_id"])
                chain_docs.append(t_copy)
                for anc in iter_chain(conn, target["doc_id"], max_depth=max_chain_items + 1):
                    if anc["doc_id"] not in seen_ids:
                        anc_copy = dict(anc)
                        anc_copy["depth"] = int(anc.get("depth", 0)) + 1
                        seen_ids.add(anc_copy["doc_id"])
                        chain_docs.append(anc_copy)

        chain_docs.sort(key=lambda d: (int(d.get("depth", 99)), -(int((d.get("doc_date") or "0000-00-00").replace("-", "")[:8]) if re.match(r"\d{4}-\d{2}-\d{2}", d.get("doc_date") or "") else 0)))

        # 1b. Zincirdeki yazılara İdare tarafından verilmiş ancak yüklenicinin atladığı cevapları yakala
        anchor_ids = [d["doc_id"] for d in chain_docs[:3]]
        incoming_responses = _find_incoming_responses(conn, anchor_ids, seen_ids)
        for resp in incoming_responses:
            seen_ids.add(resp["doc_id"])

        # 2. Etiket / Standart / Poz + Açık Talep Defteri Kayıtları
        tag_pairs: List[Tuple[str, str]] = []
        for s in std_refs[:10]:
            tag_pairs.append(("standart", s))
        for p in poz_refs[:10]:
            tag_pairs.append(("poz_no", p))

        tag_related = find_related_by_tags(conn, project_id, tag_pairs, exclude_doc_ids=seen_ids, limit=6)
        for td in tag_related:
            seen_ids.add(td["doc_id"])

        open_claims = list_open_claims(conn, project_id, exclude_doc_ids=seen_ids, limit=6)
        for oc in open_claims:
            seen_ids.add(oc["doc_id"])

        # 3. İsteğe bağlı Semantik Tarihçe Araması (ChromaDB doc_role='correspondence_history')
        semantic_docs: List[Dict[str, Any]] = []
        if use_semantic_history:
            try:
                from utils.retriever import get_chroma_collection, search_and_rerank

                col = get_chroma_collection()
                hist_check = col.get(
                    where={"$and": [{"project_id": project_id}, {"doc_role": "correspondence_history"}]},
                    limit=1,
                )
                if hist_check.get("ids"):
                    sem_query = f"{card.get('subject') or ''} {doc_text[:600]}".strip()
                    sem_res = search_and_rerank(
                        query=sem_query,
                        project_id=project_id,
                        candidate_k=12,
                        final_top_k=4,
                        doc_role="correspondence_history",
                    )
                    for sr in sem_res:
                        meta = sr.get("metadata", {})
                        s_doc_id = meta.get("sqlite_doc_id")
                        if s_doc_id and s_doc_id not in seen_ids:
                            row = conn.execute("SELECT * FROM documents WHERE doc_id=?", (s_doc_id,)).fetchone()
                            if row:
                                rd = dict(row)
                                rd["_semantic_excerpt"] = sr.get("content", "")
                                rd["_rerank_score"] = sr.get("rerank_score", 0.0)
                                seen_ids.add(s_doc_id)
                                semantic_docs.append(rd)
            except Exception:
                pass

        # --- Öncelikli Blokları İnşa Et ---
        blocks: List[Dict[str, Any]] = []

        # Priority 1: İlgi / Cevap Zinciri (2 verbatim + 3 seviye kronolojik özet)
        verbatim_docs = chain_docs[:verbatim_chain_count]
        summary_chain_docs = [
            d for d in chain_docs[verbatim_chain_count:]
            if int(d.get("depth", 0)) < (verbatim_chain_count + summary_chain_levels)
        ][: summary_chain_levels * 2]

        for idx, cd in enumerate(verbatim_docs):
            txt, src_kind = _load_document_text(cd, base_dir=history_base_dir)
            rel_lbl = f"İlgi Zinciri Seviye {cd.get('depth', idx)} (Tam Metin)"
            blocks.append({
                "priority": PRIORITY_ILGI_CHAIN,
                "category": "ilgi_chain_verbatim",
                "text": _format_verbatim_block(cd, txt, rel_lbl),
                "allow_truncate": True,
            })

        # Yüklenicinin atladığı İdare cevaplarını yüksek öncelikle verbatim/öncelikli ekle
        for resp in incoming_responses[:2]:
            txt, _ = _load_document_text(resp, base_dir=history_base_dir)
            blocks.append({
                "priority": PRIORITY_ILGI_CHAIN,
                "category": "ilgi_chain_missed_reply",
                "text": _format_verbatim_block(
                    resp,
                    txt,
                    "Önceki Yazıya Verilmiş Resmi Cevap (Yeni Evrakta İlgi Verilmemiş Olsa da Bulundu)",
                ),
                "allow_truncate": True,
            })

        if summary_chain_docs:
            lines = ["--- [İLGİ ZİNCİRİ GEÇMİŞİ — KRONOLOJİK ÖZET (3+ Seviye Geri)] ---"]
            for sd in summary_chain_docs:
                lines.append(_format_card_summary_line(sd, extra_note=f"Zincir Derinliği: {sd.get('depth')}"))
            blocks.append({
                "priority": PRIORITY_ILGI_CHAIN,
                "category": "ilgi_chain_summary",
                "text": "\n".join(lines),
                "allow_truncate": True,
            })

        # Priority 2: Talep Defteri (Açık Talepler + Paylaşılan Etiket/Standart/Poz Yazıları)
        ledger_lines: List[str] = []
        if tag_related:
            ledger_lines.append("--- [ORTAK STANDART / POZ ETİKETLİ PROJE YAZIŞMALARI] ---")
            for td in tag_related:
                ledger_lines.append(
                    _format_card_summary_line(td, extra_note=f"Ortak Etiket: {td.get('shared_tags', '')}")
                )
        if open_claims:
            ledger_lines.append("--- [TALEP DEFTERİ — AÇIK / KISMEN CEVAPLANMIŞ KAYITLAR] ---")
            for oc in open_claims:
                ledger_lines.append(_format_card_summary_line(oc))
        if ledger_lines:
            blocks.append({
                "priority": PRIORITY_LEDGER,
                "category": "ledger_items",
                "text": "\n".join(ledger_lines),
                "allow_truncate": True,
            })

        # Priority 5: Semantik Benzer Eski Yazışmalar
        if semantic_docs:
            sem_lines = ["--- [ANLAMSAL OLARAK BENZER ESKİ YAZIŞMA ÖZETLERİ] ---"]
            for sm in semantic_docs:
                sem_lines.append(
                    _format_card_summary_line(sm, extra_note=f"Alaka Skoru: {sm.get('_rerank_score', 0.0):.2f}")
                )
            blocks.append({
                "priority": PRIORITY_SIMILAR_HISTORY,
                "category": "similar_history",
                "text": "\n".join(sem_lines),
                "allow_truncate": True,
            })

        history_text, stats = assemble_budgeted_context(blocks, max_chars=history_budget_chars)
        stats["chain_count"] = len(chain_docs)
        stats["verbatim_count"] = len(verbatim_docs)
        stats["summary_chain_count"] = len(summary_chain_docs)
        stats["missed_reply_count"] = len(incoming_responses)
        stats["related_count"] = len(tag_related) + len(open_claims) + len(semantic_docs)

        # Router ve Baş Denetçi için kompakt kronoloji özeti
        summary_lines = [
            f"Proje: {project_id} | Gelen Evrak Tarihi: {card.get('doc_date') or 'Belirsiz'} | Sayı: {card.get('doc_no') or 'Belirsiz'}",
            f"Çözümlenen İlgi Zinciri ({len(chain_docs)} belge): "
            + (", ".join(f"{d.get('doc_date') or '?'} / {d.get('doc_no') or '?'} [{d.get('sender_role') or '?'}]" for d in chain_docs[:5]) or "Yok"),
        ]
        if incoming_responses:
            summary_lines.append(
                "Atlanıp Yakalanan İdare/Müşavir Cevapları: "
                + ", ".join(f"{d.get('doc_date') or '?'} / {d.get('doc_no') or '?'}" for d in incoming_responses)
            )
        if tag_related:
            summary_lines.append(
                f"Ortak Standart/Poz Taşıyan Eski Yazılar ({len(tag_related)} adet): "
                + ", ".join(f"{d.get('doc_no') or d.get('doc_date') or '?'}" for d in tag_related[:4])
            )

        return {
            "blocks": blocks,
            "history_text": history_text,
            "history_summary": "\n".join(summary_lines),
            "chain_docs": chain_docs,
            "incoming_responses": incoming_responses,
            "related_docs": tag_related + open_claims + semantic_docs,
            "detected_refs": {
                "doc_date": card.get("doc_date"),
                "doc_no": card.get("doc_no"),
                "ilgi_refs": ilgi_refs,
                "standard_codes": std_refs,
                "poz_nos": poz_refs,
            },
            "stats": stats,
        }
    finally:
        if owns_conn:
            conn.close()
