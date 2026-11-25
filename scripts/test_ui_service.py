# -*- coding: utf-8 -*-
"""
InsaatAudit NiceGUI Servis Katmanı Testleri (Fiziksel Dual-DB + İzole SQLite + Word Roundtrip)
"""

from __future__ import annotations

import gc
import io
import sys
import tempfile
from pathlib import Path

import docx

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.config import RAPORLAR_DIR, YUKLENICI_TALEPLERI_DIR  # noqa: E402
from utils.document_parser import parse_any_document  # noqa: E402
from utils.project_db import add_link, connect, upsert_document  # noqa: E402
from utils.retriever import reset_correspondence_cache  # noqa: E402
from utils.ui_service import (  # noqa: E402
    build_docx_bytes_from_markdown,
    get_correspondence_graph,
    get_document_chunks,
    get_legislation_sync_status,
    get_memory_inventory_and_tree,
    list_known_projects,
    save_uploaded_petition,
    update_card_and_approve,
)


def test_memory_inventory_tree_and_chunks() -> None:
    inv = get_memory_inventory_and_tree()
    assert inv["normative_vectors"] > 0, "Normatif ChromaDB boş olmamalı"
    assert inv["layer_counts"]["global"] > 0
    assert inv["layer_counts"]["project_normative"] > 0
    assert inv["total_vectors"] == inv["normative_vectors"] + inv["correspondence_vectors"]
    tree_children = inv["tree"]["children"]
    assert len(tree_children) == 3

    chunks = get_document_chunks("global", "yapim_isleri_genel_sartnamesi_yigs.md", limit=5, doc_role="normative_rule")
    assert len(chunks) >= 1, "YİGŞ parçaları okunabilmeli"
    print(
        f"[OK] Bilgi Ağacı (Dual-DB): normatif={inv['normative_vectors']}, "
        f"yazışma={inv['correspondence_vectors']}, YİGŞ örnek parça={len(chunks)}"
    )


def test_correspondence_graph_relink_and_human_approval_isolated() -> None:
    tmp_obj = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    tmp = Path(tmp_obj.name)
    tmp_chroma = tmp / "corr_db"
    try:
        db_p = tmp / "test_ui_graph.db"
        conn = connect(db_p)
        # Boş graf kontrolü
        empty_g = get_correspondence_graph(db_path=db_p, project_id="test_proj")
        assert empty_g["elements"] == [] and empty_g["documents"] == []

        # 2 belge: doc2, henüz doc_no'su bozuk olan doc1'e çözülmemiş İlgi taşıyor
        upsert_document(conn, {
            "doc_id": "p::doc1",
            "project_id": "test_proj",
            "doc_type": "yuklenici_yazisi",
            "sender_role": "contractor",
            "doc_date": "2026-01-15",
            "doc_no": "YK-BOZUK",
            "subject": "Test Süre Talebi",
            "state": "Acik",
            "review_status": "pending_review",
            "summary": "Özet metni",
        })
        upsert_document(conn, {
            "doc_id": "p::doc2",
            "project_id": "test_proj",
            "doc_type": "idare_cevabi",
            "sender_role": "administration",
            "doc_date": "2026-01-25",
            "doc_no": "IDR-500",
            "subject": "Cevap",
            "ilgi_raw": "15.01.2026 tarihli YK-100-REV sayılı yazınız.",
            "state": "Acik",
            "review_status": "auto_approved",
        })
        add_link(conn, "p::doc2", "YK-100-REV", "ilgi_zinciri", resolved=False)
        conn.close()

        g = get_correspondence_graph(db_path=db_p, project_id="test_proj")
        assert len(g["documents"]) == 2
        assert len(g["pending_review"]) == 1

        # UI insan onayı ile doc_no düzeltildiğinde çözülmemiş İlgi kenarı otomatik bağlanmalı!
        res = update_card_and_approve(
            doc_id="p::doc1",
            doc_date="2026-01-15",
            doc_no="YK-100-REV",
            subject="Test Süre Talebi (Onaylı)",
            new_state="Kismen_Cevaplandi",
            confirmed_by_human=True,
            db_path=db_p,
            correspondence_db_dir=tmp_chroma,
        )
        assert res["state_changed"] is True
        assert res["relinked"] == 1, f"Çözülmemiş İlgi kenarı yeniden bağlanmalıydı: {res}"
        assert res["card"]["review_status"] == "human_approved"
        assert res["card"]["state"] == "Kismen_Cevaplandi"

        g2 = get_correspondence_graph(db_path=db_p, project_id="test_proj")
        assert len(g2["pending_review"]) == 0
        assert len(g2["state_history"]) == 1
        assert g2["state_history"][0]["confirmed_by_human"] == 1
        resolved_edges = [e for e in g2["elements"] if "source" in e["data"] and e["data"].get("resolved")]
        assert len(resolved_edges) == 1
        print("[OK] Cytoscape boş durum + izole insan onayı + otomatik İlgi yeniden bağlama doğrulandı.")
    finally:
        reset_correspondence_cache(tmp_chroma)
        gc.collect()
        try:
            tmp_obj.cleanup()
        except Exception:
            pass


