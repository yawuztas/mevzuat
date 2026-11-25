# -*- coding: utf-8 -*-
"""
Uyuşmazlık Zinciri Kümeleyici & Toplu Yazışma Denetim Motoru
============================================================
Yüzlerce/binlerce proje yazışmasını (`data/project_graph.db`) `İlgi:` ve `cevaplar`
bağlarına göre otomatik uyuşmazlık kümelerine (bağlı bileşenlere) ayırır:

1. Deterministik Kümeleme (`discover_dispute_clusters` — 0 LLM, anlık):
   - Çözümlenmiş `ilgi_zinciri` + `cevaplar` kenarlarıyla bağlı yazıları birleştirir.
   - Arşivde eksik olan aynı `İlgi:` evrak numarasına atıf yapan yazıları da köprüler
     (`bridge_shared_unresolved=True`).
   - Her küme için: kronoloji, tarih aralığı, taraf dağılımı, cevapsız kalan yüklenici
     yazıları, arşivde eksik `İlgi:` referansları, ortak standartlar, çatışma sinyalleri
     ve risk puanı (0–100) hesaplar.

2. Proje Geneli Uyuşmazlık Matrisi (`build_project_dispute_matrix_markdown` — 0 LLM):
   - 400+ yazının tamamından tek tıkla yönetici özet tablosu ve eksik evrak listesi üretir.

3. Seçili Uyuşmazlık Zinciri Toplu Denetimi (`audit_dispute_cluster` — Normatif DB + LLM + Verifier):
   - Seçilen kümedeki tüm yazışmaları kronolojik ve `[KANIT TÜRÜ]` ağırlıklı bütçeyle paketler.
   - Yalnızca Normatif DB (`vector_db/insaat_mevzuat`) üzerinden bağlayıcı sözleşme,
     teknik şartname, kanun ve Hop-2 standart normlarını çeker.
   - Tarafların pozisyon değişimlerini, çelişen beyanları, atlanan cevapları ve usul/süre
     risklerini analiz eder; tüm kanun/şartname/standart atıflarını `citation_verifier_node`
     ile doğrular.
"""
from __future__ import annotations

import importlib.util
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from utils.case_context_builder import (
    DEFAULT_TOTAL_BUDGET_CHARS,
    PRIORITY_ILGI_CHAIN,
    PRIORITY_NORMATIVE,
    PRIORITY_STANDARDS,
    _format_card_summary_line,
    _format_verbatim_block,
    _load_document_text,
    assemble_budgeted_context,
    format_evidence_label,
)
from utils.config import RAPORLAR_DIR, YUKLENICI_TALEPLERI_DIR
from utils.project_db import DEFAULT_DB_PATH, connect
from utils.retriever import detect_project_procurement_type, search_and_rerank
from utils.standards import extract_standard_refs
from utils.text_tr import tr_lower

BASE_DIR = Path(__file__).resolve().parent.parent

# Uyuşmazlık / ihtilaf risk sinyalleri (deterministik ağırlıklı sözlük)
_DISPUTE_SIGNAL_RULES: Tuple[Tuple[str, str, int], ...] = (
    (r"\btahkim\b|\bdava\b|\bihtar(?:name)?\b", "Tahkim / İhtar", 28),
    (r"\breddedilmi[şs]tir\b|\bkabul\s+edilmemi[şs]tir\b|\buygun\s+(?:görülmemi[şs]tir|bulunmam[ıi][şs]t[ıi]r)\b", "Resmi Ret / Uygunsuzluk", 16),
    (r"\bitiraz\b|\buyuşmazl[ıi]k\b|\bihtilaf\b", "İtiraz / Uyuşmazlık", 12),
    (r"\bsüre\s+uzat[ıi]m[ıi]\b|\bek\s+süre\b|\bgecikme\b|\bceza\b|\bkesinti\b", "Süre / Gecikme / Ceza", 12),
    (r"\bek\s+maliyet\b|\bfiyat\s+fark[ıi]\b|\byeni\s+birim\s+fiyat\b|\bhakedi[şs]\s+itiraz", "Mali Talep / Fiyat Farkı", 12),
    (r"\buygunsuzluk\b|\bncr\b|\bpunch\b|\bba[şs]ar[ıi]s[ıi]z\b|\bfail(?:ed)?\b|\bsat\s+ret", "Test / Kalite Uygunsuzluğu", 10),
    (r"\beksik\s+(?:belge|bilgi|imalat|test)\b|\brevize\b|\bsorumluluk\b|\bkusur\b", "Eksik / Revize / Sorumluluk", 8),
)

