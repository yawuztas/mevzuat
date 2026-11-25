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
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def collect_files(
    project_dir: Path,
    include_dirs: List[str],
    source_dir: Optional[Path] = None,
) -> List[Path]:
    """
    Yazışma dosyalarını toplar:
    - `source_dir` verilmişse: o harici veya karma klasörün tamamını özyinelemeli tarar.
    - Verilmemişse: `project_dir` altındaki tüm desteklenen belgeleri tarar
      (4 standart yazışma klasörü + proje içine bırakılan karma konu klasörleri dahil;
      `.cache_ocr`, `_arsiv`, `ham_dosyalar` ve `--include-dir` ile açılmayan `tahkim` hariç).
    """
    include_folded = {ascii_fold(x) for x in (include_dirs or [])}

    def _is_skipped_for_scan(fp: Path, base_root: Path) -> bool:
        try:
            rel_parts = [ascii_fold(p) for p in fp.resolve().relative_to(base_root.resolve()).parent.parts]
        except ValueError:
            rel_parts = [ascii_fold(p) for p in fp.parent.parts]
        for part in rel_parts:
            if any(pat in part for pat in SKIPPED_PATTERNS):
                return True
            if "tahkim" in part and not any("tahkim" in inc for inc in include_folded):
                return True
        return False

    scan_root = Path(source_dir) if source_dir else Path(project_dir)
    if not scan_root.exists():
        return []

    dosyalar: List[Path] = []
    seen: set = set()
    for fp in sorted(scan_root.rglob("*")):
        if not fp.is_file() or _is_skipped_for_scan(fp, scan_root):
            continue
        if fp.name.endswith(KANONIK_SON_EK):
            continue
        if fp.suffix.lower() in (TEXT_EXT | PARSABLE_EXT):
            resolved_str = str(fp.resolve())
            if resolved_str not in seen:
                seen.add(resolved_str)
                dosyalar.append(fp)

    # Açıkça --include-dir ile verilen ek klasörler varsa (ör. TAHKİM) ekle
    if not source_dir and include_dirs:
        for extra in include_dirs:
            extra_dir = Path(project_dir) / extra
            if not extra_dir.exists():
                continue
            for fp in sorted(extra_dir.rglob("*")):
                if not fp.is_file() or is_ignored_history(fp) or fp.name.endswith(KANONIK_SON_EK):
                    continue
                if fp.suffix.lower() in (TEXT_EXT | PARSABLE_EXT):
                    resolved_str = str(fp.resolve())
                    if resolved_str not in seen:
                        seen.add(resolved_str)
                        dosyalar.append(fp)
    return dosyalar


def _target_organized_subfolder(sender_role: Optional[str], doc_type: Optional[str]) -> str:
    """Taraf ve belge türüne göre düzenli klasör adını belirler (--organize modu için)."""
    if doc_type == "hakedis":
        return "4_hakedis_ozetleri"
    if sender_role == "joint" or doc_type == "tutanak":
        return "3_tutanak_ve_toplantilar"
    if sender_role in ("administration", "consultant") or doc_type in ("idare_cevabi", "musavir_yazisi"):
        return "2_idare_cevaplari"
    return "1_yuklenici_yazilari"


def _copy_to_organized_folder(
    src_fp: Path,
    project_dir: Path,
    sender_role: Optional[str],
    doc_type: Optional[str],
    doc_date: Optional[str],
) -> Path:
    """
    Orijinal dosyayı SİLMEDEN proje klasörü altında `<taraf_klasoru>/<yil>/` altına kopyalar.
    Aynı dosya zaten hedef konumdaysa doğrudan onu döndürür.
    """
    bucket = _target_organized_subfolder(sender_role, doc_type)
    year_dir = doc_date[:4] if (doc_date and re.fullmatch(r"20\d{2}", doc_date[:4])) else "tarihsiz"
    dest_dir = project_dir / bucket / year_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_fp = dest_dir / src_fp.name
    try:
        if src_fp.resolve() == dest_fp.resolve():
            return dest_fp
    except Exception:
        pass
    if not dest_fp.exists():
        shutil.copy2(src_fp, dest_fp)
        # OCR önbelleği varsa onu da kopyala ki ikinci kez OCR edilmesin
        src_kan = src_fp.parent / ".cache_ocr" / (src_fp.stem + KANONIK_SON_EK)
        if src_kan.exists():
            dst_cache = dest_dir / ".cache_ocr"
            dst_cache.mkdir(parents=True, exist_ok=True)
            dst_kan = dst_cache / src_kan.name
            if not dst_kan.exists():
                shutil.copy2(src_kan, dst_kan)
    return dest_fp


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


