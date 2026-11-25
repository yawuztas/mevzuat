# -*- coding: utf-8 -*-
"""
10 Saniyelik İnsan Onay CLI'ı (Adım 3).

pending_review'daki Kimlik Kartlarını sırayla gösterir:
    [O]nayla            : alanlar doğruysa human_approved yapar
    [D]üzenle & Onayla  : doc_date (DMY), doc_no, sender_role düzelt + onayla +
                          bu belgeye işaret eden çözülmemiş İlgi kenarlarını yeniden bağla
    [A]tla              : sonraya bırak
    [Ç]ık               : bitir
"""
import argparse
import sys
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from utils.project_db import connect, pending_review, approve, match_doc_no_in_project, resolve_link, link_exists
from utils.card_extractor import _RE_ILGI_TARIH, _evidence_weight_for, parse_tr_date

ROLE_LABELED = {"1": "contractor", "2": "administration", "3": "consultant", "4": "joint"}


def relink_after_fix(conn, project_id: str, target_doc_id: str, doc_no: str) -> int:
    """Bu belgeye işaret eden çözülmemiş kenarları (tam + fuzzy + OCR/tarih) yeniden bağlar."""
    rows = conn.execute(
        "SELECT l.link_id, l.from_doc_id, l.to_ref FROM links l "
        "JOIN documents d ON d.doc_id = l.from_doc_id "
        "WHERE l.resolved=0 AND l.link_type='ilgi_zinciri' AND d.project_id=?",
        (project_id,),
    ).fetchall()
    linked = 0
    for r in rows:
        ref = r["to_ref"]
        src_row = conn.execute(
            "SELECT ilgi_raw, doc_date FROM documents WHERE doc_id=?",
            (r["from_doc_id"],),
        ).fetchone()
        def_year = int(src_row["doc_date"][:4]) if (src_row and src_row["doc_date"]) else None
        ilgi_dates = []
        if src_row and src_row["ilgi_raw"]:
            for mm in _RE_ILGI_TARIH.finditer(src_row["ilgi_raw"]):
                iso, _ = parse_tr_date(mm.group(0), default_year=def_year)
                if iso:
                    ilgi_dates.append(iso)
        hedef = match_doc_no_in_project(conn, project_id, ref, ilgi_dates=ilgi_dates, fuzz_threshold=92)
        if hedef and hedef["doc_id"] == target_doc_id and hedef["doc_id"] != r["from_doc_id"]:
            if link_exists(conn, r["from_doc_id"], target_doc_id, "ilgi_zinciri"):
                conn.execute("DELETE FROM links WHERE link_id=?", (r["link_id"],))
                conn.commit()
            else:
                resolve_link(conn, r["link_id"], target_doc_id)
            linked += 1
    return linked


def _sync_chroma_card(kart: dict, correspondence_db_dir: Optional[Path] = None) -> None:
    """Düzenlenen Kimlik Kartı alanlarını ayrı yazışma ChromaDB'sine (`vector_db_yazismalar`) yansıtır."""
    try:
        from utils.retriever import get_correspondence_collection
        col = get_correspondence_collection(db_dir=correspondence_db_dir)
        if col.count() == 0:
            return
        res = col.get(where={"sqlite_doc_id": kart["doc_id"]}, include=["metadatas"])
        ids = res.get("ids") or []
        metas = res.get("metadatas") or []
        if ids:
            updated_metas = []
            for m in metas:
                nm = dict(m)
                nm["doc_date"] = kart.get("doc_date") or ""
                nm["doc_no"] = kart.get("doc_no") or ""
                nm["sender_role"] = kart.get("sender_role") or ""
                nm["evidence_weight"] = kart.get("evidence_weight") or ""
                updated_metas.append(nm)
            col.update(ids=ids, metadatas=updated_metas)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="10 Saniyelik İnsan Onay CLI'ı (Adım 3)")
    ap.add_argument("--project", default=None, help="Sadece belirli projeyi listele (opsiyonel)")
    args = ap.parse_args()

    conn = connect()
    skipped_ids = set()
    try:
        while True:
            kuyruk = [k for k in pending_review(conn, project_id=args.project) if k["doc_id"] not in skipped_ids]
            if not kuyruk:
                if skipped_ids:
                    print(f"Kalan kart yok ({len(skipped_ids)} kart atlandı).")
                else:
                    print("Kuyruk boş ✔ — onay bekleyen kart yok.")
                return
            kart = kuyruk[0]
            print("\n" + "=" * 68)
            print(f"doc_id  : {kart['doc_id']}")
            print(f"proje   : {kart['project_id']}  | tip: {kart['doc_type']}")
            print(f"dosya   : {kart['file_path']}")
            print(f"tarih   : {kart['doc_date']}   | sayı : {kart['doc_no']}")
            print(f"rol     : {kart['sender_role']}  | güven: {kart['extraction_confidence']}")
            print(f"konu    : {str(kart['subject'])[:90]}")
            print(f"özet    : {str(kart['summary'])[:90]}")
            secim = input("[O]nayla / [D]üzenle&Onayla / [A]tla / [Ç]ık > ").strip().lower()

            if secim in ("o", "o*", "onayla"):
                approve(conn, kart["doc_id"])
                print("✔ human_approved")
            elif secim in ("d", "d*"):
                yeni_tarih = input(f"  doc_date [{kart['doc_date']}]: ").strip()
                yeni_no = input(f"  doc_no   [{kart['doc_no']}]: ").strip()
                yeni_rol = input(f"  rol (1=Yüklenici 2=İdare 3=Müşavir 4=Ortak) [{kart['sender_role']}]: ").strip()
                if yeni_tarih:
                    iso, _ = parse_tr_date(yeni_tarih)
                    if iso:
                        kart["doc_date"] = iso
                    else:
                        print("  ! tarih çözülemedi, eski değer korundu")
                if yeni_no:
                    kart["doc_no"] = yeni_no
                if yeni_rol in ROLE_LABELED:
                    kart["sender_role"] = ROLE_LABELED[yeni_rol]
                kart["evidence_weight"] = _evidence_weight_for(kart.get("sender_role"), kart.get("doc_type") or "")
                conn.execute(
                    "UPDATE documents SET doc_date=?, doc_no=?, sender_role=?, evidence_weight=? WHERE doc_id=?",
                    (kart["doc_date"], kart["doc_no"], kart["sender_role"], kart["evidence_weight"], kart["doc_id"]),
                )
                conn.commit()
                approve(conn, kart["doc_id"])
                _sync_chroma_card(kart)
                linked = relink_after_fix(conn, kart["project_id"], kart["doc_id"], kart["doc_no"]) if kart["doc_no"] else 0
                print(f"✔ düzenlendi + human_approved + {linked} İlgi bağlantısı yeniden çözüldü")
            elif secim in ("a", "a*", "atla"):
                skipped_ids.add(kart["doc_id"])
            elif secim in ("c", "ç", "c*", "çık", "q"):
                return
    finally:
        conn.close()


if __name__ == "__main__":
    main()