_SUBSYSTEM_TO_DOMAIN = {
    "sinyalizasyon_cbtc": "elektromekanik",
    "cer_gucu_ve_elektrifikasyon": "elektromekanik",
    "zayif_akim_ve_scada": "elektromekanik",
    "havalandirma_ve_yangin_tvs": "elektromekanik",
    "asansor_ve_yuruyen_merdiven": "elektromekanik",
    "genel_rams_ve_emniyet": "elektromekanik",
    "genel_elektromekanik": "elektromekanik",
    "tunel_ve_kazilar": "insaat",
    "demiryolu_ustyapi_ve_ray": "insaat",
    "istasyon_kaba_ince": "insaat",
    "genel_insaat": "insaat",
}


class _UnionFind:
    def __init__(self, items: Sequence[str]):
        self.parent = {x: x for x in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


def _norm_ref_key(ref: str) -> str:
    s = (ref or "").replace("i", "I").replace("İ", "I").upper().strip()
    return re.sub(r"[-./_\s]+", "-", s).strip("-")


def _parse_iso_date(d: Optional[str]) -> Optional[datetime]:
    if not d:
        return None
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d")
    except Exception:
        return None


def _pick_cluster_title(docs: List[Dict[str, Any]], standards: List[str], subsystems: List[str]) -> str:
    """Küme için en açıklayıcı başlığı seçer (boş/çok kısa konuları eler)."""
    candidates: List[str] = []
    for d in docs:
        subj = re.sub(r"\s+", " ", (d.get("subject") or "").strip())
        if len(subj) >= 6:
            candidates.append(subj)
    if candidates:
        # En erken ve bilgilendirici konu (çoğu zaman uyuşmazlığın kök talebidir)
        best = candidates[0]
        if len(best) > 84:
            best = best[:81].rstrip() + "..."
        return best
    if standards:
        return f"Standart İlişkili Yazışma ({', '.join(standards[:2])})"
    if subsystems:
        return f"{subsystems[0]} Yazışması"
    first_no = next((d.get("doc_no") for d in docs if d.get("doc_no")), None)
    return f"Evrak {first_no}" if first_no else "Konusuz Yazışma"


def discover_dispute_clusters(
    conn: Optional[sqlite3.Connection] = None,
    project_id: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
    include_singletons: bool = True,
    bridge_shared_unresolved: bool = True,
) -> Dict[str, Any]:
    """
    SQLite `project_graph.db` içindeki tüm yazışmaları `İlgi:` / `cevaplar` kenarları ve
    ortak çözülmemiş `İlgi:` referanslarıyla uyuşmazlık kümelerine ayırır.
    """
    owns_conn = False
    if conn is None:
        conn = connect(db_path) if db_path else connect(DEFAULT_DB_PATH)
        owns_conn = True

    try:
        if project_id and project_id != "Tümü":
            doc_rows = conn.execute(
                "SELECT * FROM documents WHERE project_id=? ORDER BY COALESCE(doc_date, '9999-99-99') ASC, created_at ASC",
                (project_id,),
            ).fetchall()
        else:
            doc_rows = conn.execute(
                "SELECT * FROM documents ORDER BY COALESCE(doc_date, '9999-99-99') ASC, created_at ASC"
            ).fetchall()

        docs = [dict(r) for r in doc_rows]
        if not docs:
            return {
                "project_id": project_id or "Tümü",
                "total_docs": 0,
                "cluster_count": 0,
                "multi_doc_cluster_count": 0,
                "high_risk_count": 0,
                "unanswered_total": 0,
                "missing_refs_total": 0,
                "clusters": [],
            }

        doc_map = {d["doc_id"]: d for d in docs}
        doc_ids = list(doc_map.keys())
        placeholders = ",".join("?" for _ in doc_ids)

        link_rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM links WHERE from_doc_id IN ({placeholders}) AND link_type IN ('ilgi_zinciri', 'cevaplar')",
                tuple(doc_ids),
            ).fetchall()
        ]
        tag_rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT doc_id, tag_type, tag_value FROM tags WHERE doc_id IN ({placeholders})",
                tuple(doc_ids),
            ).fetchall()
        ]

        tags_by_doc: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for tr in tag_rows:
            tags_by_doc[tr["doc_id"]].append((tr["tag_type"], tr["tag_value"]))

        uf = _UnionFind(doc_ids)
        outgoing_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        incoming_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        unresolved_ref_to_docs: Dict[Tuple[str, str], List[str]] = defaultdict(list)

        for lk in link_rows:
            src = lk["from_doc_id"]
            tgt = lk["to_ref"]
            outgoing_by_doc[src].append(lk)
            if lk["resolved"] and tgt in doc_map:
                if doc_map[src]["project_id"] == doc_map[tgt]["project_id"]:
                    uf.union(src, tgt)
                    incoming_by_doc[tgt].append(lk)
            elif not lk["resolved"] and bridge_shared_unresolved:
                nk = _norm_ref_key(tgt)
                if len(nk) >= 5:
                    unresolved_ref_to_docs[(doc_map[src]["project_id"], nk)].append(src)

        if bridge_shared_unresolved:
            for (_, _), members in unresolved_ref_to_docs.items():
                if len(members) >= 2:
                    anchor = members[0]
                    for m in members[1:]:
                        uf.union(anchor, m)

        groups: Dict[str, List[str]] = defaultdict(list)
        for did in doc_ids:
            groups[uf.find(did)].append(did)

        clusters: List[Dict[str, Any]] = []
        for comp_ids in groups.values():
            if not include_singletons and len(comp_ids) < 2:
                continue
            comp_docs = sorted(
                (doc_map[d] for d in comp_ids),
                key=lambda x: (x.get("doc_date") or "9999-99-99", x.get("doc_no") or "", x["doc_id"]),
            )
            comp_set = set(comp_ids)
            proj = comp_docs[0]["project_id"]

            party_counts = Counter((d.get("sender_role") or "unknown") for d in comp_docs)
            dates = [d["doc_date"] for d in comp_docs if d.get("doc_date")]
            date_start = min(dates) if dates else None
            date_end = max(dates) if dates else None
            dt_s, dt_e = _parse_iso_date(date_start), _parse_iso_date(date_end)
            span_days = max(0, (dt_e - dt_s).days) if (dt_s and dt_e) else 0

            # Arşivde eksik İlgi referansları
            missing_refs_list: List[str] = []
            seen_miss_norm = set()
            for did in comp_ids:
                for lk in outgoing_by_doc.get(did, []):
                    if not lk["resolved"]:
                        nk = _norm_ref_key(lk["to_ref"])
                        if nk and nk not in seen_miss_norm:
                            seen_miss_norm.add(nk)
                            missing_refs_list.append(lk["to_ref"])

            # Cevapsız kalan yüklenici yazıları (kendisine İdare veya Müşavir'den gelen ok yok + state Kapatildi/Cevaplandi değil)
            unanswered_docs: List[Dict[str, Any]] = []
            for d in comp_docs:
                if d.get("sender_role") != "contractor":
                    continue
                if d.get("state") in ("Cevaplandi", "Kapatildi"):
                    continue
                has_official_reply = any(
                    doc_map.get(lk["from_doc_id"], {}).get("sender_role") in ("administration", "consultant")
                    for lk in incoming_by_doc.get(d["doc_id"], [])
                )
                if not has_official_reply:
                    unanswered_docs.append({
                        "doc_id": d["doc_id"],
                        "doc_date": d.get("doc_date"),
                        "doc_no": d.get("doc_no"),
                        "subject": d.get("subject"),
                    })

            # Ortak standartlar, alt sistemler, pozlar
            std_counter: Counter = Counter()
            sub_counter: Counter = Counter()
            poz_counter: Counter = Counter()
            for did in comp_ids:
                for tt, tv in tags_by_doc.get(did, []):
                    if tt == "standart":
                        std_counter[tv] += 1
                    elif tt == "alt_sistem":
                        sub_counter[tv] += 1
                    elif tt == "poz_no":
                        poz_counter[tv] += 1

            shared_standards = [k for k, _ in std_counter.most_common(10)]
            subsystems = [k for k, _ in sub_counter.most_common(6)]
            poz_nos = [k for k, _ in poz_counter.most_common(8)]

            # Deterministik uyuşmazlık sinyal ve risk puanı (0–100)
            corpus_blob = tr_lower(
                "\n".join(f"{d.get('subject') or ''} {d.get('summary') or ''} {d.get('ilgi_raw') or ''}" for d in comp_docs)
            )
            matched_signals: List[str] = []
            signal_pts = 0
            for pat, label, pts in _DISPUTE_SIGNAL_RULES:
                if re.search(pat, corpus_blob, re.IGNORECASE):
                    matched_signals.append(label)
                    signal_pts += pts

            has_bilateral = (
                party_counts.get("contractor", 0) > 0
                and (party_counts.get("administration", 0) + party_counts.get("consultant", 0)) > 0
            )
            structure_pts = 0
            if len(comp_docs) >= 2:
                structure_pts += min(24, (len(comp_docs) - 1) * 5)
            if has_bilateral:
                structure_pts += 12
            if unanswered_docs:
                structure_pts += min(15, len(unanswered_docs) * 5)
            if missing_refs_list:
                structure_pts += min(10, len(missing_refs_list) * 3)
            if span_days >= 60:
                structure_pts += 8

            risk_score = min(100, signal_pts + structure_pts)
            risk_level = "Yüksek" if risk_score >= 55 else ("Orta" if risk_score >= 28 else "Düşük")

            timeline = []
            for d in comp_docs:
                did = d["doc_id"]
                resolved_out = [
                    doc_map[lk["to_ref"]].get("doc_no") or lk["to_ref"]
                    for lk in outgoing_by_doc.get(did, [])
                    if lk["resolved"] and lk["to_ref"] in comp_set
                ]
                timeline.append({
                    "doc_id": did,
                    "doc_date": d.get("doc_date") or "-",
                    "doc_no": d.get("doc_no") or "(Sayısız)",
                    "sender_role": d.get("sender_role") or "unknown",
                    "doc_type": d.get("doc_type") or "",
                    "evidence_weight": d.get("evidence_weight") or "",
                    "state": d.get("state") or "Acik",
                    "review_status": d.get("review_status") or "",
                    "subject": d.get("subject") or "",
                    "summary": d.get("summary") or "",
                    "refs_in_cluster": resolved_out,
                })

            clusters.append({
                "project_id": proj,
                "title": _pick_cluster_title(comp_docs, shared_standards, subsystems),
                "doc_ids": [d["doc_id"] for d in comp_docs],
                "doc_count": len(comp_docs),
                "date_start": date_start or "-",
                "date_end": date_end or "-",
                "span_days": span_days,
                "party_counts": dict(party_counts),
                "party_summary": (
                    f"Y:{party_counts.get('contractor', 0)} / "
                    f"İ:{party_counts.get('administration', 0)} / "
                    f"M:{party_counts.get('consultant', 0)} / "
                    f"T:{party_counts.get('joint', 0)}"
                ),
                "unanswered_docs": unanswered_docs,
                "unanswered_count": len(unanswered_docs),
                "missing_refs": missing_refs_list,
                "missing_refs_count": len(missing_refs_list),
                "shared_standards": shared_standards,
                "subsystems": subsystems,
                "poz_nos": poz_nos,
                "dispute_signals": matched_signals,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "timeline": timeline,
            })

        # Öncelik sıralaması: çoklu yazışma kümeleri + yüksek risk puanı + belge sayısı
        clusters.sort(
            key=lambda c: (
                1 if c["doc_count"] >= 2 else 0,
                c["risk_score"],
                c["doc_count"],
                c["date_end"],
            ),
            reverse=True,
        )
        for idx, c in enumerate(clusters, 1):
            c["cluster_id"] = f"K{idx:02d}"

        return {
            "project_id": project_id or "Tümü",
            "total_docs": len(docs),
            "cluster_count": len(clusters),
            "multi_doc_cluster_count": sum(1 for c in clusters if c["doc_count"] >= 2),
            "high_risk_count": sum(1 for c in clusters if c["risk_level"] == "Yüksek"),
            "unanswered_total": sum(c["unanswered_count"] for c in clusters),
            "missing_refs_total": sum(c["missing_refs_count"] for c in clusters),
            "clusters": clusters,
        }
    finally:
        if owns_conn:
            conn.close()


