# -*- coding: utf-8 -*-
"""
Yazışma Tarihçesi İndeksleyici (Adım 3) — 1_ingest.py'nin kardeşi.

Ne yapar:
    data/3_yuklenici_talepleri/<proje>/ altındaki YAZIŞMA klasörlerini okur
    (1_yuklenici_yazilari / 2_idare_cevaplari / 3_tutanak_ve_toplantilar /
     4_hakedis_ozetleri — TAHKİM/ yalnızca --include-dir ile açılır),
    her belgeyi kanonik .md'ye çevirir (doc_sha256 kilidi), Kimlik Kartı çıkarır,
    SQLite (project_graph.db) + ChromaDB'ye doc_role="correspondence_history"
    ile izole yazar ve İlgi: referanslarını İKİ TURLU çözümler.

Kapsam kuralı (KRİTİK):
    1_ingest.py yalnızca 1_genel + 2_proje okur — bu betik ona hiç dokunmaz;
    2_agents_graph Hop 1/2 aramaları doc_role="normative_rule" ile normatif
    havuza kilitlidir. Böylece yüklenici iddiası asla kural gibi davranmaz.

Kullanım:
    python ingest_history.py --project ikitelli_atakoy_metro --use-llm
    python ingest_history.py --project ... --dry-run --limit 3
    python ingest_history.py --project ... --include-dir TAHKİM --limit 30
"""
import argparse
import hashlib
import re
import sys
import uuid
from pathlib import Path
from typing import List, Optional

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table

console = Console(legacy_windows=False)

from importlib.util import spec_from_file_location, module_from_spec

# 1_ingest.py kardeş modülü (modül adı rakamla başladığı için importlib ile yüklenir)
_INGEST_PATH = Path(__file__).resolve().parent / "1_ingest.py"
_spec = spec_from_file_location("ing1", str(_INGEST_PATH))
ing1 = module_from_spec(_spec)
_spec.loader.exec_module(ing1)

from utils.config import YUKLENICI_TALEPLERI_DIR
from utils.text_tr import ascii_fold
from utils.card_extractor import _RE_ILGI_TARIH, extract_identity_card, parse_tr_date
from utils.project_db import (
    connect,
    upsert_document,
    delete_document,
    add_link,
    add_tags,
    find_by_file_path,
    match_doc_no_in_project,
    get_unresolved_links,
    resolve_link,
    link_exists,
)
from utils.retriever import (
    get_correspondence_collection,
    get_embedding_model,
    detect_project_procurement_type,
)
from utils.document_parser import parse_any_document
from utils.standards import extract_standard_refs

# --- Kapsam kuralları ----------------------------------------------------------
# klasör adı -> (sender_role_hint, doc_type)
HISTORY_FOLDER_MAP = {
    "1_yuklenici_yazilari": ("contractor", "yuklenici_yazisi"),
    "2_idare_cevaplari": ("administration", "idare_cevabi"),
    "3_tutanak_ve_toplantilar": ("joint", "tutanak"),
    "4_hakedis_ozetleri": (None, "hakedis"),
}
SKIPPED_PATTERNS = {".cache", "ham_dosyalar", "hamdosyalar", "_arsiv", "arsiv"}
PARSABLE_EXT = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
TEXT_EXT = {".md", ".txt"}
KANONIK_SON_EK = "__kanonik.md"
REF_FUZZ_THRESHOLD = 92


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_ignored_history(fp: Path) -> bool:
    parts = [ascii_fold(p) for p in fp.parts]
    return any(any(p in part for p in SKIPPED_PATTERNS) for part in parts)


def folder_year(fp: Path, project_dir: Path) -> Optional[int]:
    """Klasör yolundaki yıl (1_yuklenici_yazilari/2023/...)."""
    try:
        rel = fp.resolve().relative_to(project_dir.resolve()).parts
    except ValueError:
        return None
    for part in rel[:-1]:
        m = re.fullmatch(r"(20\d{2})", part)
        if m:
            return int(m.group(1))
    return None


