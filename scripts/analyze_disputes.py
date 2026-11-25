# -*- coding: utf-8 -*-
"""
Uyuşmazlık Zinciri Keşfi ve Toplu Zincir Denetimi CLI Aracı
===========================================================
Kullanım örnekleri:
    # 1) Projedeki tüm uyuşmazlık kümelerini listele ve 0-LLM özet matrisini (.md/.docx) kaydet:
    .\venv\Scripts\python.exe -X utf8 scripts\analyze_disputes.py --project ikitelli_atakoy_metro

    # 2) En kritik 1. uyuşmazlık kümesini (K01) Sözleşme + Teknik Şartname + Mevzuata göre denetle:
    .\venv\Scripts\python.exe -X utf8 scripts\analyze_disputes.py --project ikitelli_atakoy_metro --cluster K01 --audit
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table

from utils.config import RAPORLAR_DIR
from utils.dispute_analyzer import (
    audit_dispute_cluster,
    build_project_dispute_matrix_markdown,
    discover_dispute_clusters,
)
from utils.ui_service import build_docx_bytes_from_markdown

console = Console(legacy_windows=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Proje yazışmalarından uyuşmazlık kümelerini keşfeder ve zincir bazlı denetler.")
    ap.add_argument("--project", required=True, help="proje_id (ör. ikitelli_atakoy_metro)")
    ap.add_argument("--cluster", default=None, help="Denetlenecek küme kodu (ör. K01) veya sıra no (1)")
    ap.add_argument("--audit", action="store_true", help="Seçili küme için LLM + Normatif DB + Verifier denetimi koştur")
    ap.add_argument("--only-multi", action="store_true", help="Yalnızca 2+ yazılık bağlı zincirleri göster")
    ap.add_argument("--db-path", default=None, help="Özel SQLite dosya yolu (varsayılan: data/project_graph.db)")
    ap.add_argument("--export-docx", action="store_true", help="Özet matrisi Word (.docx) olarak da kaydet")
    args = ap.parse_args()

    db_p = Path(args.db_path) if args.db_path else None
    disc = discover_dispute_clusters(
        project_id=args.project,
        db_path=db_p,
        include_singletons=not args.only_multi,
    )

    console.rule(f"[bold cyan]Uyuşmazlık Zinciri Analizi — {args.project}[/bold cyan]")
    console.print(
        f"Toplam Yazı: [bold]{disc['total_docs']}[/bold] | Küme: [bold]{disc['cluster_count']}[/bold] "
        f"(Çoklu Zincir: {disc['multi_doc_cluster_count']}) | Yüksek Risk: [bold red]{disc['high_risk_count']}[/bold red] | "
        f"Cevapsız Yüklenici: [yellow]{disc['unanswered_total']}[/yellow] | Eksik İlgi: {disc['missing_refs_total']}"
    )

    if not disc["clusters"]:
        console.print("[yellow]Bu proje için henüz yazışma kaydı bulunmuyor. Önce ingest_history.py çalıştırın.[/yellow]")
        return

    tbl = Table(title="Keşfedilen Uyuşmazlık / Yazışma Kümeleri (İlk 25)")
    tbl.add_column("Küme", style="cyan")
    tbl.add_column("Başlık")
    tbl.add_column("Yazı", justify="right")
    tbl.add_column("Tarih Aralığı")
    tbl.add_column("Y/İ/M/T")
    tbl.add_column("Cevapsız", justify="right")
    tbl.add_column("Eksik İlgi", justify="right")
    tbl.add_column("Risk", style="bold")

    for c in disc["clusters"][:25]:
        r_style = "red" if c["risk_level"] == "Yüksek" else ("yellow" if c["risk_level"] == "Orta" else "green")
        tbl.add_row(
            c["cluster_id"],
            c["title"][:56],
            str(c["doc_count"]),
            f"{c['date_start']}..{c['date_end']}",
            c["party_summary"],
            str(c["unanswered_count"]),
            str(c["missing_refs_count"]),
            f"[{r_style}]{c['risk_level']} ({c['risk_score']})[/{r_style}]",
        )
    console.print(tbl)

    # 0-LLM deterministik matris raporu kaydet
    RAPORLAR_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    md_text = build_project_dispute_matrix_markdown(disc)
    md_out = RAPORLAR_DIR / f"Uyusmazlik_Matrisi_{args.project}_{ts}.md"
    md_out.write_text(md_text, encoding="utf-8")
    console.print(f"[green]✔ Özet Matris (.md):[/green] {md_out}")

    if args.export_docx:
        docx_bytes = build_docx_bytes_from_markdown(md_text, f"Uyuşmazlık Kümeleri Matrisi — {args.project}")
        docx_out = md_out.with_suffix(".docx")
        docx_out.write_bytes(docx_bytes)
        console.print(f"[green]✔ Özet Matris (.docx):[/green] {docx_out}")

    if args.audit:
        target_cluster = None
        if args.cluster:
            q = args.cluster.strip().upper()
            if q.isdigit():
                q = f"K{int(q):02d}"
            target_cluster = next((c for c in disc["clusters"] if c["cluster_id"] == q), None)
        else:
            target_cluster = disc["clusters"][0]

        if not target_cluster:
            console.print(f"[bold red]![/bold red] Küme bulunamadı: {args.cluster}")
            sys.exit(1)

        console.rule(f"[bold magenta]Toplu Zincir Denetimi: {target_cluster['cluster_id']} — {target_cluster['title']}[/bold magenta]")
        res = audit_dispute_cluster(
            project_id=args.project,
            cluster_doc_ids=target_cluster["doc_ids"],
            cluster_title=target_cluster["title"],
            cluster_id=target_cluster["cluster_id"],
            db_path=db_p,
            progress_cb=lambda msg: console.print(f"  [cyan]▶[/cyan] {msg}"),
        )
        docx_bytes = build_docx_bytes_from_markdown(
            res["final_report"],
            f"Uyuşmazlık Zincir Raporu: {target_cluster['cluster_id']} — {target_cluster['title']}",
        )
        docx_path = Path(res["saved_report_path"]).with_suffix(".docx")
        docx_path.write_bytes(docx_bytes)
        console.print(f"[bold green]✔ Zincir Raporu (.md):[/bold green] {res['saved_report_path']}")
        console.print(f"[bold green]✔ Zincir Raporu (.docx):[/bold green] {docx_path}")


if __name__ == "__main__":
    main()