def _edge_type_for_pair(src_role: Optional[str], tgt_role: Optional[str]) -> str:
    """İdare/Müşavir yazısı bir Yüklenici yazısına İlgi veriyorsa `cevaplar`, aksi halde `ilgi_zinciri`."""
    if src_role in ("administration", "consultant") and tgt_role == "contractor":
        return "cevaplar"
    return "ilgi_zinciri"


def resolve_refs_two_pass(
    conn,
    project_id: str,
    doc_id: str,
    ilgi_refs: List[str],
    ilgi_raw: Optional[str] = None,
    ilgi_span: Optional[dict] = None,
    default_year: Optional[int] = None,
    src_sender_role: Optional[str] = None,
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
            etype = _edge_type_for_pair(src_sender_role, hedef.get("sender_role"))
            if not link_exists(conn, doc_id, hedef["doc_id"], etype):
                add_link(conn, doc_id, hedef["doc_id"], etype, resolved=True, evidence_span=ilgi_span)
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
            "SELECT ilgi_raw, doc_date, sender_role FROM documents WHERE doc_id=?",
            (kenar["from_doc_id"],),
        ).fetchone()
        def_year = int(src_row["doc_date"][:4]) if (src_row and src_row["doc_date"]) else None
        src_role = src_row["sender_role"] if src_row else None
        ilgi_dates = _extract_ilgi_dates(src_row["ilgi_raw"] if src_row else None, default_year=def_year)
        hedef = match_doc_no_in_project(
            conn, project_id, ref, ilgi_dates=ilgi_dates, fuzz_threshold=REF_FUZZ_THRESHOLD
        )
        if hedef and hedef["doc_id"] != kenar["from_doc_id"]:
            etype = _edge_type_for_pair(src_role, hedef.get("sender_role"))
            if link_exists(conn, kenar["from_doc_id"], hedef["doc_id"], etype):
                conn.execute("DELETE FROM links WHERE link_id=?", (kenar["link_id"],))
                conn.commit()
            else:
                conn.execute(
                    "UPDATE links SET to_ref=?, link_type=?, resolved=1 WHERE link_id=?",
                    (hedef["doc_id"], etype, kenar["link_id"]),
                )
                conn.commit()
            baglanan += 1
    return baglanan


def _detect_folder_role_hint(fp: Path, rel: str) -> Tuple[Optional[str], str]:
    """
    Dosya 4 yapısal yazışma klasöründen birindeyse o klasörün rol/tür ipucunu döndürür.
    Karma bir klasördeyse `(None, 'auto')` döndürerek çoklu-sinyal antet/evrak-no sınıflandırıcısını devreye alır.
    """
    rel_norm = f"/{rel}/".replace("\\", "/").lower()
    parent_norm = str(fp.parent).replace("\\", "/").lower()
    for klasor, (rl, dt) in HISTORY_FOLDER_MAP.items():
        if f"/{klasor}/" in rel_norm or f"/{klasor}" in parent_norm:
            return rl, dt
    return None, "auto"


