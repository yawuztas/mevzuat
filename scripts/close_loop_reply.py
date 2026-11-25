# -*- coding: utf-8 -*-
"""
Adım 5.1 & 5.2 — Kapalı Döngü İdare Cevabı Geri Giriş CLI'ı.

Kullanım örnekleri:
    # Etkileşimli onay (insan onayıyla durum makinesi güncellemesi):
    .\\venv\\Scripts\\python.exe scripts/close_loop_reply.py ^
        --project ikitelli_atakoy_metro ^
        --file data/3_yuklenici_talepleri/ikitelli_atakoy_metro/2_idare_cevaplari/2023/2023-05-18_S.23-401_cevap.md ^
        --reply-to YK-2023-4236

    # Otomatik onay bypass'sız, insan parametresiyle kesin geçiş + ChromaDB kaydı:
    .\\venv\\Scripts\\python.exe scripts/close_loop_reply.py ^
        --project ikitelli_atakoy_metro ^
        --file <cevap.pdf|.md> --reply-to <doc_no> --confirm-state Cevaplandi --yes --chroma
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table

from utils.closed_loop import record_admin_reply
from utils.project_db import VALID_STATES, connect, update_state

console = Console(legacy_windows=False)


def main():
    ap = argparse.ArgumentParser(description="Kapalı Döngü İdare/Müşavir Cevabı Geri Giriş Aracı (Adım 5)")
    ap.add_argument("--project", required=True, help="proje_id (ör. ikitelli_atakoy_metro)")
    ap.add_argument("--file", required=True, help="İdare/Müşavir resmi cevap dosyası (.md/.pdf/.docx)")
    ap.add_argument("--reply-to", default=None, help="Yanıtlanan hedef yüklenici doc_no veya doc_id (opsiyonel)")
    ap.add_argument("--role", default="administration", choices=["administration", "consultant"])
    ap.add_argument("--confirm-state", default=None, choices=list(VALID_STATES),
                    help="Doğrudan verilecek yeni durum (yalnızca --yes ile otomatik uygulanır)")
    ap.add_argument("--yes", action="store_true", help="--confirm-state değerini soru sormadan onayla")
    ap.add_argument("--no-confirm", action="store_true", help="Durumu değiştirme, yalnızca öneri raporla")
    ap.add_argument("--chroma", action="store_true", help="Ayrı Yazışma ChromaDB'sine (vector_db_yazismalar / proje_yazismalari) da yaz")
    ap.add_argument("--use-llm", action="store_true", help="instructor + langextract zenginleştirmesi")
    args = ap.parse_args()

    fp = Path(args.file)
    conn = connect()
    try:
        auto_confirm = bool(args.yes and args.confirm_state and not args.no_confirm)
        res = record_admin_reply(
            reply_path=fp,
            project_id=args.project,
            reply_to=args.reply_to,
            role=args.role,
            conn=conn,
            confirm_state=args.confirm_state if auto_confirm else None,
            confirmed_by_human=auto_confirm,
            use_llm=args.use_llm,
            index_chroma=args.chroma,
        )

        card = res["reply_card"]
        console.rule(f"[bold cyan]Kapalı Döngü Cevap Kaydı — {args.project}[/bold cyan]")
        console.print(
            f"  [green]✔ Kaydedildi:[/green] doc_id=`{card['doc_id']}` | Tarih: {card.get('doc_date')} | "
            f"Sayı: {card.get('doc_no')} | Ağırlık: [bold]{card.get('evidence_weight')}[/bold]"
        )
        if res["chroma_chunks_added"]:
            console.print(f"  [green]✔ ChromaDB:[/green] {res['chroma_chunks_added']} parça (`correspondence_history`)")

        if not res["linked_targets"]:
            console.print("[yellow]! Otomatik veya --reply-to ile eşleşen hedef talep bulunamadı.[/yellow]")
            return

        tbl = Table(title="Yanıtlanan Talepler ve Durum Makinesi Önerileri")
        tbl.add_column("Hedef doc_id")
        tbl.add_column("Sayı / Tarih")
        tbl.add_column("Mevcut Durum")
        tbl.add_column("Önerilen Durum")
        tbl.add_column("Gerekçe")

        for tgt, sug in zip(res["linked_targets"], res["suggestions"]):
            tbl.add_row(
                tgt["doc_id"],
                f"{tgt.get('doc_no') or '?'} ({tgt.get('doc_date') or '?'})",
                sug["current_state"],
                f"{sug['suggested_state']} (%{int(sug['confidence'] * 100)})",
                sug["reason"],
            )
        console.print(tbl)

        if auto_confirm:
            for up in res["state_updates"]:
                console.print(
                    f"  [bold green]✔ Durum Güncellendi (Onaylı):[/bold green] "
                    f"{up['target_doc_id']}: {up['old_state']} -> {up['new_state']}"
                )
            return

        if args.no_confirm:
            console.print("[dim]--no-confirm nedeniyle durum değiştirilmedi.[/dim]")
            return

        # Etkileşimli insan onayı
        state_choices = {str(i): s for i, s in enumerate(VALID_STATES, 1)}
        for tgt, sug in zip(res["linked_targets"], res["suggestions"]):
            console.print(
                f"\n[bold]Hedef:[/bold] `{tgt['doc_id']}` ({tgt.get('doc_no')}) | "
                f"Mevcut: `{sug['current_state']}` → Önerilen: [yellow]{sug['suggested_state']}[/yellow]"
            )
            ans = input(
                "Onayla [O] / Durum seç [1=Acik 2=Kismen_Cevaplandi 3=Cevaplandi 4=Kapatildi] / Atla [A] > "
            ).strip().lower()
            chosen = None
            if ans in ("o", "e", "onayla", "evet"):
                chosen = args.confirm_state or sug["suggested_state"]
            elif ans in state_choices:
                chosen = state_choices[ans]
            if chosen:
                changed = update_state(
                    conn,
                    tgt["doc_id"],
                    chosen,
                    triggered_by_doc_id=card["doc_id"],
                    confirmed_by_human=True,
                )
                console.print(
                    f"  [green]✔ Güncellendi:[/green] {tgt['doc_id']} -> {chosen} (değişim={changed}, confirmed_by_human=1)"
                )
            else:
                console.print(f"  [dim]Atlandı: {tgt['doc_id']}[/dim]")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