def test_docx_export_and_parse_with_tables() -> None:
    md = (
        "# 1. YÖNETİCİ ÖZETİ\n\n"
        "Bu denetim raporunda **4735 Sayılı Kanun** ve `YİGŞ Madde 29` incelenmiştir.\n\n"
        "## 2. BULGULAR TABLOSU\n\n"
        "| Madde | Durum | Kaynak |\n"
        "|---|---|---|\n"
        "| Madde 29 | ✔ Doğrulandı | YİGŞ Sayfa 14 |\n\n"
        "- Eksik evrak bulunmamaktadır.\n"
    )
    raw = build_docx_bytes_from_markdown(md, report_title="Örnek Test Raporu")
    assert len(raw) > 5000
    d = docx.Document(io.BytesIO(raw))
    full_txt = "\n".join(p.text for p in d.paragraphs)
    assert "Örnek Test Raporu" in full_txt
    assert "4735 Sayılı Kanun" in full_txt
    assert len(d.tables) == 1
    assert d.tables[0].cell(1, 0).text.strip() == "Madde 29"

    # parse_any_document .docx tablo + paragraf okuma ve save_uploaded_petition .docx kabulü
    with tempfile.TemporaryDirectory() as tmp:
        sample_docx = Path(tmp) / "test_dilekce.docx"
        sample_docx.write_bytes(raw)
        parsed = parse_any_document(sample_docx)
        assert "4735 Sayılı Kanun" in parsed
        assert "YİGŞ Sayfa 14" in parsed, "Word tablo hücresi parse_any_document çıktısında olmalıydı!"

    saved_path = save_uploaded_petition("gecici_test_dilekce.docx", raw, "test_ui_upload")
    try:
        assert saved_path.exists()
        assert RAPORLAR_DIR.resolve() in saved_path.resolve().parents
        assert YUKLENICI_TALEPLERI_DIR.resolve() not in saved_path.resolve().parents
    finally:
        if saved_path.exists():
            saved_path.unlink()
        try:
            saved_path.parent.rmdir()
        except OSError:
            pass
    print(f"[OK] Word (.docx) export + tablo parse + Katman 3 kirletmeyen upload doğrulandı ({len(raw):,} bayt).")


def test_legislation_center_and_projects() -> None:
    st = get_legislation_sync_status()
    assert st["total_catalog"] == 35
    assert len(st["rows"]) == 35
    projs = list_known_projects()
    assert "ornek_proje" in projs
    print(f"[OK] Mevzuat Merkezi ({st['total_catalog']} kaynak) ve proje keşfi ({projs}) doğrulandı.")


if __name__ == "__main__":
    test_memory_inventory_tree_and_chunks()
    test_correspondence_graph_relink_and_human_approval_isolated()
    test_docx_export_and_parse_with_tables()
    test_legislation_center_and_projects()
    print("TÜM UI SERVİS TESTLERİ BAŞARIYLA GEÇTİ ✔")