def ingest_project_history(
    project_id: str,
    *,
    project_dir: Optional[Path] = None,
    source_dir: Optional[Path] = None,
    history_root_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    chroma_dir: Optional[Path] = None,
    use_llm: bool = False,
    dry_run: bool = False,
    organize: bool = False,
    limit: int = 0,
    include_dirs: Optional[List[str]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """
    Bir projenin yazışma klasörlerini (yapısal 4 klasör VEYA karma tek klasör / `--source-dir`) tarar;
    tarafı otomatik sınıflandırır, Kimlik Kartlarını SQLite (`project_graph.db`) ve
    fiziksel olarak ayrı yazışma ChromaDB'sine (`vector_db_yazismalar/proje_yazismalari`) yazar.
    Normatif veritabanına (`vector_db/insaat_mevzuat`) ASLA dokunmaz.
    """
    root_dir = Path(history_root_dir) if history_root_dir else YUKLENICI_TALEPLERI_DIR
    proj_dir = Path(project_dir) if project_dir else (root_dir / project_id)
    src_dir = Path(source_dir) if source_dir else None

    if src_dir is not None:
        if not src_dir.exists():
            raise FileNotFoundError(f"Kaynak klasör yok: {src_dir}")
        proj_dir.mkdir(parents=True, exist_ok=True)
    elif not proj_dir.exists():
        raise FileNotFoundError(f"Proje klasörü yok: {proj_dir}")

    proc_type = detect_project_procurement_type(project_id)
    console.rule(f"[bold cyan]Yazışma Tarihçesi İndeksleme — {project_id}[/bold cyan]")
    console.print(
        f"İhale türü: [yellow]{proc_type}[/yellow] | Kaynak: [cyan]{src_dir or proj_dir}[/cyan] | "
        f"Düzenle(--organize): {'AÇIK' if organize else 'kapalı'} | LLM: {'AÇIK' if use_llm else 'kapalı'} | "
        f"{'DRY-RUN' if dry_run else 'GERÇEK'} | limit: {limit or 'tümü'}"
    )

    dosyalar = collect_files(proj_dir, list(include_dirs or []), source_dir=src_dir)
    if limit:
        dosyalar = dosyalar[:limit]
    if not dosyalar:
        console.print("[yellow]Taranacak yazışma bulunamadı.[/yellow]")
        return {
            "processed": 0, "skipped": 0, "failed": 0, "chroma_added": 0,
            "resolved_pass1": 0, "resolved_pass2": 0, "role_counts": {}, "errors": [],
        }
    console.print(f"[green]✔[/green] {len(dosyalar)} belge sıraya alındı.")

    conn = connect(db_path) if db_path else connect()
    col = None
    emb = None

    islenen, atlanan, hatali, chroma_eklenen, ilk_cozulen, baglanan = 0, 0, 0, 0, 0, 0
    role_counts: Dict[str, int] = {}
    errors: List[Dict[str, str]] = []
    total_files = len(dosyalar)

    try:
        for i, fp in enumerate(dosyalar, 1):
            if progress_cb:
                try:
                    progress_cb(i, total_files, fp.name)
                except Exception:
                    pass
            try:
                try:
                    rel = str(fp.resolve().relative_to(root_dir.resolve()))
                except ValueError:
                    rel = str(fp.resolve())

                role_hint, doc_type_hint = _detect_folder_role_hint(fp, rel)
                default_year = folder_year(fp, src_dir or proj_dir)

                # --- Artımlı kontrol: kanonik md + sha aynıysa atla ---
                onceki = find_by_file_path(conn, project_id, rel)
                md = None
                if fp.suffix.lower() not in PARSABLE_EXT:
                    md = canonical_markdown(fp)
                else:
                    kanonik = fp.parent / ".cache_ocr" / (fp.stem + KANONIK_SON_EK)
                    if kanonik.exists():
                        md = kanonik.read_text(encoding="utf-8", errors="ignore")

                if md is not None and onceki and onceki.get("doc_sha256") == sha256_text(md) and not dry_run and not organize:
                    if col is None:
                        col = get_correspondence_collection(db_dir=chroma_dir)
                    var = col.get(where={"sqlite_doc_id": onceki["doc_id"]}, limit=1)
                    if var.get("ids"):
                        atlanan += 1
                        continue

                console.print(f"\n[cyan][{i}/{total_files}][/cyan] {fp.name} [dim]({rel})[/dim]")

                # --- Kanonik .md + SHA ---
                if md is None:
                    md = canonical_markdown(fp)
                sha = sha256_text(md)
                doc_id = f"{project_id}::{sha[:24]}"

                if onceki and onceki.get("doc_sha256") == sha and not dry_run and not organize:
                    if col is None:
                        col = get_correspondence_collection(db_dir=chroma_dir)
                    var = col.get(where={"sqlite_doc_id": doc_id}, limit=1)
                    if var.get("ids"):
                        atlanan += 1
                        console.print("  [dim]✔ aynı içerik zaten işlenmiş — atlandı[/dim]")
                        continue

                # --- Kimlik Kartı (karma klasörde çoklu-sinyal otomatik taraf tespiti!) ---
                sonuc = extract_identity_card(
                    md, filename=fp.name, rel_path=rel, doc_sha256=sha, doc_id=doc_id,
                    project_id=project_id, doc_type=doc_type_hint,
                    sender_role_hint=role_hint, default_year=default_year, use_llm=use_llm,
                )
                card = sonuc["card"]

                # İsteğe bağlı: orijinali silmeden proje altında taraf/yıl klasörüne kopyala
                if organize and not dry_run:
                    org_fp = _copy_to_organized_folder(
                        fp, proj_dir, card.get("sender_role"), card.get("doc_type"), card.get("doc_date")
                    )
                    try:
                        rel = str(org_fp.resolve().relative_to(root_dir.resolve()))
                    except ValueError:
                        rel = str(org_fp.resolve())
                    card["file_path"] = rel

                r_lbl = card.get("sender_role") or "belirsiz"
                role_counts[r_lbl] = role_counts.get(r_lbl, 0) + 1

                for h in sonuc["llm_errors"]:
                    console.print(f"  [yellow]! {h}[/yellow]")
                console.print(
                    f"  Tarih: {card.get('doc_date')} | Sayı: {card.get('doc_no')} | "
                    f"Rol: {r_lbl} ({card.get('doc_type')}) | Durum: {card.get('review_status')} | "
                    f"Güven: {card.get('extraction_confidence')} | İlgi ref: {sonuc['ilgi_refs']}"
                )
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

                # --- SQLite: kart + etiketler (disiplin + standart + poz + konu) + köprüler ---
                upsert_document(conn, card)
                etiketler = []
                for e in (card.get("konu_etiketleri") or [])[:8]:
                    etiketler.append({"tag_type": "konu", "tag_value": str(e)})
                # Disiplin (subsystem) otomatik etiketi — 6.000 evrakta anlık filtre için
                try:
                    det_sub = ing1.classify_subsystem(
                        md[:6000],
                        filename=fp.name,
                        domain="karma",
                        title=card.get("subject") or "",
                    )
                    if det_sub:
                        etiketler.append({"tag_type": "alt_sistem", "tag_value": det_sub})
                except Exception:
                    det_sub = None

                std_refs = extract_standard_refs(md)[:12]
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
                if etiketler:
                    add_tags(conn, doc_id, etiketler)

                # --- 1. Tur İlgi: referansı çözümle (İdare/Müşavir -> Yüklenici ise 'cevaplar') ---
                ilgi_span = next((s for s in sonuc["spans"] if s.get("field") == "ilgi_raw"), None)
                ilk_cozulen += resolve_refs_two_pass(
                    conn,
                    project_id,
                    doc_id,
                    sonuc["ilgi_refs"],
                    ilgi_raw=card.get("ilgi_raw"),
                    ilgi_span=ilgi_span,
                    default_year=default_year,
                    src_sender_role=card.get("sender_role"),
                )

                # --- Yazışma ChromaDB (`vector_db_yazismalar/proje_yazismalari`) — FİZİKSEL İZOLASYON ---
                if emb is None:
                    emb = get_embedding_model()
                chunks = []
                parcalar = ing1.split_markdown_into_legal_chunks(
                    markdown_text=md, filename=fp.name, domain="idari",
                    scope="project", project_id=project_id,
                    project_name=project_id.replace("_", " ").title(),
                    rel_path=rel, procurement_type=proc_type, folder_subsystem=det_sub,
                )
                for ch in parcalar:
                    m = ch["metadata"]
                    m["doc_role"] = "correspondence_history"     # ASLA normative_rule değil!
                    m["sender_role"] = card.get("sender_role") or ""
                    m["evidence_weight"] = card.get("evidence_weight") or ""
                    m["doc_date"] = card.get("doc_date") or ""
                    m["doc_no"] = card.get("doc_no") or ""
                    m["sqlite_doc_id"] = doc_id
                    m["doc_type"] = card.get("doc_type") or doc_type_hint
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
            except Exception as exc:
                hatali += 1
                errors.append({"file": str(fp), "error": str(exc)})
                console.print(f"  [bold red]✖ Hata ({fp.name}):[/bold red] {exc}")
                continue

        if dry_run:
            console.print(
                f"\n[bold yellow]DRY-RUN tamamlandı:[/bold yellow] {islenen} belge tarandı, {hatali} hata "
                f"(veritabanına yazılmadı). Taraf dağılımı: {role_counts}"
            )
            return {
                "processed": islenen, "skipped": atlanan, "failed": hatali, "chroma_added": 0,
                "resolved_pass1": 0, "resolved_pass2": 0, "role_counts": role_counts, "errors": errors,
            }

        # --- 2. Tur: çözülemeyen İlgi kenarlarını yeni belgelerle bağla ---
        baglanan = backfill_unresolved(conn, project_id)

        console.print(
            f"\n[bold green]✔ Bitti:[/bold green] {islenen} belge işlendi, {atlanan} atlandı, {hatali} hata, "
            f"{chroma_eklenen} Yazışma ChromaDB parçası, {ilk_cozulen} 1. tur + {baglanan} 2. tur çözümlenen İlgi kenarı."
        )
        console.print(f"[dim]Taraf dağılımı:[/dim] {role_counts}")
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
            "failed": hatali,
            "chroma_added": chroma_eklenen,
            "resolved_pass1": ilk_cozulen,
            "resolved_pass2": baglanan,
            "role_counts": role_counts,
            "errors": errors,
        }
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Akıllı Karma Klasör Yazışma İndeksleyici (Fiziksel Ayrı Yazışma DB)")
    ap.add_argument("--project", required=True, help="proje_id (ör. ikitelli_atakoy_metro)")
    ap.add_argument("--source-dir", default=None, help="Karışık yazışmaların bulunduğu harici/özel klasör yolu")
    ap.add_argument("--organize", action="store_true",
                    help="Orijinal dosyaları silmeden taraf ve yıl klasörlerine (1_yuklenici_yazilari/2023 vb.) kopyalayarak düzenle")
    ap.add_argument("--use-llm", action="store_true", help="instructor + langextract zenginleştirmesi")
    ap.add_argument("--dry-run", action="store_true", help="yazma yapmadan taraf tespiti ve kartları raporlar")
    ap.add_argument("--limit", type=int, default=0, help="en fazla N belge işle (0=tümü)")
    ap.add_argument("--include-dir", action="append", default=[],
                    help="ek taranacak klasör (ör. TAHKİM — pilot için kontrollü)")
    ap.add_argument("--db-path", default=None, help="Özel SQLite dosya yolu (varsayılan: data/project_graph.db)")
    ap.add_argument("--chroma-dir", default=None, help="Özel Yazışma ChromaDB klasörü (varsayılan: vector_db_yazismalar)")
    args = ap.parse_args()

    try:
        ingest_project_history(
            args.project,
            source_dir=Path(args.source_dir) if args.source_dir else None,
            db_path=Path(args.db_path) if args.db_path else None,
            chroma_dir=Path(args.chroma_dir) if args.chroma_dir else None,
            use_llm=args.use_llm,
            dry_run=args.dry_run,
            organize=args.organize,
            limit=args.limit,
            include_dirs=args.include_dir,
        )
    except FileNotFoundError as exc:
        console.print(f"[bold red]![/bold red] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