def build_project_dispute_matrix_markdown(discovery: Dict[str, Any]) -> str:
    """Tüm keşfedilen uyuşmazlık kümelerini anlık (0 LLM) kurumsal Markdown matrisine döker."""
    proj = discovery.get("project_id", "Tümü")
    clusters = discovery.get("clusters", [])
    lines = [
        f"# PROJE YAZIŞMA VE UYUŞMAZLIK KÜMELERİ ÖZET MATRİSİ — {str(proj).upper()}",
        "",
        f"- **Oluşturulma Zamanı:** {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        f"- **Toplam İndekslenmiş Yazışma:** {discovery.get('total_docs', 0)}",
        f"- **Keşfedilen Toplam Küme:** {discovery.get('cluster_count', 0)} "
        f"(Çoklu Zincir: {discovery.get('multi_doc_cluster_count', 0)})",
        f"- **Yüksek Riskli Uyuşmazlık Kümesi:** {discovery.get('high_risk_count', 0)}",
        f"- **Cevapsız Kalan Yüklenici Yazısı:** {discovery.get('unanswered_total', 0)}",
        f"- **Arşivde Eksik Tespit Edilen `İlgi:` Referansı:** {discovery.get('missing_refs_total', 0)}",
        "",
        "## 1. UYUŞMAZLIK KÜMELERİ SIRALAMASI",
        "",
        "| Küme | Konu / Başlık | Yazı | Tarih Aralığı | Taraflar (Y/İ/M/T) | Cevapsız | Eksik İlgi | Risk | Sinyaller |",
        "| :--- | :--- | :---: | :--- | :--- | :---: | :---: | :---: | :--- |",
    ]
    if not clusters:
        lines.append("| - | Henüz yazışma kaydı yok | 0 | - | - | 0 | 0 | - | - |")
    else:
        for c in clusters:
            sigs = ", ".join(c["dispute_signals"][:3]) or "-"
            drange = f"{c['date_start']} → {c['date_end']}" if c["date_start"] != c["date_end"] else c["date_start"]
            title_clean = c["title"].replace("|", "/")
            lines.append(
                f"| `{c['cluster_id']}` | {title_clean} | {c['doc_count']} | {drange} | "
                f"{c['party_summary']} | {c['unanswered_count']} | {c['missing_refs_count']} | "
                f"**{c['risk_level']} ({c['risk_score']})** | {sigs} |"
            )

    # En kritik çoklu kümelerin kronoloji ve eksik belge detayı
    top_multi = [c for c in clusters if c["doc_count"] >= 2 or c["risk_level"] == "Yüksek"][:15]
    if top_multi:
        lines.extend(["", "## 2. ÖNCELİKLİ UYUŞMAZLIK ZİNCİRLERİ DETAYI", ""])
        for c in top_multi:
            lines.append(f"### {c['cluster_id']} — {c['title']} ({c['doc_count']} Yazı · Risk: {c['risk_level']} {c['risk_score']}/100)")
            if c["shared_standards"]:
                lines.append(f"- **Ortak Standartlar:** `{', '.join(c['shared_standards'])}`")
            if c["subsystems"]:
                lines.append(f"- **Disiplinler:** `{', '.join(c['subsystems'])}`")
            if c["missing_refs"]:
                lines.append(f"- **Arşivde Eksik `İlgi:` Evrakları:** `{', '.join(c['missing_refs'][:12])}`")
            if c["unanswered_docs"]:
                un_str = ", ".join(f"{u.get('doc_no') or '?'} ({u.get('doc_date') or '?'})" for u in c["unanswered_docs"][:8])
                lines.append(f"- **Cevapsız Yüklenici Yazıları:** {un_str}")
            lines.append("")
            lines.append("| Tarih | Evrak No | Taraf | Durum | Konu |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for item in c["timeline"][:25]:
                subj_c = (item["subject"] or "-").replace("|", "/")[:90]
                lines.append(
                    f"| {item['doc_date']} | `{item['doc_no']}` | {item['sender_role']} | {item['state']} | {subj_c} |"
                )
            lines.append("")

    return "\n".join(lines)


def _load_agents_graph_module():
    spec = importlib.util.spec_from_file_location("agents_graph_dispute", BASE_DIR / "2_agents_graph.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def audit_dispute_cluster(
    project_id: str,
    cluster_doc_ids: Sequence[str],
    *,
    cluster_title: str = "",
    cluster_id: str = "K01",
    db_path: Optional[Path] = None,
    history_base_dir: Path = YUKLENICI_TALEPLERI_DIR,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Seçili uyuşmazlık kümesindeki TÜM yazışmaları kronolojik ve `[KANIT TÜRÜ]` ağırlığıyla derler,
    yalnızca Normatif DB (`vector_db/insaat_mevzuat`) üzerinden bağlayıcı sözleşme + teknik şartname +
    kanun + Hop-2 standartları çeker, çelişki ve risk denetim raporunu üretip `citation_verifier_node`
    ile doğrular.
    """
    if not cluster_doc_ids:
        raise ValueError("Denetlenecek kümede belge bulunamadı.")

    def _emit(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    _emit("1/4 Uyuşmazlık kümesi yazışmaları ve kanıt ağırlıkları derleniyor...")
    conn = connect(db_path) if db_path else connect(DEFAULT_DB_PATH)
    try:
        placeholders = ",".join("?" for _ in cluster_doc_ids)
        rows = conn.execute(
            f"SELECT * FROM documents WHERE doc_id IN ({placeholders}) "
            f"ORDER BY COALESCE(doc_date, '9999-99-99') ASC, created_at ASC",
            tuple(cluster_doc_ids),
        ).fetchall()
        docs = [dict(r) for r in rows]
        if not docs:
            raise ValueError("Verilen doc_id'ler veritabanında bulunamadı.")

        tag_rows = conn.execute(
            f"SELECT doc_id, tag_type, tag_value FROM tags WHERE doc_id IN ({placeholders})",
            tuple(cluster_doc_ids),
        ).fetchall()
        unresolved_rows = conn.execute(
            f"SELECT from_doc_id, to_ref FROM links WHERE from_doc_id IN ({placeholders}) AND resolved=0 AND link_type='ilgi_zinciri'",
            tuple(cluster_doc_ids),
        ).fetchall()
    finally:
        conn.close()

    standards: List[str] = []
    subsystems: List[str] = []
    poz_nos: List[str] = []
    for tr in tag_rows:
        tt, tv = tr["tag_type"], tr["tag_value"]
        if tt == "standart" and tv not in standards:
            standards.append(tv)
        elif tt == "alt_sistem" and tv not in subsystems:
            subsystems.append(tv)
        elif tt == "poz_no" and tv not in poz_nos:
            poz_nos.append(tv)

    missing_refs = list(dict.fromkeys(r["to_ref"] for r in unresolved_rows))
    eff_title = cluster_title or _pick_cluster_title(docs, standards, subsystems)

    # Kronoloji bloklarını bütçe içinde derle:
    # - İlk talep + son 2 yazı + tüm İdare/Müşavir resmi cevaplarından en kritik 4'ü tam metin (Priority 1)
    # - Diğer ara yazılar kronolojik özet satırı (Priority 2)
    verbatim_indices = set()
    if docs:
        verbatim_indices.add(0)
        verbatim_indices.add(len(docs) - 1)
        if len(docs) >= 2:
            verbatim_indices.add(len(docs) - 2)
    official_indices = [
        idx for idx, d in enumerate(docs)
        if d.get("sender_role") in ("administration", "consultant", "joint")
    ]
    for oi in official_indices[-4:]:
        verbatim_indices.add(oi)

    blocks: List[Dict[str, Any]] = []
    summary_lines = [f"--- [TÜM KÜME KRONOLOJİK ÖZETİ ({len(docs)} YAZIŞMA)] ---"]
    for idx, d in enumerate(docs):
        summary_lines.append(_format_card_summary_line(d, extra_note=f"Sıra #{idx + 1}"))
        if idx in verbatim_indices:
            full_txt, _ = _load_document_text(d, base_dir=history_base_dir)
            blocks.append({
                "priority": PRIORITY_ILGI_CHAIN,
                "category": "cluster_verbatim",
                "allow_truncate": True,
                "text": _format_verbatim_block(
                    d,
                    full_txt,
                    relation_note=f"Uyuşmazlık Zinciri #{idx + 1}/{len(docs)}",
                    max_single_chars=9000,
                ),
            })

    blocks.append({
        "priority": PRIORITY_ILGI_CHAIN,
        "category": "cluster_timeline_summary",
        "allow_truncate": True,
        "text": "\n".join(summary_lines),
    })

    # 2. Normatif DB (`vector_db/insaat_mevzuat`) araması — ASLA yazışma DB'ye karışmaz!
    _emit("2/4 Bağlayıcı sözleşme, teknik şartname ve mevzuat maddeleri taranıyor (vector_db)...")
    proc_type = detect_project_procurement_type(project_id)
    query_seed = " ".join(
        [eff_title]
        + [d.get("subject") or "" for d in docs[:6]]
        + standards[:6]
        + poz_nos[:4]
    )[:600]

    domains = ["mevzuat", "idari"]
    tech_subs: Dict[str, List[str]] = defaultdict(list)
    for sub in subsystems:
        dom = _SUBSYSTEM_TO_DOMAIN.get(sub)
        if dom:
            tech_subs[dom].append(sub)
            if dom not in domains:
                domains.append(dom)

    retrieved_norm_chunks: List[Dict[str, Any]] = []
    seen_chunk_ids = set()
    for dom in domains:
        dom_subs = tech_subs.get(dom) or None
        hits = search_and_rerank(
            query=query_seed,
            domain=dom,
            subsystems=dom_subs,
            project_id=project_id,
            procurement_type=proc_type,
            candidate_k=20,
            final_top_k=4,
            doc_role="normative_rule",
        )
        for h in hits:
            if h["id"] not in seen_chunk_ids:
                seen_chunk_ids.add(h["id"])
                retrieved_norm_chunks.append(h)

    # Hop-2 standart içi okuma (en çok 4 standart)
    std_pool = list(standards)
    for h in retrieved_norm_chunks:
        for sc in (h.get("metadata", {}).get("standard_codes") or "").split("|"):
            sc = sc.strip()
            if sc and sc not in std_pool:
                std_pool.append(sc)
    for code in std_pool[:4]:
        s_hits = search_and_rerank(
            query=f"{code} {eff_title}",
            project_id=project_id,
            procurement_type=proc_type,
            candidate_k=10,
            final_top_k=2,
            doc_role="normative_rule",
            doc_type_filter=["standart_norm_katalogu"],
        )
        for sh in s_hits:
            if sh["id"] not in seen_chunk_ids:
                seen_chunk_ids.add(sh["id"])
                retrieved_norm_chunks.append(sh)

    for idx, ch in enumerate(retrieved_norm_chunks, 1):
        m = ch.get("metadata", {})
        ev_lbl = format_evidence_label(doc_type=m.get("doc_type", ""), doc_role="normative_rule")
        pg = f"Sayfa {m.get('page_num')}" if (m.get("page_num") or 0) > 0 else "Dijital Belge"
        prio = PRIORITY_STANDARDS if m.get("doc_type") == "standart_norm_katalogu" else PRIORITY_NORMATIVE
        blocks.append({
            "priority": prio,
            "category": "normative" if prio == PRIORITY_NORMATIVE else "standards",
            "allow_truncate": True,
            "text": (
                f"[KANIT TÜRÜ: {ev_lbl}]\n"
                f"--- [Bağlayıcı Kaynak {idx}: {m.get('source_file', '?')} ({pg}) - {m.get('title', '')}] ---\n"
                f"{ch['content']}"
            ),
        })

    budgeted_ctx, budget_stats = assemble_budgeted_context(blocks, max_chars=DEFAULT_TOTAL_BUDGET_CHARS)

    # 3. LLM Toplu Uyuşmazlık & Çelişki Sentezi
    _emit("3/4 Baş Denetçi yazışmalar arası çelişki ve sözleşme uyuşmazlık raporunu sentezliyor...")
    ag = _load_agents_graph_module()
    from langchain_core.messages import HumanMessage, SystemMessage

    sys_prompt = (
        "Sen Kamu Yapım & Raylı Sistem Sözleşmeleri Kıdemli Baş Denetçisi ve Tahkim/Uyuşmazlık Uzmanısın.\n"
        "Sana bir projenin aynı uyuşmazlık zincirine ait TÜM kronolojik yazışmaları (Yüklenici, İdare, Müşavir, Tutanak) "
        "ile bağlayıcı Sözleşme, Teknik Şartname, Mevzuat ve Standart maddeleri birlikte veriliyor.\n\n"
        "KESİN KANIT DİSİPLİNİ:\n"
        "- `[KANIT TÜRÜ: BAĞLAYICI KURAL]` tek bağlayıcı hukuki/teknik hükümdür.\n"
        "- `[KANIT TÜRÜ: RESMİ POZİSYON]` İdare/Müşavirin önceki resmi iradesidir.\n"
        "- `[KANIT TÜRÜ: İDDİA (Yüklenici)]` tek taraflı beyandır; asla kesin kural gibi kullanma, "
        "fakat yüklenicinin kendi önceki yazılarıyla çelişip çelişmediğini ve atladığı İdare cevaplarını mutlaka yakala!\n\n"
        "RAPOR YAPISI:\n"
        "# TOPLU YAZIŞMA ZİNCİRİ VE UYUŞMAZLIK DENETİM RAPORU\n"
        "## 1. UYUŞMAZLIK ÖZETİ VE KRONOLOJİ TABLOSU\n"
        "## 2. TARAFLARIN POZİSYON EVRİMİ, BEYAN ÇELİŞKİLERİ VE ATLANAN CEVAPLAR\n"
        "## 3. BAĞLAYICI SÖZLEŞME, TEKNİK ŞARTNAME VE MEVZUAT DEĞERLENDİRMESİ\n"
        "## 4. USUL, SÜRE AŞIMI VE EKSİK ARŞİV BELGELERİ TESPİTİ\n"
        "## 5. İDARE İÇİN NİHAİ RİSK KARARI VE AKSİYON PLANI"
    )
    user_prompt = (
        f"PROJE: {project_id.upper()} ({proc_type or 'ortak'})\n"
        f"UYUŞMAZLIK KÜMESİ: {cluster_id} — {eff_title}\n"
        f"KÜMEDEKİ TOPLAM YAZIŞMA: {len(docs)} adet\n"
        f"ORTAK STANDARTLAR: {', '.join(standards) or 'Yok'}\n"
        f"ARŞİVDE EKSİK İLGİ REFERANSLARI: {', '.join(missing_refs) or 'Yok'}\n\n"
        f"BÜTÇELENMİŞ KRONOLOJİ VE BAĞLAYICI KAYNAK PAKETİ ({budget_stats['used_chars']}/{budget_stats['max_chars']} krk):\n"
        f"{budgeted_ctx}\n\n"
        "Lütfen somut tarih, evrak numarası ve bağlayıcı madde numaralarına dayanarak kapsamlı uyuşmazlık ve çelişki raporunu üret."
    )
    draft_report = ag.safe_llm_invoke([SystemMessage(content=sys_prompt), HumanMessage(content=user_prompt)])

    # 4. Citation Verifier doğrulaması (yalnızca Normatif DB `vector_db`)
    _emit("4/4 Rapordaki tüm kanun, şartname ve standart atıfları doğrulanıyor (Citation Verifier)...")
    verify_res = ag.citation_verifier_node({
        "doc_path": f"{project_id}_{cluster_id}.md",
        "doc_text": "",
        "project_id": project_id,
        "procurement_type": proc_type,
        "case_context": None,
        "router_result": {},
        "expert_analyses": {"cluster": {"retrieved_chunks": retrieved_norm_chunks}},
        "final_report": draft_report,
        "verification_notes": None,
    })
    final_report = verify_res["final_report"]

    RAPORLAR_DIR.mkdir(parents=True, exist_ok=True)
    safe_cid = re.sub(r"[^a-zA-Z0-9_-]", "_", cluster_id)
    out_path = RAPORLAR_DIR / f"Uyusmazlik_Zincir_Raporu_{project_id}_{safe_cid}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    out_path.write_text(final_report, encoding="utf-8")

    return {
        "cluster_id": cluster_id,
        "title": eff_title,
        "doc_count": len(docs),
        "normative_chunks_used": len(retrieved_norm_chunks),
        "missing_refs": missing_refs,
        "final_report": final_report,
        "verification_notes": verify_res.get("verification_notes", ""),
        "saved_report_path": str(out_path),
    }
