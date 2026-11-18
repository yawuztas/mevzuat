# -*- coding: utf-8 -*-
"""
Adım 5.3 — Gerçek Yazışmalarla Sandbox Pilot Değerlendirme Aracı (20–30 Yazı).

Amaç:
    Gerçek taranmış İkitelli yazışmaları üzerinde (varsayılan kaynak:
    `_arsiv/TAHKİM/17.06.2026/Ekler/Süre Uzatım Yazılar ve İlgileri`)
    yalıtılmış geçici SQLite DB kullanarak Adım 3–5 hattını ölçer.
    Üretim veritabanı (`data/project_graph.db`) ve ChromaDB'ye ASLA dokunmaz.

Ölçülen 3 Metrik:
    1. Kart Doğruluğu & Tamlığı: tarih/sayı/konu/İlgi çıkarım oranı ve
       dosya adında tarih/kod taşıyan belgelerde bağımsız çapraz doğrulama.
    2. Zincir Hatırlama: havuz içinde karşılığı bulunan `İlgi:` bağlarının
       2 turlu çözümleme + `build_case_context` ile kaçak vermeden geri gelme oranı.
    3. Karşılaştırmalı Bağlam Kalitesi: aynı son mektupta Hafızasız mod vs
       Vaka Hafızası (+ isteğe bağlı `--with-llm` canlı Graf denetimi).

Kullanım:
    .\\venv\\Scripts\\python.exe -X utf8 scripts/run_pilot_eval.py --limit 25
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import fitz
from rich.console import Console
from rich.table import Table

from utils.card_extractor import _RE_ILGI_TARIH, extract_identity_card, parse_tr_date
from utils.case_context_builder import (
    DEFAULT_TOTAL_BUDGET_CHARS,
    assemble_budgeted_context,
    build_case_context,
)
from utils.closed_loop import suggest_state_transition
from utils.config import RAPORLAR_DIR
from utils.document_parser import parse_any_document
from utils.project_db import (
    add_link,
    add_tags,
    connect,
    get_unresolved_links,
    link_exists,
    match_doc_no_in_project,
    resolve_link,
    upsert_document,
)
from utils.standards import extract_standard_refs

console = Console(legacy_windows=False)

DEFAULT_PILOT_DIR = (
    PROJECT_ROOT / "_arsiv" / "TAHKİM" / "17.06.2026" / "Ekler" / "Süre Uzatım Yazılar ve İlgileri"
)


def _file_sha256(fp: Path) -> str:
    h = hashlib.sha256()
    with fp.open("rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()


def _infer_role_from_name(fp: Path) -> Tuple[Optional[str], str]:
    """Klasör/dosya adından gönderen rolü ipucu (belirsizse None döner)."""
    s = fp.name.lower()
    if any(k in s for k in ("yüklenici", "yuklenici", "aga-", "ati-", "atİ-", "atı-")):
        return "contractor", "yuklenici_yazisi"
    if any(k in s for k in ("müşavir", "musavir", "emay", "2016.03", "danışman", "danisman")):
        return "consultant", "musavir_cevabi"
    if any(k in s for k in ("İbb", "ibb", "s.19-", "s.20-", "s.21-", "s.22-", "s.23-")):
        return "administration", "idare_cevabi"
    return None, "resmi_yazi"


def _extract_filename_ground_truth(fp: Path) -> Dict[str, Optional[str]]:
    """
    Dosya adında açıkça bulunan bağımsız tarih/numara ipuçlarını çıkarır
    (Kart Doğruluğu metrik 1 için bağımsız çapraz kontrol).
    """
    name = fp.stem
    gt_date = None
    m_d = re.search(r"\((\d{2})\.(\d{2})\.(\d{4})\)", name)
    if m_d:
        gt_date = f"{m_d.group(3)}-{m_d.group(2)}-{m_d.group(1)}"

    gt_code = None
    m_c = (
        re.search(r"\b(S\.\d{2}-\d{3,5})\b", name, re.I)
        or re.search(r"\b(?:AGA|EMAY)[-](\d{3,5})\b", name, re.I)
        or re.search(r"\b(2016\.03[-/]GD[-/]\d{3,5})\b", name, re.I)
        or re.search(r"\b(AT[İI][-]AS[-]TR[-]PM[-]\d{3,5})\b", name, re.I)
        or re.search(r"^(\d{4})-(?:yüklenici|müşavir)", name, re.I)
    )
    if m_c:
        gt_code = m_c.group(1)
    return {"gt_date": gt_date, "gt_code": gt_code}


def _collect_unique_pdfs(source_dir: Path, limit: int, max_pages: int) -> List[Tuple[Path, int, str]]:
    """Aynı PDF'in farklı alt klasörlerdeki kopyalarını SHA-256 ile tekilleştirir."""
    seen_sha = set()
    selected: List[Tuple[Path, int, str]] = []
    for fp in sorted(source_dir.rglob("*.pdf")):
        if ".cache" in str(fp):
            continue
        fsha = _file_sha256(fp)
        if fsha in seen_sha:
            continue
        seen_sha.add(fsha)
        try:
            with fitz.open(fp) as pdf:
                pg = len(pdf)
        except Exception:
            pg = 999
        if pg <= max_pages:
            selected.append((fp, pg, fsha))
    # Kısa yazışma evraklarını (1-15 sf) önce alarak pilot çalışma süresini öngörülebilir tut
    selected.sort(key=lambda item: (item[1] > 15, item[0].name))
    return selected[:limit] if limit > 0 else selected


