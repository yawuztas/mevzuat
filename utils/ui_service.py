# -*- coding: utf-8 -*-
"""
InsaatAudit NiceGUI Web Stüdyosu — Arka Plan Servis Katmanı
===========================================================
UI bileşenlerinden bağımsız, birim test edilebilir saf Python servisleri:
1. ChromaDB Bilgi Ağacı & Disiplin Dağılımı + Doküman Parça Gezgini
2. SQLite (project_graph.db) Yazışma Soy Ağacı (Cytoscape.js elemanları) + İnsan Onayı
3. 6 Düğümlü LangGraph Canlı Denetim Akışı (stream_mode="updates") + Word (.docx) Çıktısı
4. Katman 1 Mevzuat Güncelleme Merkezi (mevzuat_sync + diff raporları)
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Inches, Pt, RGBColor

from utils.closed_loop import suggest_state_transition
from utils.config import (
    DATA_DIR,
    PROJE_EVRAKLARI_DIR,
    RAPORLAR_DIR,
    YUKLENICI_TALEPLERI_DIR,
)
from utils.document_parser import SUPPORTED_DOC_EXTENSIONS, parse_any_document
from utils.mevzuat_sync import MevzuatSyncEngine
from utils.project_db import (
    DEFAULT_DB_PATH,
    VALID_STATES,
    approve,
    connect,
    get_document,
    pending_review,
    update_state,
)
from utils.retriever import detect_project_procurement_type, get_chroma_collection, search_and_rerank

BASE_DIR = Path(__file__).resolve().parent.parent

DOC_TYPE_LABELS: Dict[str, str] = {
    "kanun": "Kanunlar & CB Kararları",
    "yonetmelik": "Yönetmelikler & Genel Şartnameler",
    "teblig_ve_kararname": "Tebliğler & Fiyat Farkı Esasları",
    "standart_norm_katalogu": "Teknik Standart Normları",
    "standart_form_sablonu": "Standart Formlar",
    "sozlesme": "Sözleşme & Ekleri",
    "idari_sartname": "İdari Şartname",
    "teknik_sartname": "Teknik Şartnameler",
    "birim_fiyat_tarifi": "Birim Fiyat Tarifleri",
    "zeyilname_ve_aciklama": "Zeyilnameler",
    "yuklenici_yazisi": "Yüklenici Yazıları",
    "idare_cevabi": "İdare Cevapları",
    "musavir_yazisi": "Müşavir Yazıları",
    "hakedis": "Hakediş Özetleri",
    "genel_referans": "Diğer Referanslar",
}

ROLE_LABELS: Dict[str, str] = {
    "contractor": "Yüklenici",
    "administration": "İdare",
    "consultant": "Müşavir",
    "joint": "Ortak / Tutanak",
}


# ==============================================================================
# 1. Proje Keşfi & Katman 1-2-3 Hafıza Ağacı (ECharts)
# ==============================================================================
def list_known_projects(data_dir: Optional[Path] = None) -> List[str]:
    root = Path(data_dir) if data_dir else DATA_DIR
    found = set()
    for sub in ("2_proje_evraklari", "3_yuklenici_talepleri"):
        d = root / sub
        if d.exists():
            for child in d.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    found.add(child.name)
    return sorted(found)


def get_memory_inventory_and_tree() -> Dict[str, Any]:
    """ChromaDB 'insaat_mevzuat' koleksiyonunu ECharts ağaç & grafik verisine dönüştürür."""
    col = get_chroma_collection()
    total = col.count()
    if total == 0:
        return {
            "total_vectors": 0,
            "layer_counts": {"global": 0, "project": 0, "correspondence": 0},
            "project_counts": {},
            "subsystem_counts": {},
            "tree": {"name": "Kalıcı Hafıza (Boş)", "children": []},
        }

    metas = col.get(include=["metadatas"]).get("metadatas") or []
    layer_counts = {"global": 0, "project_normative": 0, "correspondence_history": 0}
    project_counts: Counter = Counter()
    subsystem_counts: Counter = Counter()

    # Ağaç kırılımı: katman -> alt grup -> doküman -> chunk sayısı
    global_tree: Dict[str, Counter] = defaultdict(Counter)
    proj_tree: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    corr_tree: Dict[str, Counter] = defaultdict(Counter)

    for m in metas:
        scope = m.get("scope", "global")
        pid = m.get("project_id", "global")
        doc_role = m.get("doc_role", "normative_rule")
        doc_type = m.get("doc_type", "genel_referans")
        subsystem = m.get("subsystem", "genel")
        sf = m.get("source_file", "Bilinmeyen")

        subsystem_counts[subsystem] += 1
        project_counts[pid] += 1

        if doc_role == "correspondence_history":
            layer_counts["correspondence_history"] += 1
            corr_tree[pid][sf] += 1
        elif scope == "global":
            layer_counts["global"] += 1
            global_tree[doc_type][sf] += 1
        else:
            layer_counts["project_normative"] += 1
            proj_tree[pid][doc_type][sf] += 1

    # ECharts tree düğümleri oluştur (varsayılan 1. seviye açık, yapraklar kapalı)
    l1_children = []
    for dt in sorted(global_tree.keys()):
        files_counter = global_tree[dt]
        dt_sum = sum(files_counter.values())
        doc_nodes = [
            {
                "name": f"{sf} ({cnt})",
                "value": cnt,
                "meta": {"project_id": "global", "source_file": sf, "doc_type": dt, "layer": "Katman 1"},
            }
            for sf, cnt in sorted(files_counter.items())
        ]
        l1_children.append({
            "name": f"{DOC_TYPE_LABELS.get(dt, dt)} ({dt_sum:,})",
            "value": dt_sum,
            "collapsed": True,
            "children": doc_nodes,
        })

    l2_children = []
    for pid in sorted(proj_tree.keys()):
        dt_map = proj_tree[pid]
        p_sum = sum(sum(c.values()) for c in dt_map.values())
        dt_nodes = []
        for dt in sorted(dt_map.keys()):
            files_counter = dt_map[dt]
            dt_sum = sum(files_counter.values())
            doc_nodes = [
                {
                    "name": f"{sf} ({cnt})",
                    "value": cnt,
                    "meta": {"project_id": pid, "source_file": sf, "doc_type": dt, "layer": "Katman 2"},
                }
                for sf, cnt in sorted(files_counter.items())
            ]
            dt_nodes.append({
                "name": f"{DOC_TYPE_LABELS.get(dt, dt)} ({dt_sum:,})",
                "value": dt_sum,
                "collapsed": True,
                "children": doc_nodes,
            })
        l2_children.append({
            "name": f"{pid} ({p_sum:,})",
            "value": p_sum,
            "collapsed": True,
            "children": dt_nodes,
        })

    l3_children = []
    for pid in sorted(corr_tree.keys()):
        files_counter = corr_tree[pid]
        c_sum = sum(files_counter.values())
        doc_nodes = [
            {
                "name": f"{sf} ({cnt})",
                "value": cnt,
                "meta": {"project_id": pid, "source_file": sf, "doc_type": "correspondence", "layer": "Katman 3"},
            }
            for sf, cnt in sorted(files_counter.items())
        ]
        l3_children.append({
            "name": f"{pid} Yazışmaları ({c_sum})",
            "value": c_sum,
            "collapsed": False,
            "children": doc_nodes,
        })

    tree_root = {
        "name": f"InsaatAudit Hafıza ({len(metas):,})",
        "children": [
            {
                "name": f"Katman 1: Genel Mevzuat & Norm ({layer_counts['global']:,})",
                "value": layer_counts["global"],
                "collapsed": False,
                "children": l1_children,
            },
            {
                "name": f"Katman 2: Proje Sözleşme & Şartname ({layer_counts['project_normative']:,})",
                "value": layer_counts["project_normative"],
                "collapsed": False,
                "children": l2_children,
            },
            {
                "name": f"Katman 3: Yazışma Geçmişi ({layer_counts['correspondence_history']:,})",
                "value": layer_counts["correspondence_history"],
                "collapsed": True,
                "children": l3_children if l3_children else [{"name": "Henüz gerçek yazışma yüklenmedi (0)", "value": 0}],
            },
        ],
    }

    return {
        "total_vectors": len(metas),
        "layer_counts": layer_counts,
        "project_counts": dict(project_counts),
        "subsystem_counts": dict(subsystem_counts.most_common()),
        "tree": tree_root,
    }


def get_document_chunks(project_id: str, source_file: str, limit: int = 80) -> List[Dict[str, Any]]:
    """Belirli bir dosya ve proje için ChromaDB içindeki parçaları sayfa sırasıyla döndürür."""
    col = get_chroma_collection()
    res = col.get(
        where={"$and": [{"project_id": project_id}, {"source_file": source_file}]},
        include=["documents", "metadatas"],
    )
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    items = [
        {"content": d, "metadata": m}
        for d, m in zip(docs, metas)
    ]
    items.sort(key=lambda x: (x["metadata"].get("page_num", 0) or 0, x["metadata"].get("title", "")))
    return items[:limit]


def semantic_search_memory(
    query: str,
    project_id: Optional[str] = None,
    domain: Optional[str] = None,
    doc_role: Optional[str] = "normative_rule",
    top_k: int = 6,
) -> List[Dict[str, Any]]:
    if not query or not query.strip():
        return []
    eff_pid = None if (not project_id or project_id == "global") else project_id
    return search_and_rerank(
        query=query.strip(),
        domain=None if (not domain or domain == "Tümü") else domain,
        project_id=eff_pid,
        candidate_k=20,
        final_top_k=top_k,
        doc_role=None if (not doc_role or doc_role == "Tümü") else doc_role,
    )


# ==============================================================================
# 2. Yazışma Soy Ağacı (Cytoscape.js) & İnsan Onay Kuyruğu (project_graph.db)
# ==============================================================================
def get_correspondence_graph(
    db_path: Optional[Path] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """SQLite project_graph.db üzerinden Cytoscape graf elemanları + onay kuyruğu verisi üretir."""
    conn = connect(db_path)
    try:
        if project_id and project_id != "Tümü":
            doc_rows = conn.execute(
                "SELECT * FROM documents WHERE project_id=? ORDER BY doc_date ASC, created_at ASC",
                (project_id,),
            ).fetchall()
        else:
            doc_rows = conn.execute(
                "SELECT * FROM documents ORDER BY doc_date ASC, created_at ASC"
            ).fetchall()
        docs = [dict(r) for r in doc_rows]
        doc_ids = {d["doc_id"] for d in docs}

        # Tüm etiketler ve durum geçmişi
        tags_by_doc: Dict[str, List[str]] = defaultdict(list)
        for tr in conn.execute("SELECT doc_id, tag_type, tag_value FROM tags").fetchall():
            if tr["doc_id"] in doc_ids:
                tags_by_doc[tr["doc_id"]].append(f"{tr['tag_type']}:{tr['tag_value']}")

        links = []
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            links = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM links WHERE from_doc_id IN ({placeholders})",
                    tuple(doc_ids),
                ).fetchall()
            ]

        history_rows = []
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            history_rows = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM state_history WHERE doc_id IN ({placeholders}) ORDER BY changed_at DESC, history_id DESC",
                    tuple(doc_ids),
                ).fetchall()
            ]

        pend_rows = pending_review(conn, project_id=None if (not project_id or project_id == "Tümü") else project_id)

        elements: List[Dict[str, Any]] = []
        ghost_nodes_seen = set()

        for d in docs:
            did = d["doc_id"]
            d_no = d.get("doc_no") or "(Sayısız)"
            d_date = d.get("doc_date") or "Tarih ?"
            role = d.get("sender_role") or "contractor"
            state = d.get("state") or "Acik"
            rev = d.get("review_status") or "pending_review"
            subj_short = (d.get("subject") or "")[:36]
            elements.append({
                "data": {
                    "id": did,
                    "label": f"{d_no}\n{d_date}\n[{state}]",
                    "doc_no": d_no,
                    "doc_date": d_date,
                    "sender_role": role,
                    "role_tr": ROLE_LABELS.get(role, role),
                    "state": state,
                    "review_status": rev,
                    "subject": d.get("subject") or "",
                    "subj_short": subj_short,
                    "summary": d.get("summary") or "",
                    "evidence_weight": d.get("evidence_weight") or "",
                    "ilgi_raw": d.get("ilgi_raw") or "",
                    "file_path": d.get("file_path") or "",
                    "tags": ", ".join(tags_by_doc.get(did, [])),
                    "node_kind": "pending" if rev == "pending_review" else role,
                }
            })

        for lk in links:
            src = lk["from_doc_id"]
            tgt = lk["to_ref"]
            resolved = bool(lk.get("resolved"))
            if not resolved:
                ghost_id = f"unresolved::{tgt}"
                if ghost_id not in ghost_nodes_seen:
                    ghost_nodes_seen.add(ghost_id)
                    elements.append({
                        "data": {
                            "id": ghost_id,
                            "label": f"{tgt}\n(Arşivde Yok)",
                            "doc_no": tgt,
                            "doc_date": "-",
                            "sender_role": "unresolved",
                            "role_tr": "Çözülmemiş Referans",
                            "state": "Eksik",
                            "review_status": "unresolved",
                            "subject": f"İlgi satırında atıf yapılan '{tgt}' belgesi veritabanında henüz yok.",
                            "summary": "",
                            "evidence_weight": "",
                            "ilgi_raw": "",
                            "file_path": "",
                            "tags": "",
                            "node_kind": "unresolved",
                        }
                    })
                tgt_node = ghost_id
            else:
                if tgt not in doc_ids:
                    continue
                tgt_node = tgt

            elements.append({
                "data": {
                    "id": f"e_{lk['link_id']}",
                    "source": src,
                    "target": tgt_node,
                    "label": lk["link_type"],
                    "link_type": lk["link_type"],
                    "resolved": resolved,
                }
            })

        projects_in_db = sorted({r["project_id"] for r in conn.execute("SELECT DISTINCT project_id FROM documents").fetchall()})
        return {
            "elements": elements,
            "documents": docs,
            "pending_review": pend_rows,
            "state_history": history_rows,
            "projects": projects_in_db,
        }
    finally:
        conn.close()


def update_card_and_approve(
    doc_id: str,
    doc_date: Optional[str] = None,
    doc_no: Optional[str] = None,
    subject: Optional[str] = None,
    new_state: Optional[str] = None,
    confirmed_by_human: bool = True,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """İnsan onayıyla kimlik kartını düzeltir (`human_approved`) ve gerekirse durum geçişi uygular."""
    conn = connect(db_path)
    try:
        card = get_document(conn, doc_id)
        if not card:
            raise ValueError(f"Kayıt bulunamadı: {doc_id}")

        updates = []
        params: List[Any] = []
        if doc_date is not None and doc_date.strip():
            updates.append("doc_date=?")
            params.append(doc_date.strip())
        if doc_no is not None and doc_no.strip():
            updates.append("doc_no=?")
            params.append(doc_no.strip())
        if subject is not None and subject.strip():
            updates.append("subject=?")
            params.append(subject.strip())
        if updates:
            conn.execute(f"UPDATE documents SET {', '.join(updates)} WHERE doc_id=?", (*params, doc_id))
            conn.commit()

        approve(conn, doc_id)

        state_changed = False
        if new_state and new_state in VALID_STATES and new_state != card.get("state"):
            if not confirmed_by_human:
                raise ValueError("İnsan onayı (confirmed_by_human=True) olmadan durum değiştirilemez.")
            state_changed = update_state(conn, doc_id, new_state, triggered_by_doc_id="UI_HUMAN_APPROVAL", confirmed_by_human=True)

        updated = get_document(conn, doc_id)
        return {"card": updated, "state_changed": state_changed}
    finally:
        conn.close()


# ==============================================================================
# 3. Dilekçe Yükleme, Canlı 6 Düğümlü Denetim & Word (.docx) Dışa Aktarma
# ==============================================================================
def save_uploaded_petition(filename: str, content_bytes: bytes, project_id: str) -> Path:
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("Geçersiz dosya adı.")
    ext = Path(safe_name).suffix.lower()
    if ext not in SUPPORTED_DOC_EXTENSIONS:
        raise ValueError(f"Desteklenmeyen dosya uzantısı: {ext}")
    safe_proj = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id or "ornek_proje")
    dest_dir = YUKLENICI_TALEPLERI_DIR / safe_proj / "_ui_yuklenenler"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name
    dest_path.write_bytes(content_bytes)
    return dest_path


def list_sample_petitions() -> List[Dict[str, str]]:
    """Deneme için erişilebilir yüklenici evraklarını (ornek_proje + Downloads ATİ-AS-TR-PM) listeler."""
    items: List[Dict[str, str]] = []
    if YUKLENICI_TALEPLERI_DIR.exists():
        for p in sorted(YUKLENICI_TALEPLERI_DIR.rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_DOC_EXTENSIONS and ".cache" not in str(p).lower():
                if "1_yuklenici_yazilari" in p.parts or "2_idare_cevaplari" in p.parts or "4_hakedis_ozetleri" in p.parts:
                    continue
                if p.suffix.lower() == ".pdf" and "paftalar_ve_semalar" in p.parts:
                    continue
                items.append({"label": f"[Havuz] {p.relative_to(YUKLENICI_TALEPLERI_DIR).as_posix()}", "path": str(p)})
    dl_dir = Path.home() / "Downloads"
    if dl_dir.exists():
        for name in ("ATİ-AS-TR-PM-9443.pdf", "ATİ-AS-TR-PM-9400.pdf"):
            cand = dl_dir / name
            if cand.exists():
                items.append({"label": f"[İndirilenler] {cand.name}", "path": str(cand)})
    return items


def _load_agents_graph_module():
    spec = importlib.util.spec_from_file_location("agents_graph_mod", BASE_DIR / "2_agents_graph.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


NODE_LABELS: Dict[str, str] = {
    "reader": "1/6 Evrak Okuyucu & OCR",
    "case_builder": "2/6 Vaka Hafızası (SQLite İlgi Zinciri)",
    "router": "3/6 Router Ajanı (Disiplin & Alan Tespiti)",
    "experts": "4/6 Uzman Ajanlar & Hop-2 Standart Arama",
    "chief_auditor": "5/6 Baş Denetçi (Sentez Raporu)",
    "verifier": "6/6 Citation Verifier (Madde Doğrulama)",
}


def run_audit_streaming(
    file_path: Path,
    project_id: Optional[str] = None,
    progress_cb: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """2_agents_graph.py akışını stream_mode='updates' ile düğüm bazlı gerçek ilerleme bildirerek koşturur."""
    ag = _load_agents_graph_module()
    compiled_app = ag.create_audit_graph()
    eff_pid = None if (not project_id or project_id == "Otomatik / Klasörden") else project_id

    initial_state = {
        "doc_path": str(file_path),
        "doc_text": "",
        "project_id": eff_pid,
        "procurement_type": detect_project_procurement_type(eff_pid) if eff_pid else None,
        "case_context": None,
        "router_result": None,
        "expert_analyses": {},
        "final_report": "",
        "verification_notes": None,
    }

    final_state: Dict[str, Any] = dict(initial_state)
    for event in compiled_app.stream(initial_state, stream_mode="updates"):
        for node_name, patch in event.items():
            if isinstance(patch, dict):
                final_state.update(patch)
            if progress_cb:
                summary = _summarize_node_patch(node_name, patch or {}, final_state)
                progress_cb(node_name, summary, patch or {})

    RAPORLAR_DIR.mkdir(parents=True, exist_ok=True)
    report_filename = f"Denetim_Raporu_{Path(file_path).stem}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    report_path = RAPORLAR_DIR / report_filename
    report_path.write_text(final_state.get("final_report", ""), encoding="utf-8")
    final_state["saved_report_path"] = str(report_path)
    return final_state


def _summarize_node_patch(node_name: str, patch: Dict[str, Any], full_state: Dict[str, Any]) -> str:
    if node_name == "reader":
        txt_len = len(patch.get("doc_text", ""))
        pid = patch.get("project_id", "global")
        ptype = patch.get("procurement_type") or "ortak"
        return f"Proje={pid} ({ptype}) | Okunan metin: {txt_len:,} krk"
    if node_name == "case_builder":
        st = (patch.get("case_context") or {}).get("stats", {})
        return f"İlgi zinciri={st.get('chain_count', 0)} belge | İlişkili={st.get('related_count', 0)}"
    if node_name == "router":
        rr = patch.get("router_result") or {}
        doms = ", ".join(rr.get("active_domains", []))
        subs = ", ".join(rr.get("target_subsystems", []))
        return f"Tür: {rr.get('document_type', '-')} | Alanlar: [{doms}] | Alt sistem: [{subs}]"
    if node_name == "experts":
        ex = patch.get("expert_analyses") or {}
        return f"Tamamlanan uzman analizleri: {', '.join(ex.keys())}"
    if node_name == "chief_auditor":
        return f"Taslak denetim raporu üretildi ({len(patch.get('final_report', '')):,} krk)"
    if node_name == "verifier":
        notes = patch.get("verification_notes") or ""
        m = re.search(r"Atıf Doğruluk Oranı:\*\*\s*(%[\d.,]+)", notes)
        return f"Atıf doğrulaması tamamlandı ({m.group(1) if m else 'tamam'})"
    return "Tamamlandı"


def _add_formatted_runs(p: docx.text.paragraph.Paragraph, text: str, font_size: float = 10.0) -> None:
    """Markdown **kalın** ve `kod` biçimlerini Word run'larına çevirir."""
    tokens = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text)
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**"):
            r = p.add_run(tok[2:-2])
            r.bold = True
            r.font.name = "Calibri"
            r.font.size = Pt(font_size)
            r.font.color.rgb = RGBColor(16, 44, 87)
        elif tok.startswith("`") and tok.endswith("`"):
            r = p.add_run(tok[1:-1])
            r.font.name = "Consolas"
            r.font.size = Pt(max(font_size - 0.5, 8.5))
            r.font.color.rgb = RGBColor(15, 118, 110)
        else:
            r = p.add_run(tok)
            r.font.name = "Calibri"
            r.font.size = Pt(font_size)
            r.font.color.rgb = RGBColor(33, 37, 41)


