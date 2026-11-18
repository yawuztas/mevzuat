# -*- coding: utf-8 -*-
"""
Adım 5 — Kapalı Döngü İdare Cevabı Geri Girişi & İnsan Onaylı Durum Makinesi.

Görevleri:
1. İdare / Müşavir tarafından gönderilen resmi cevap yazısını sisteme
   `sender_role='administration'|'consultant'`, `evidence_weight='RESMI_POZISYON_IDARE'`
   ve `doc_role='correspondence_history'` olarak kaydeder.
2. `--reply-to` parametresi ve `İlgi:` satırı üzerinden yanıtladığı önceki yüklenici
   yazılarına `cevaplar` kenarı bağlar (`links` tablosu).
3. Cevap metnini deterministik kalıplarla analiz ederek hedef yazı(lar) için
   durum geçiş önerisi (`Acik` -> `Kismen_Cevaplandi` / `Cevaplandi` / `Kapatildi`) üretir.
4. Kesin durum geçişini ASLA sessizce yapmaz; insan onayı verildiğinde
   `update_state(..., confirmed_by_human=True)` ile `state_history` tablosuna
   tam denetim izi yazar.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.card_extractor import (
    _RE_ILGI_TARIH,
    extract_identity_card,
    parse_tr_date,
)
from utils.config import YUKLENICI_TALEPLERI_DIR
from utils.document_parser import parse_any_document
from utils.project_db import (
    VALID_STATES,
    add_link,
    add_tags,
    connect,
    find_by_file_path,
    get_document,
    link_exists,
    match_doc_no_in_project,
    update_state,
    upsert_document,
)
from utils.standards import extract_standard_refs
from utils.text_tr import tr_lower

KANONIK_SON_EK = "__kanonik.md"
TEXT_EXT = {".md", ".txt"}

# Deterministik durum öneri kalıpları (sıralı öncelik: kısmi -> kapanış -> kesin cevap)
_PARTIAL_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\beksik\s+(?:bilgi|belge|evrak)", "eksik bilgi/belge talebi"),
    (r"\bek\s+(?:bilgi|belge|rapor|doküman)", "ek belge istenmesi"),
    (r"\bkısmen\s+(?:kabul|uygun)", "kısmi kabul / uygunluk"),
    (r"\byeniden\s+değerlendir", "tamamlama sonrası yeniden değerlendirme"),
    (r"\bsunulmas[ıi]\s+halinde", "şartlı ek sunum beklentisi"),
    (r"\brevize\s+edilerek\s+(?:tekrar\s+)?sunul", "revize edilerek tekrar sunum talebi"),
    (r"\btamamland[ıi][ğg][ıi]nda\b", "eksik tamamlanana dek açık"),
)

_CLOSURE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\bbaşkanl[ıi]k\s+olur", "Başkanlık Oluru ile kesin karar"),
    (r"\bkesin\s+karar", "kesin karar bildirimi"),
    (r"\bsonu[çc]land[ıi]r[ıi]lm[ıi][şs]t[ıi]r", "dosya/talep sonuçlandırıldı"),
    (r"\bkapat[ıi]lm[ıi][şs]t[ıi]r", "dosya/talep kapatıldı"),
    (r"\bhakem\s+karar[ıi]", "hakem kararı ile kapanış"),
    (r"\bsüre\s+uzat[ıi]m[ıi]\s+verilmesine\s+olur", "süre uzatımı oluru"),
)

_ANSWERED_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\breddedilmiştir\b", "talebin reddi"),
    (r"\buygun\s+(?:görülmemiştir|bulunmam[ıi][şs]t[ıi]r)", "uygun bulunmadığının bildirimi"),
    (r"\bkabul\s+edilmemiştir\b", "talebin kabul edilmemesi"),
    (r"\bmümkün\s+(?:görülmemektedir|bulunmamaktad[ıi]r|değildir)", "talebin mümkün görülmemesi"),
    (r"\bdeğerlendirmeye\s+al[ıi]namam[ıi][şs]t[ıi]r\b", "usul/esastan red"),
    (r"\bkabul\s+edilmiştir\b", "talebin kabulü"),
    (r"\bonaylanm[ıi][şs]t[ıi]r\b", "onay bildirimi"),
    (r"\buygun\s+(?:görülmüştür|bulunmuştur)", "uygunluk bildirimi"),
    (r"\bbilgilerinizi\s+(?:ve\s+gereğini\s+)?rica\s+ederim", "resmi sonuç yazısı"),
)


def suggest_state_transition(
    reply_text: str,
    current_state: str = "Acik",
) -> Dict[str, Any]:
    """
    İdare/Müşavir cevabının metnine göre tavsiye edilen yeni durumu hesaplar.
    Veritabanını DEĞİŞTİRMEZ — yalnızca gerekçeli öneri döndürür.
    """
    low = tr_lower(reply_text or "")

    partial_hits = [desc for pat, desc in _PARTIAL_PATTERNS if re.search(pat, low)]
    if partial_hits:
        return {
            "current_state": current_state,
            "suggested_state": "Kismen_Cevaplandi",
            "reason": "Kısmi veya şartlı tamamlama işaretleri tespit edildi: " + ", ".join(partial_hits[:3]),
            "matched_signals": partial_hits,
            "confidence": 0.9 if len(partial_hits) >= 2 else 0.8,
        }

    closure_hits = [desc for pat, desc in _CLOSURE_PATTERNS if re.search(pat, low)]
    if closure_hits:
        return {
            "current_state": current_state,
            "suggested_state": "Kapatildi",
            "reason": "Kesin kapanış / Başkanlık Oluru işaretleri tespit edildi: " + ", ".join(closure_hits[:3]),
            "matched_signals": closure_hits,
            "confidence": 0.9,
        }

    answer_hits = [desc for pat, desc in _ANSWERED_PATTERNS if re.search(pat, low)]
    if answer_hits:
        return {
            "current_state": current_state,
            "suggested_state": "Cevaplandi",
            "reason": "Resmi hüküm / cevap ifadesi tespit edildi: " + ", ".join(answer_hits[:3]),
            "matched_signals": answer_hits,
            "confidence": 0.85 if len(answer_hits) >= 2 else 0.75,
        }

    return {
        "current_state": current_state,
        "suggested_state": current_state if current_state in VALID_STATES else "Acik",
        "reason": "Belirgin kapanış veya kısmi cevap kalıbı bulunamadı — mevcut durum korundu.",
        "matched_signals": [],
        "confidence": 0.4,
    }


def _read_canonical_text(fp: Path) -> str:
    if fp.suffix.lower() in TEXT_EXT:
        return fp.read_text(encoding="utf-8", errors="ignore")
    kanonik_dir = fp.parent / ".cache_ocr"
    kanonik = kanonik_dir / (fp.stem + KANONIK_SON_EK)
    if kanonik.exists():
        return kanonik.read_text(encoding="utf-8", errors="ignore")
    md = parse_any_document(fp)
    kanonik_dir.mkdir(parents=True, exist_ok=True)
    kanonik.write_text(md, encoding="utf-8")
    return md


def _resolve_target_docs(
    conn: sqlite3.Connection,
    project_id: str,
    reply_doc_id: str,
    reply_to: Optional[str],
    ilgi_refs: List[str],
    ilgi_raw: Optional[str],
    default_year: Optional[int],
) -> List[Dict[str, Any]]:
    """
    Cevap yazısının yanıtladığı hedef belgeleri (`--reply-to` + `İlgi:`) bulur.
    """
    targets: List[Dict[str, Any]] = []
    seen = {reply_doc_id}

    if reply_to:
        direct = get_document(conn, reply_to)
        if not direct:
            direct = match_doc_no_in_project(conn, project_id, reply_to, fuzz_threshold=88)
        if direct and direct["doc_id"] not in seen:
            seen.add(direct["doc_id"])
            targets.append(direct)

    ilgi_dates: List[str] = [r for r in ilgi_refs if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r)]
    if ilgi_raw:
        for mm in _RE_ILGI_TARIH.finditer(ilgi_raw):
            iso, _ = parse_tr_date(mm.group(0), default_year=default_year)
            if iso and iso not in ilgi_dates:
                ilgi_dates.append(iso)

    for ref in ilgi_refs:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}", ref):
            continue
        hedef = match_doc_no_in_project(
            conn, project_id, ref, ilgi_dates=ilgi_dates, fuzz_threshold=92
        )
        if hedef and hedef["doc_id"] not in seen:
            seen.add(hedef["doc_id"])
            targets.append(hedef)

    return targets


def _index_reply_chroma(
    md_text: str,
    card: Dict[str, Any],
    fp: Path,
    rel_path: str,
    project_id: str,
) -> int:
    """Cevap yazısını ChromaDB'ye STRICT `doc_role='correspondence_history'` ile yazar."""
    import importlib.util

    ing1_path = Path(__file__).resolve().parent.parent / "1_ingest.py"
    spec = importlib.util.spec_from_file_location("ing1_closed_loop", str(ing1_path))
    ing1 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ing1)

    from utils.retriever import detect_project_procurement_type, get_chroma_collection, get_embedding_model

    col = get_chroma_collection()
    emb = get_embedding_model()
    proc_type = detect_project_procurement_type(project_id)
    parcalar = ing1.split_markdown_into_legal_chunks(
        markdown_text=md_text,
        filename=fp.name,
        domain="idari",
        scope="project",
        project_id=project_id,
        project_name=project_id.replace("_", " ").title(),
        rel_path=rel_path,
        procurement_type=proc_type,
        folder_subsystem=None,
    )
    if not parcalar:
        return 0

    doc_id = card["doc_id"]
    sha = card["doc_sha256"]
    try:
        col.delete(where={"sqlite_doc_id": doc_id})
    except Exception:
        pass

    docs_content, metas, ids = [], [], []
    for ch in parcalar:
        m = ch["metadata"]
        m["doc_role"] = "correspondence_history"
        m["sender_role"] = card.get("sender_role") or "administration"
        m["evidence_weight"] = card.get("evidence_weight") or "RESMI_POZISYON_IDARE"
        m["doc_date"] = card.get("doc_date") or ""
        m["doc_no"] = card.get("doc_no") or ""
        m["sqlite_doc_id"] = doc_id
        m["doc_type"] = card.get("doc_type") or "idare_cevabi"
        docs_content.append(ch["content"])
        metas.append(m)
        ids.append(f"corr_{project_id}_{sha[:12]}_{uuid.uuid4().hex[:8]}")

    if hasattr(emb, "encode"):
        res = emb.encode(docs_content, return_dense=True)
        vectors = res["dense_vecs"].tolist() if isinstance(res, dict) and "dense_vecs" in res else (
            res.tolist() if hasattr(res, "tolist") else list(res)
        )
    else:
        vectors = [emb.encode_queries([t])[0].tolist() for t in docs_content]

    col.add(ids=ids, documents=docs_content, metadatas=metas, embeddings=vectors)
    return len(docs_content)