def _resolve_two_pass_local(conn, proj: str, doc_id: str, ilgi_refs: List[str], ilgi_raw: Optional[str], default_year: Optional[int]) -> int:
    ilgi_dates = [r for r in ilgi_refs if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r)]
    if ilgi_raw:
        for mm in _RE_ILGI_TARIH.finditer(ilgi_raw):
            iso, _ = parse_tr_date(mm.group(0), default_year=default_year)
            if iso and iso not in ilgi_dates:
                ilgi_dates.append(iso)
    linked = 0
    for ref in ilgi_refs:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}", ref):
            continue
        tgt = match_doc_no_in_project(conn, proj, ref, ilgi_dates=ilgi_dates, fuzz_threshold=92)
        if tgt and tgt["doc_id"] != doc_id:
            if not link_exists(conn, doc_id, tgt["doc_id"], "ilgi_zinciri"):
                add_link(conn, doc_id, tgt["doc_id"], "ilgi_zinciri", resolved=True)
            linked += 1
        elif not link_exists(conn, doc_id, ref, "ilgi_zinciri"):
            add_link(conn, doc_id, ref, "ilgi_zinciri", resolved=False)
    return linked


def main():
    ap = argparse.ArgumentParser(description="Adım 5.3 — Gerçek Yazışma Pilot Değerlendirme Aracı")
    ap.add_argument("--source-dir", default=str(DEFAULT_PILOT_DIR), help="Taranacak yazışma klasörü")
    ap.add_argument("--project-id", default="ikitelli_atakoy_metro", help="Pilot proje ID")
    ap.add_argument("--limit", type=int, default=25, help="İncelenecek benzersiz belge sayısı (varsayılan 25)")
    ap.add_argument("--max-pages", type=int, default=20, help="Pilot kapsamındaki maks. sayfa sayısı (ekli dev kararları atlamak için)")
    ap.add_argument("--use-llm", action="store_true", help="Kimlik kartında instructor+langextract zenginleştirmesi")
    ap.add_argument("--with-llm-audit", action="store_true", help="3. metrikte canlı LangGraph denetimi karşılaştır")
    ap.add_argument("--report-out", default=str(RAPORLAR_DIR / "pilot_eval_raporu.md"))
    args = ap.parse_args()

    src_dir = Path(args.source_dir)
    if not src_dir.exists():
        console.print(f"[bold red]![/bold red] Kaynak klasör bulunamadı: {src_dir}")
        sys.exit(1)

    pdfs = _collect_unique_pdfs(src_dir, limit=args.limit, max_pages=args.max_pages)
    if not pdfs:
        console.print("[yellow]Pilot için uygun PDF bulunamadı.[/yellow]")
        return

    console.rule(f"[bold cyan]Adım 5 Pilot Değerlendirme — {len(pdfs)} Benzersiz Gerçek Yazı[/bold cyan]")
    t0_all = time.time()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        db_path = tmp / "pilot_graph.db"
        conn = connect(db_path)
        try:
            records: List[Dict[str, Any]] = []
            # 1) Ayrıştırma + Kimlik Kartı Çıkarımı
            for idx, (fp, pages, fsha) in enumerate(pdfs, 1):
                t0 = time.time()
                role_hint, doc_type = _infer_role_from_name(fp)
                md_text = parse_any_document(fp)
                gt = _extract_filename_ground_truth(fp)
                def_year = int(gt["gt_date"][:4]) if gt["gt_date"] else None

                res = extract_identity_card(
                    md_text,
                    filename=fp.name,
                    rel_path=str(fp),
                    doc_sha256=hashlib.sha256(md_text.encode("utf-8")).hexdigest(),
                    doc_id=f"{args.project_id}::pilot_{idx}_{fsha[:12]}",
                    project_id=args.project_id,
                    doc_type=doc_type,
                    sender_role_hint=role_hint,
                    default_year=def_year,
                    use_llm=args.use_llm,
                )
                card = res["card"]
                upsert_document(conn, card)
                std_refs = extract_standard_refs(md_text)[:10]
                if std_refs:
                    add_tags(conn, card["doc_id"], [{"tag_type": "standart", "tag_value": r["canonical"]} for r in std_refs])

                _resolve_two_pass_local(
                    conn, args.project_id, card["doc_id"], res["ilgi_refs"], card.get("ilgi_raw"), def_year
                )

                records.append({
                    "fp": fp,
                    "pages": pages,
                    "card": card,
                    "ilgi_refs": res["ilgi_refs"],
                    "md_text": md_text,
                    "gt": gt,
                    "elapsed_s": round(time.time() - t0, 2),
                })
                console.print(
                    f"  [{idx}/{len(pdfs)}] {fp.name} ({pages} sf, {records[-1]['elapsed_s']}s) -> "
                    f"Tarih: {card.get('doc_date')} | Sayı: {card.get('doc_no')} | İlgi ref: {len(res['ilgi_refs'])}"
                )

            # 2) İkinci tur İlgi çözümleme (kronolojik sıradan bağımsız eksik kenarları tamamlama)
            unresolved = get_unresolved_links(conn, args.project_id)
            pass2_linked = 0
            for lnk in unresolved:
                ref = lnk["to_ref"]
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}", ref):
                    continue
                src_row = conn.execute("SELECT ilgi_raw, doc_date FROM documents WHERE doc_id=?", (lnk["from_doc_id"],)).fetchone()
                def_y = int(src_row["doc_date"][:4]) if (src_row and src_row["doc_date"]) else None
                ilgi_dates = []
                if src_row and src_row["ilgi_raw"]:
                    for mm in _RE_ILGI_TARIH.finditer(src_row["ilgi_raw"]):
                        iso, _ = parse_tr_date(mm.group(0), default_year=def_y)
                        if iso:
                            ilgi_dates.append(iso)
                tgt = match_doc_no_in_project(conn, args.project_id, ref, ilgi_dates=ilgi_dates, fuzz_threshold=92)
                if tgt and tgt["doc_id"] != lnk["from_doc_id"]:
                    if link_exists(conn, lnk["from_doc_id"], tgt["doc_id"], "ilgi_zinciri"):
                        conn.execute("DELETE FROM links WHERE link_id=?", (lnk["link_id"],))
                        conn.commit()
                    else:
                        resolve_link(conn, lnk["link_id"], tgt["doc_id"])
                    pass2_linked += 1

            # --- METRİK 1: Kart Doğruluğu & Tamlık ---
            total = len(records)
            has_date = sum(1 for r in records if r["card"].get("doc_date"))
            has_no = sum(1 for r in records if r["card"].get("doc_no"))
            has_subj = sum(1 for r in records if r["card"].get("subject"))
            has_ilgi = sum(1 for r in records if r["ilgi_refs"])
            auto_cnt = sum(1 for r in records if r["card"].get("review_status") == "auto_approved")

            date_gt_eval, date_gt_ok = 0, 0
            code_gt_eval, code_gt_ok = 0, 0
            mismatches = []
            for r in records:
                gt = r["gt"]
                c = r["card"]
                if gt["gt_date"]:
                    date_gt_eval += 1
                    if c.get("doc_date") == gt["gt_date"]:
                        date_gt_ok += 1
                    else:
                        mismatches.append(f"Tarih uyumsuz: {r['fp'].name} beklenen={gt['gt_date']} çıkan={c.get('doc_date')}")
                if gt["gt_code"]:
                    code_gt_eval += 1
                    norm_gt = re.sub(r"[-./_\s]+", "", gt["gt_code"]).replace("i", "I").replace("İ", "I").upper()
                    norm_ext = re.sub(r"[-./_\s]+", "", (c.get("doc_no") or "")).replace("i", "I").replace("İ", "I").upper()
                    if norm_gt and norm_gt in norm_ext:
                        code_gt_ok += 1
                    else:
                        mismatches.append(f"Sayı uyumsuz: {r['fp'].name} beklenen~{gt['gt_code']} çıkan={c.get('doc_no')}")

            # --- METRİK 2: Zincir Hatırlama (Havuz İçi Atıf Çözümleme + build_case_context) ---
            resolved_rows = conn.execute(
                "SELECT l.from_doc_id, l.to_ref, d.doc_no FROM links l "
                "JOIN documents d ON d.doc_id = l.from_doc_id "
                "WHERE d.project_id=? AND l.link_type='ilgi_zinciri' AND l.resolved=1",
                (args.project_id,),
            ).fetchall()
            expected_targets_by_src: Dict[str, set] = {}
            for row in resolved_rows:
                expected_targets_by_src.setdefault(row["from_doc_id"], set()).add(row["to_ref"])

            recalled_targets, expected_targets_total = 0, 0
            chain_cases: List[Dict[str, Any]] = []
            for r in records:
                cid = r["card"]["doc_id"]
                exp_set = expected_targets_by_src.get(cid)
                if not exp_set:
                    continue
                ctx = build_case_context(
                    r["md_text"],
                    doc_path=r["fp"],
                    project_id=args.project_id,
                    conn=conn,
                    use_semantic_history=False,
                )
                returned_ids = {d["doc_id"] for d in ctx["chain_docs"]} | {d["doc_id"] for d in ctx["incoming_responses"]}
                hits = exp_set & returned_ids
                expected_targets_total += len(exp_set)
                recalled_targets += len(hits)
                chain_cases.append({"record": r, "ctx": ctx, "expected": exp_set, "hits": hits})

            # Durum önerisi örneklemesi: resmi İdare/Müşavir cevapları üzerinde suggest_state_transition kontrolü
            admin_sug_stats: Dict[str, int] = {}
            for r in records:
                if r["card"].get("sender_role") in ("administration", "consultant"):
                    sg = suggest_state_transition(r["md_text"], current_state="Acik")["suggested_state"]
                    admin_sug_stats[sg] = admin_sug_stats.get(sg, 0) + 1

            # --- METRİK 3: Karşılaştırmalı Bağlam Kalitesi (En Zengin Zincirli Son Mektup) ---
            comp_md = ""
            if chain_cases:
                chain_cases.sort(key=lambda c: len(c["ctx"]["chain_docs"]) + len(c["ctx"]["incoming_responses"]), reverse=True)
                best_case = chain_cases[0]
                br = best_case["record"]
                bctx = best_case["ctx"]
                full_pkt, pkt_stats = assemble_budgeted_context(bctx["blocks"], max_chars=DEFAULT_TOTAL_BUDGET_CHARS)
                resmi_cnt = full_pkt.count("RESMİ POZİSYON")
                iddia_cnt = full_pkt.count("İDDİA (Yüklenici)")

                comp_md = (
                    f"- **Seçilen Hedef Yazı:** `{br['fp'].name}` (`{br['card'].get('doc_no')}` / `{br['card'].get('doc_date')}`)\n"
                    f"- **Eski Mod (Hafızasız — Tek Yazı):** Çözümlenen önceki yazı: `0`, "
                    f"önceki İdare/Müşavir pozisyonu: `0`, toplam tarihsel bağlam: `0 krk`\n"
                    f"- **Yeni Mod (Vaka Hafızası + Kanıt Ağırlığı):** Çekilen İlgi zinciri: `{len(bctx['chain_docs'])}` belge, "
                    f"yakalanan ekstra cevap: `{len(bctx['incoming_responses'])}`, "
                    f"`RESMİ POZİSYON` bloğu: `{resmi_cnt}`, `İDDİA` bloğu: `{iddia_cnt}`, "
                    f"bütçe kullanımı: `{pkt_stats['used_chars']}/{DEFAULT_TOTAL_BUDGET_CHARS} krk`\n"
                )

                if args.with_llm_audit:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("agents_mod", PROJECT_ROOT / "2_agents_graph.py")
                    ag = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(ag)
                    out_old = ag.create_audit_graph().invoke({
                        "doc_path": str(br["fp"]), "doc_text": br["md_text"],
                        "project_id": args.project_id, "procurement_type": "yapim",
                        "case_context": None, "router_result": None, "expert_analyses": {},
                        "final_report": "", "verification_notes": None,
                    })
                    out_new = ag.create_audit_graph().invoke({
                        "doc_path": str(br["fp"]), "doc_text": br["md_text"],
                        "project_id": args.project_id, "procurement_type": "yapim",
                        "case_context": bctx, "router_result": None, "expert_analyses": {},
                        "final_report": "", "verification_notes": None,
                    })
                    comp_md += (
                        f"- **Canlı LLM Rapor Uzunluğu (Hafızasız vs Vaka Hafızalı):** "
                        f"`{len(out_old.get('final_report', ''))}` vs `{len(out_new.get('final_report', ''))}` karakter\n"
                    )

            total_elapsed = round(time.time() - t0_all, 1)

            # --- Konsol Tablosu + Rapor Yazımı ---
            tbl = Table(title=f"Adım 5 Pilot Sonuçları ({total} Gerçek İkitelli Yazısı, {total_elapsed}s)")
            tbl.add_column("Metrik")
            tbl.add_column("Sonuç")
            tbl.add_row("Tarih Çıkarım Tamlığı", f"{has_date}/{total} (%{round(100*has_date/total, 1)})")
            tbl.add_row("Sayı / Ref Çıkarım Tamlığı", f"{has_no}/{total} (%{round(100*has_no/total, 1)})")
            tbl.add_row("Konu Çıkarım Tamlığı", f"{has_subj}/{total} (%{round(100*has_subj/total, 1)})")
            tbl.add_row("Dosya Adı Tarih Çapraz Doğruluğu", f"{date_gt_ok}/{date_gt_eval}" if date_gt_eval else "N/A")
            tbl.add_row("Dosya Adı Sayı Çapraz Doğruluğu", f"{code_gt_ok}/{code_gt_eval}" if code_gt_eval else "N/A")
            tbl.add_row("2. Tur Bağlanan İlgi Kenarı", str(pass2_linked))
            tbl.add_row("Zincir Hatırlama (Havuz İçi Recall)", f"{recalled_targets}/{expected_targets_total} (%{round(100*recalled_targets/expected_targets_total, 1) if expected_targets_total else 0.0})")
            tbl.add_row("Durum Makinesi Öneri Dağılımı", str(admin_sug_stats))
            console.print(tbl)

            report_path = Path(args.report_out)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            lines = [
                f"# Adım 5 Pilot Değerlendirme Raporu ({total} Gerçek İkitelli Yazısı)",
                "",
                f"- **Kaynak Dizin:** `{src_dir}`",
                f"- **İncelenen Benzersiz PDF:** {total} (maks. sayfa filtresi <= {args.max_pages}, toplam süre: {total_elapsed}s)",
                f"- **Ortam:** Tamamen yalıtılmış geçici SQLite (`project_graph` üretim DB'sine dokunulmadı)",
                "",
                "## 1. Kart Çıkarım Doğruluğu ve Tamlığı",
                f"- Tarih (`doc_date`): **{has_date}/{total}** (%{round(100*has_date/total, 1)})",
                f"- Evrak Sayısı (`doc_no`): **{has_no}/{total}** (%{round(100*has_no/total, 1)})",
                f"- Konu (`subject`): **{has_subj}/{total}** (%{round(100*has_subj/total, 1)})",
                f"- `İlgi:` referansı yakalanan yazı sayısı: **{has_ilgi}/{total}**",
                f"- Otomatik onay (`auto_approved`): **{auto_cnt}/{total}** | İnsan onay kuyruğu (`pending_review`): **{total - auto_cnt}/{total}**",
                f"- Bağımsız dosya adı tarih çapraz kontrolü: **{date_gt_ok}/{date_gt_eval}**",
                f"- Bağımsız dosya adı kod çapraz kontrolü: **{code_gt_ok}/{code_gt_eval}**",
            ]
            if mismatches:
                lines.append("\n### Tespit Edilen Çapraz Kontrol Uyumsuzlukları (Şeffaf Döküm)")
                for mm in mismatches:
                    lines.append(f"- {mm}")

            lines += [
                "",
                "## 2. Zincir Hatırlama (Havuz İçi İlgi & Cevap Çözümleme)",
                f"- Çözümlenmiş toplam `ilgi_zinciri` kenarı: **{len(resolved_rows)}** (2. turda eklenen: {pass2_linked})",
                f"- `build_case_context` zincir hatırlama (havuz içi doğrulanan hedefler): **{recalled_targets}/{expected_targets_total}**",
                f"- İdare/Müşavir yazıları durum geçiş öneri dağılımı: `{admin_sug_stats}`",
                "",
                "## 3. Karşılaştırmalı Bağlam Kalitesi (Hafızasız vs Vaka Hafızası)",
                comp_md or "- Zincir içeren belge bulunamadı.",
                "",
                "## Belge Bazlı Döküm",
                "| # | Dosya | Sayfa | Tarih | Sayı | Durum | İlgi Ref Sayısı |",
                "| :--- | :--- | :---: | :--- | :--- | :--- | :---: |",
            ]
            for i, r in enumerate(records, 1):
                c = r["card"]
                lines.append(
                    f"| {i} | `{r['fp'].name}` | {r['pages']} | `{c.get('doc_date') or '-'}` | "
                    f"`{c.get('doc_no') or '-'}` | `{c.get('review_status')}` | {len(r['ilgi_refs'])} |"
                )
            report_path.write_text("\n".join(lines), encoding="utf-8")
            console.print(f"\n[bold green]✔ Rapor kaydedildi:[/bold green] {report_path}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()