def collect_files(project_dir: Path, include_dirs: List[str]) -> List[Path]:
    """Yalnızca 4 yazışma klasörü (+ isteğe bağlı include-dir) taranır."""
    hedef_kokler = list(HISTORY_FOLDER_MAP.keys())
    for extra in include_dirs:
        if extra not in hedef_kokler:
            hedef_kokler.append(extra)
    dosyalar: List[Path] = []
    for kok in hedef_kokler:
        kok_dir = project_dir / kok
        if not kok_dir.exists():
            continue
        for fp in sorted(kok_dir.rglob("*")):
            if not fp.is_file() or is_ignored_history(fp):
                continue
            if fp.name.endswith(KANONIK_SON_EK):
                continue  # kanonik .md dosyası ikinci belge sanılmaz
            if fp.suffix.lower() in (TEXT_EXT | PARSABLE_EXT):
                dosyalar.append(fp)
    return dosyalar


def canonical_markdown(fp: Path) -> str:
    """
    Kanonik .md içeriği: .md/.txt ise dosyanın kendisi; PDF/docx/görsel ise
    document_parser çıktısı .cache_ocr/<stem>__kanonik.md olarak diske yazılır
    (doc_sha256 bu metnin UTF-8 byte'larından hesaplanır — offset kilidi).
    """
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


def _extract_ilgi_dates(ilgi_raw: Optional[str], default_year: Optional[int] = None) -> List[str]:
    """İlgi satırındaki tarih ifadelerini ISO tarih listesine çevirir (bulanık doc_no doğrulama için)."""
    if not ilgi_raw:
        return []
    dates: List[str] = []
    for mm in _RE_ILGI_TARIH.finditer(ilgi_raw):
        iso, _ = parse_tr_date(mm.group(0), default_year=default_year)
        if iso and iso not in dates:
            dates.append(iso)
    return dates


def _is_date_token(ref: str) -> bool:
    return bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", ref)
        or re.fullmatch(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", ref)
    )


def resolve_refs_two_pass(
    conn,
    project_id: str,
    doc_id: str,
    ilgi_refs: List[str],
    ilgi_raw: Optional[str] = None,
    ilgi_span: Optional[dict] = None,
    default_year: Optional[int] = None,
) -> int:
    """1. Tur: referansı doc_no havuzunda çöz (tam + rapidfuzz + OCR/tarih doğrulamalı)."""
    ilgi_dates = [r for r in ilgi_refs if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r)]
    for d_iso in _extract_ilgi_dates(ilgi_raw, default_year=default_year):
        if d_iso not in ilgi_dates:
            ilgi_dates.append(d_iso)

    cozulen = 0
    for ref in ilgi_refs:
        if _is_date_token(ref):
            continue  # Tarih tokenı tek başına doc_no kenarı olmaz (ilgi_dates olarak doğrular)
        hedef = match_doc_no_in_project(
            conn, project_id, ref, ilgi_dates=ilgi_dates, fuzz_threshold=REF_FUZZ_THRESHOLD
        )
        if hedef and hedef["doc_id"] != doc_id:
            if not link_exists(conn, doc_id, hedef["doc_id"], "ilgi_zinciri"):
                add_link(conn, doc_id, hedef["doc_id"], "ilgi_zinciri", resolved=True, evidence_span=ilgi_span)
            cozulen += 1
            continue
        if not link_exists(conn, doc_id, ref, "ilgi_zinciri"):
            add_link(conn, doc_id, ref, "ilgi_zinciri", resolved=False, evidence_span=ilgi_span)
    return cozulen


def backfill_unresolved(conn, project_id: str) -> int:
    """2. Tur: sonradan yüklenen eski yazılarla çözülemeyen kenarları bağlar."""
    bekleyen = get_unresolved_links(conn, project_id)
    baglanan = 0
    for kenar in bekleyen:
        ref = kenar["to_ref"]
        if _is_date_token(ref):
            continue
        src_row = conn.execute(
            "SELECT ilgi_raw, doc_date FROM documents WHERE doc_id=?",
            (kenar["from_doc_id"],),
        ).fetchone()
        def_year = int(src_row["doc_date"][:4]) if (src_row and src_row["doc_date"]) else None
        ilgi_dates = _extract_ilgi_dates(src_row["ilgi_raw"] if src_row else None, default_year=def_year)
        hedef = match_doc_no_in_project(
            conn, project_id, ref, ilgi_dates=ilgi_dates, fuzz_threshold=REF_FUZZ_THRESHOLD
        )
        if hedef and hedef["doc_id"] != kenar["from_doc_id"]:
            if link_exists(conn, kenar["from_doc_id"], hedef["doc_id"], "ilgi_zinciri"):
                conn.execute("DELETE FROM links WHERE link_id=?", (kenar["link_id"],))
                conn.commit()
            else:
                resolve_link(conn, kenar["link_id"], hedef["doc_id"])
            baglanan += 1
    return baglanan