def record_admin_reply(
    *,
    reply_path: Path,
    project_id: str,
    reply_to: Optional[str] = None,
    role: str = "administration",
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
    confirm_state: Optional[str] = None,
    confirmed_by_human: bool = False,
    use_llm: bool = False,
    index_chroma: bool = False,
) -> Dict[str, Any]:
    """
    Resmi İdare/Müşavir cevabını kapalı döngüyle sisteme işler:
    - SQLite `documents` + `tags` + `links` (`cevaplar`)
    - İsteğe bağlı ChromaDB (`doc_role='correspondence_history'`)
    - Hedef yazılar için durum geçiş önerisi
    - Yalnızca `confirmed_by_human=True` ve geçerli `confirm_state` varsa durum geçişi uygular.
    """
    if role not in ("administration", "consultant"):
        raise ValueError(f"İdare/Müşavir cevabı için geçersiz rol: {role}")
    if confirm_state is not None and confirm_state not in VALID_STATES:
        raise ValueError(f"Geçersiz durum: {confirm_state} (geçerli: {VALID_STATES})")

    fp = Path(reply_path)
    if not fp.exists():
        raise FileNotFoundError(f"Cevap dosyası bulunamadı: {fp}")

    md_text = _read_canonical_text(fp)
    sha = hashlib.sha256(md_text.encode("utf-8")).hexdigest()
    doc_id = f"{project_id}::{sha[:24]}"

    try:
        rel_path = str(fp.resolve().relative_to(YUKLENICI_TALEPLERI_DIR.resolve()))
    except ValueError:
        rel_path = str(fp)

    doc_type = "idare_cevabi" if role == "administration" else "musavir_cevabi"
    default_year = None
    for part in fp.parts[:-1]:
        if re.fullmatch(r"20\d{2}", part):
            default_year = int(part)

    card_res = extract_identity_card(
        md_text,
        filename=fp.name,
        rel_path=rel_path,
        doc_sha256=sha,
        doc_id=doc_id,
        project_id=project_id,
        doc_type=doc_type,
        sender_role_hint=role,
        default_year=default_year,
        use_llm=use_llm,
    )
    card = card_res["card"]
    # Cevap yazısının kendisi işlendiğinde kesin pozisyon etiketi taşır
    card["evidence_weight"] = "RESMI_POZISYON_IDARE"

    owns_conn = False
    if conn is None:
        conn = connect(db_path) if db_path else connect()
        owns_conn = True

    try:
        prev = find_by_file_path(conn, project_id, rel_path)
        if prev and prev["doc_id"] != doc_id:
            # Dosya güncellendiğinde yeni sha kaydı oluşturulur, eski kayıt yerine bağlanır
            doc_id = card["doc_id"]

        upsert_document(conn, card)

        tags_to_add = []
        for t in (card.get("konu_etiketleri") or [])[:8]:
            tags_to_add.append({"tag_type": "konu", "tag_value": str(t)})
        for sr in extract_standard_refs(md_text)[:10]:
            tags_to_add.append({"tag_type": "standart", "tag_value": sr["canonical"]})
        for p in re.findall(r"Poz\s+\d+(?:[.\-]\d+)*", md_text, re.IGNORECASE)[:15]:
            pv = re.sub(r"(?i)^poz\s+", "", p).strip()
            if pv:
                tags_to_add.append({"tag_type": "poz_no", "tag_value": pv})
        if tags_to_add:
            add_tags(conn, doc_id, tags_to_add)

        targets = _resolve_target_docs(
            conn=conn,
            project_id=project_id,
            reply_doc_id=doc_id,
            reply_to=reply_to,
            ilgi_refs=card_res["ilgi_refs"],
            ilgi_raw=card.get("ilgi_raw"),
            default_year=default_year,
        )

        ilgi_span = next((s for s in card_res["spans"] if s.get("field") == "ilgi_raw"), None)
        linked_targets: List[Dict[str, Any]] = []
        suggestions: List[Dict[str, Any]] = []
        state_updates: List[Dict[str, Any]] = []

        for tgt in targets:
            t_id = tgt["doc_id"]
            if not link_exists(conn, doc_id, t_id, "cevaplar"):
                add_link(conn, doc_id, t_id, "cevaplar", resolved=True, evidence_span=ilgi_span)
            linked_targets.append(tgt)

            sug = suggest_state_transition(md_text, current_state=tgt.get("state") or "Acik")
            sug["target_doc_id"] = t_id
            sug["target_doc_no"] = tgt.get("doc_no")
            suggestions.append(sug)

            if confirmed_by_human and confirm_state:
                changed = update_state(
                    conn,
                    t_id,
                    confirm_state,
                    triggered_by_doc_id=doc_id,
                    confirmed_by_human=True,
                )
                state_updates.append({
                    "target_doc_id": t_id,
                    "old_state": tgt.get("state"),
                    "new_state": confirm_state,
                    "changed": changed,
                    "confirmed_by_human": True,
                })

        # Çözülememiş İlgi referansları varsa ileride 2. tur çözümleme için sakla
        for ref in card_res["ilgi_refs"]:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}", ref):
                continue
            matched = match_doc_no_in_project(conn, project_id, ref, fuzz_threshold=92)
            if not matched:
                if not link_exists(conn, doc_id, ref, "ilgi_zinciri"):
                    add_link(conn, doc_id, ref, "ilgi_zinciri", resolved=False, evidence_span=ilgi_span)

        chroma_count = 0
        if index_chroma:
            chroma_count = _index_reply_chroma(md_text, card, fp, rel_path, project_id)

        return {
            "reply_card": card,
            "ilgi_refs": card_res["ilgi_refs"],
            "linked_targets": linked_targets,
            "suggestions": suggestions,
            "state_updates": state_updates,
            "pending_state_confirmation": bool(targets) and not (confirmed_by_human and confirm_state),
            "chroma_chunks_added": chroma_count,
            "llm_errors": card_res["llm_errors"],
        }
    finally:
        if owns_conn:
            conn.close()