def _flush_md_table(doc_obj: docx.Document, table_lines: List[str]) -> None:
    rows: List[List[str]] = []
    for ln in table_lines:
        stripped = ln.strip().strip("|")
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in stripped.split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c is not None):
            continue
        rows.append(cells)
    if not rows:
        return
    cols = max(len(r) for r in rows)
    if cols == 0:
        return
    tbl = doc_obj.add_table(rows=len(rows), cols=cols)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for r_i, row in enumerate(rows):
        for c_i in range(cols):
            val = row[c_i] if c_i < len(row) else ""
            cell = tbl.cell(r_i, c_i)
            tcPr = cell._element.get_or_add_tcPr()
            fill = "102C57" if r_i == 0 else ("F8F9FA" if r_i % 2 == 1 else "FFFFFF")
            tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill}"/>'))
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(val)
            r.font.name = "Calibri"
            r.font.size = Pt(9)
            if r_i == 0:
                r.bold = True
                r.font.color.rgb = RGBColor(255, 255, 255)
            else:
                r.font.color.rgb = RGBColor(33, 37, 41)
    doc_obj.add_paragraph().paragraph_format.space_after = Pt(4)


def build_docx_bytes_from_markdown(markdown_text: str, report_title: str = "Teknik ve Hukuki Denetim Raporu") -> bytes:
    """Denetim raporunu kurumsal biçimli Word (.docx) baytlarına dönüştürür."""
    d = docx.Document()
    for s in d.sections:
        s.top_margin = Inches(0.75)
        s.bottom_margin = Inches(0.75)
        s.left_margin = Inches(0.8)
        s.right_margin = Inches(0.8)

    p_top = d.add_paragraph()
    p_top.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_top = p_top.add_run(report_title)
    r_top.bold = True
    r_top.font.name = "Calibri"
    r_top.font.size = Pt(15)
    r_top.font.color.rgb = RGBColor(16, 44, 87)

    p_sub = d.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_sub = p_sub.add_run(f"InsaatAudit Çoklu Ajan Denetim Çıktısı — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    r_sub.font.name = "Calibri"
    r_sub.font.size = Pt(9.5)
    r_sub.font.color.rgb = RGBColor(100, 116, 139)

    lines = markdown_text.replace("\r\n", "\n").splitlines()
    table_buf: List[str] = []

    def _flush_tbl() -> None:
        if table_buf:
            _flush_md_table(d, table_buf)
            table_buf.clear()

    for ln in lines:
        s = ln.strip()
        if s.startswith("|") and "|" in s[1:]:
            table_buf.append(ln)
            continue
        _flush_tbl()
        if not s or s == "---":
            continue
        if s.startswith("### "):
            h = d.add_heading(level=3)
            run = h.add_run(s[4:].strip())
            run.font.name = "Calibri"
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(186, 24, 27)
        elif s.startswith("## "):
            h = d.add_heading(level=2)
            run = h.add_run(s[3:].strip())
            run.font.name = "Calibri"
            run.font.size = Pt(13)
            run.font.color.rgb = RGBColor(16, 44, 87)
        elif s.startswith("# "):
            h = d.add_heading(level=1)
            run = h.add_run(s[2:].strip())
            run.font.name = "Calibri"
            run.font.size = Pt(14.5)
            run.font.color.rgb = RGBColor(16, 44, 87)
        elif s.startswith(">"):
            clean_q = re.sub(r"^>\s*(?:\[![A-Z]+\]\s*)?", "", s)
            if clean_q:
                p = d.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.25)
                _add_formatted_runs(p, clean_q, font_size=9.5)
        elif s.startswith("- ") or s.startswith("* "):
            p = d.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(2)
            _add_formatted_runs(p, s[2:].strip(), font_size=10)
        else:
            p = d.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            _add_formatted_runs(p, s, font_size=10)

    _flush_tbl()
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ==============================================================================
# 4. Mevzuat Güncelleme Merkezi (sync_mevzuat)
# ==============================================================================
def get_legislation_sync_status() -> Dict[str, Any]:
    engine = MevzuatSyncEngine()
    reg = engine.load_registry()
    sources = reg.get("sources", {})
    rows = []
    for src in engine.catalog:
        rec = sources.get(src.key, {})
        rows.append({
            "key": src.key,
            "title": src.title,
            "source_kind": src.source_kind,
            "version_tag": rec.get("version_tag") or "-",
            "rg_tarih": rec.get("rg_tarih") or "-",
            "char_count": rec.get("char_count") or 0,
            "last_checked_at": rec.get("last_checked_at") or "-",
            "rel_path": src.rel_path,
        })

    reports = []
    if RAPORLAR_DIR.exists():
        for rp in sorted(RAPORLAR_DIR.glob("mevzuat_guncelleme_*.md"), reverse=True)[:10]:
            reports.append({"name": rp.name, "path": str(rp)})

    latest_report_text = ""
    if reports:
        latest_report_text = Path(reports[0]["path"]).read_text(encoding="utf-8", errors="ignore")

    return {
        "updated_at": reg.get("updated_at") or "-",
        "total_catalog": len(engine.catalog),
        "rows": rows,
        "reports": reports,
        "latest_report_text": latest_report_text,
    }


def run_legislation_check(deep: bool = True) -> Dict[str, Any]:
    return MevzuatSyncEngine().check_updates(deep=deep)


def run_legislation_sync(ingest: bool = False) -> Dict[str, Any]:
    engine = MevzuatSyncEngine()
    res = engine.sync_all(purge_legacy=False)
    if ingest:
        import subprocess
        import sys
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(BASE_DIR / "1_ingest.py")],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        res["ingest_returncode"] = proc.returncode
        res["ingest_log"] = (proc.stdout or "")[-3000:]
    return res