def ingest_project_history(
    project_id: str,
    *,
    project_dir: Optional[Path] = None,
    history_root_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    chroma_dir: Optional[Path] = None,
    use_llm: bool = False,
    dry_run: bool = False,
    limit: int = 0,
    include_dirs: Optional[List[str]] = None,
) -> dict:
    """
    Bir projenin yazışma klasörlerini tarar; Kimlik Kartlarını SQLite (`project_graph.db`) ve
    fiziksel olarak ayrı yazışma ChromaDB'sine (`vector_db_yazismalar/proje_yazismalari`) yazar.
    Normatif veritabanına (`vector_db/insaat_mevzuat`) ASLA dokunmaz.
    """
    root_dir = Path(history_root_dir) if history_root_dir else YUKLENICI_TALEPLERI_DIR
    proj_dir = Path(project_dir) if project_dir else (root_dir / project_id)
    if not proj_dir.exists():
        raise FileNotFoundError(f"Proje klasörü yok: {proj_dir}")

    proc_type = detect_project_procurement_type(project_id)
    console.rule(f"[bold cyan]Yazışma Tarihçesi İndeksleme — {project_id}[/bold cyan]")
    console.print(
        f"İhale türü: [yellow]{proc_type}[/yellow] | LLM: {'AÇIK' if use_llm else 'kapalı'} | "
        f"{'DRY-RUN' if dry_run else 'GERÇEK'} | limit: {limit or 'tümü'} | "
        f"Vektör DB: [cyan]{chroma_dir or 'vector_db_yazismalar (proje_yazismalari)'}[/cyan]"
    )

    dosyalar = collect_files(proj_dir, list(include_dirs or []))
    if limit:
        dosyalar = dosyalar[:limit]
    if not dosyalar:
        console.print("[yellow]Taranacak yazışma bulunamadı.[/yellow]")
        return {"processed": 0, "skipped": 0, "chroma_added": 0, "resolved_pass1": 0, "resolved_pass2": 0}
    console.print(f"[green]✔[/green] {len(dosyalar)} belge sıraya alındı (kronolojik klasör sırası).")

    conn = connect(db_path) if db_path else connect()
    col = None
    emb = None

    islenen, atlanan, chroma_eklenen, ilk_cozulen, baglanan = 0, 0, 0, 0, 0
    try:
        for i, fp in enumerate(dosyalar, 1):
            try:
                rel = str(fp.resolve().relative_to(root_dir.resolve()))
            except ValueError:
                rel = str(fp)
            # Klasör -> rol/tip ipucu (dosya yolunun ilk yazışma klasöründen)
            role_hint, doc_type_hint = "contractor", "yuklenici_yazisi"
            for klasor, (rl, dt) in HISTORY_FOLDER_MAP.items():
                if f"/{klasor}/" in f"/{rel}/".replace("\\", "/").lower() or klasor in str(fp.parent).lower():
                    role_hint, doc_type_hint = rl, dt
                    break
            default_year = folder_year(fp, proj_dir)

            # --- Artımlı kontrol: kanonik md + sha aynıysa atla ---
            onceki = find_by_file_path(conn, project_id, rel)
            md = None
            if fp.suffix.lower() not in PARSABLE_EXT:
                md = canonical_markdown(fp)
            else:
                kanonik = fp.parent / ".cache_ocr" / (fp.stem + KANONIK_SON_EK)
                if kanonik.exists():
                    md = kanonik.read_text(encoding="utf-8", errors="ignore")

            if md is not None and onceki and onceki.get("doc_sha256") == sha256_text(md) and not dry_run:
                if col is None:
                    col = get_correspondence_collection(db_dir=chroma_dir)
                var = col.get(where={"sqlite_doc_id": onceki["doc_id"]}, limit=1)
                if var.get("ids"):
                    atlanan += 1
                    continue

            console.print(f"\n[cyan][{i}/{len(dosyalar)}][/cyan] {fp.name} [dim]({rel})[/dim]")

            # --- Kanonik .md + SHA ---
            if md is None:
                md = canonical_markdown(fp)
            sha = sha256_text(md)
            doc_id = f"{project_id}::{sha[:24]}"

            if onceki and onceki.get("doc_sha256") == sha and not dry_run:
                if col is None:
                    col = get_correspondence_collection(db_dir=chroma_dir)
                var = col.get(where={"sqlite_doc_id": doc_id}, limit=1)
                if var.get("ids"):
                    atlanan += 1
                    console.print("  [dim]✔ aynı içerik zaten işlenmiş — atlandı[/dim]")
                    continue

            # --- Kimlik Kartı ---
            sonuc = extract_identity_card(
                md, filename=fp.name, rel_path=rel, doc_sha256=sha, doc_id=doc_id,
                project_id=project_id, doc_type=doc_type_hint,
                sender_role_hint=role_hint, default_year=default_year, use_llm=use_llm,
            )
            card = sonuc["card"]
            for h in sonuc["llm_errors"]:
                console.print(f"  [yellow]! {h}[/yellow]")
            console.print(f"  Tarih: {card.get('doc_date')} | Sayı: {card.get('doc_no')} | "
                          f"Rol: {card.get('sender_role')} | Durum: {card.get('review_status')} | "
                          f"Güven: {card.get('extraction_confidence')} | İlgi ref: {sonuc['ilgi_refs']}")
            if dry_run:
                islenen += 1
                continue

            if col is None:
                col = get_correspondence_collection(db_dir=chroma_dir)

            # Dosya güncellendiyse eski doc_id kalıntılarını temizle
            if onceki and onceki["doc_id"] != doc_id:
                try:
                    col.delete(where={"sqlite_doc_id": onceki["doc_id"]})
                except Exception:
                    pass
                delete_document(conn, onceki["doc_id"])

            # --- SQLite: kart + etiketler + köprüler ---
            upsert_document(conn, card)
            etiketler = []
            for e in (card.get("konu_etiketleri") or [])[:8]:
                etiketler.append({"tag_type": "konu", "tag_value": str(e)})
            std_refs = extract_standard_refs(md)[:10]
            for r in std_refs:
                etiketler.append({"tag_type": "standart", "tag_value": r["canonical"]})
                if not link_exists(conn, doc_id, r["canonical"], "standart_ref"):
                    add_link(
                        conn, doc_id, r["canonical"], "standart_ref", resolved=True,
                        evidence_span={"char_start": r["span"][0], "char_end": r["span"][1], "exact_quote": r["raw"]},
                    )
            for p in re.findall(r"Poz\s+\d+(?:[.\-]\d+)*", md, re.IGNORECASE)[:15]:
                poz_val = re.sub(r"(?i)^poz\s+", "", p).strip()
                if poz_val:
                    etiketler.append({"tag_type": "poz_no", "tag_value": poz_val})
            add_tags(conn, doc_id, etiketler)

            # --- 1. Tur İlgi: referansı çözümle ---
            ilgi_span = next((s for s in sonuc["spans"] if s.get("field") == "ilgi_raw"), None)
            ilk_cozulen += resolve_refs_two_pass(
                conn,
                project_id,
                doc_id,
                sonuc["ilgi_refs"],
                ilgi_raw=card.get("ilgi_raw"),
                ilgi_span=ilgi_span,
                default_year=default_year,
            )

            # --- Yazışma ChromaDB (`vector_db_yazismalar/proje_yazismalari`) — FİZİKSEL İZOLASYON ---
            if emb is None:
                emb = get_embedding_model()
            chunks = []
            parcalar = ing1.split_markdown_into_legal_chunks(
                markdown_text=md, filename=fp.name, domain="idari",
                scope="project", project_id=project_id,
                project_name=project_id.replace("_", " ").title(),
                rel_path=rel, procurement_type=proc_type, folder_subsystem=None,
            )
            for idx, ch in enumerate(parcalar):
                m = ch["metadata"]
                m["doc_role"] = "correspondence_history"     # ASLA normative_rule değil!
                m["sender_role"] = card.get("sender_role") or ""
                m["evidence_weight"] = card.get("evidence_weight") or ""
                m["doc_date"] = card.get("doc_date") or ""
                m["doc_no"] = card.get("doc_no") or ""
                m["sqlite_doc_id"] = doc_id
                m["doc_type"] = doc_type_hint
                ch["id"] = f"corr_{project_id}_{sha[:12]}_{uuid.uuid4().hex[:8]}"
                chunks.append(ch)

            if chunks:
                try:
                    col.delete(where={"sqlite_doc_id": doc_id})
                except Exception:
                    pass
                docs_content = [c["content"] for c in chunks]
                metas = [c["metadata"] for c in chunks]
                ids = [c["id"] for c in chunks]
                if hasattr(emb, "encode"):
                    res = emb.encode(docs_content, return_dense=True)
                    vectors = res["dense_vecs"].tolist() if isinstance(res, dict) and "dense_vecs" in res else (
                        res.tolist() if hasattr(res, "tolist") else list(res))
                else:
                    vectors = [emb.encode_queries([t])[0].tolist() for t in docs_content]
                col.add(ids=ids, documents=docs_content, metadatas=metas, embeddings=vectors)
                chroma_eklenen += len(chunks)
                console.print(f"  [green]✔ Yazışma ChromaDB (proje_yazismalari):[/green] {len(chunks)} parça")

            islenen += 1

        if dry_run:
            console.print(f"\n[bold yellow]DRY-RUN tamamlandı:[/bold yellow] {islenen} belge tarandı (veritabanına yazılmadı).")
            return {"processed": islenen, "skipped": atlanan, "chroma_added": 0, "resolved_pass1": 0, "resolved_pass2": 0}

        # --- 2. Tur: çözülemeyen İlgi kenarlarını yeni belgelerle bağla ---
        baglanan = backfill_unresolved(conn, project_id)

        console.print(
            f"\n[bold green]✔ Bitti:[/bold green] {islenen} belge işlendi, {atlanan} atlandı, "
            f"{chroma_eklenen} Yazışma ChromaDB parçası, {ilk_cozulen} 1. tur + {baglanan} 2. tur çözümlenen İlgi kenarı."
        )
        tbl = Table(title="Durum Dağılımı")
        tbl.add_column("Durum"); tbl.add_column("Adet")
        for row in conn.execute(
            "SELECT state, review_status, COUNT(*) c FROM documents WHERE project_id=? GROUP BY state, review_status",
            (project_id,),
        ):
            tbl.add_row(f"{row['state']} / {row['review_status']}", str(row["c"]))
        console.print(tbl)
        return {
            "processed": islenen,
            "skipped": atlanan,
            "chroma_added": chroma_eklenen,
            "resolved_pass1": ilk_cozulen,
            "resolved_pass2": baglanan,
        }
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Yazışma tarihçesi indeksleyici (Adım 3 — Fiziksel Ayrı Yazışma DB)")
    ap.add_argument("--project", required=True, help="proje_id (ör. ikitelli_atakoy_metro)")
    ap.add_argument("--use-llm", action="store_true", help="instructor + langextract zenginleştirmesi")
    ap.add_argument("--dry-run", action="store_true", help="yazma yapmadan raporlar (DB/Chroma/embedding açmaz)")
    ap.add_argument("--limit", type=int, default=0, help="en fazla N belge işle (0=tümü)")
    ap.add_argument("--include-dir", action="append", default=[],
                    help="ek taranacak klasör (ör. TAHKİM — pilot için kontrollü)")
    ap.add_argument("--db-path", default=None, help="Özel SQLite dosya yolu (varsayılan: data/project_graph.db)")
    ap.add_argument("--chroma-dir", default=None, help="Özel Yazışma ChromaDB klasörü (varsayılan: vector_db_yazismalar)")
    args = ap.parse_args()

    try:
        ingest_project_history(
            args.project,
            db_path=Path(args.db_path) if args.db_path else None,
            chroma_dir=Path(args.chroma_dir) if args.chroma_dir else None,
            use_llm=args.use_llm,
            dry_run=args.dry_run,
            limit=args.limit,
            include_dirs=args.include_dir,
        )
    except FileNotFoundError as exc:
        console.print(f"[bold red]![/bold red] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
