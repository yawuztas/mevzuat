# -*- coding: utf-8 -*-
"""
InsaatAudit NiceGUI Servis Katmanı Testleri (Gerçek ChromaDB + İzole SQLite + Word Export)
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import docx

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.project_db import connect, get_document, upsert_document  # noqa: E402
from utils.ui_service import (  # noqa: E402
    build_docx_bytes_from_markdown,
    get_correspondence_graph,
    get_document_chunks,
    get_legislation_sync_status,
    get_memory_inventory_and_tree,
    list_known_projects,
    update_card_and_approve,
)


def test_memory_inventory_tree_and_chunks() -> None:
    inv = get_memory_inventory_and_tree()
    assert inv["total_vectors"] > 0, "ChromaDB boş olmamalı"
    assert inv["layer_counts"]["global"] > 0
    assert inv["layer_counts"]["project_normative"] > 0
    tree_children = inv["tree"]["children"]
    assert len(tree_children) == 3

    chunks = get_document_chunks("global", "yapim_isleri_genel_sartnamesi_yigs.md", limit=5)
    assert len(chunks) >= 1, "YİGŞ parçaları okunabilmeli"
    print(f"[OK] Bilgi Ağacı: toplam={inv['total_vectors']} vektör, YİGŞ örnek parça={len(chunks)}")


def test_correspondence_graph_and_human_approval_isolated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_p = Path(tmp) / "test_ui_graph.db"
        conn = connect(db_p)
        upsert_document(conn, {
            "doc_id": "p::doc1",
            "project_id": "test_proj",
            "doc_type": "yuklenici_yazisi",
            "sender_role": "contractor",
            "doc_date": None,
            "doc_no": "YK-100",
            "subject": "Test Süre Talebi",
            "state": "Acik",
            "review_status": "pending_review",
            "summary": "Özet metni",
        })
        conn.close()

        g = get_correspondence_graph(db_path=db_p, project_id="test_proj")
        assert len(g["documents"]) == 1
        assert len(g["pending_review"]) == 1
        assert any(el["data"]["id"] == "p::doc1" for el in g["elements"])

        res = update_card_and_approve(
            doc_id="p::doc1",
            doc_date="2026-01-15",
            doc_no="YK-100-REV",
            subject="Test Süre Talebi (Onaylı)",
            new_state="Kismen_Cevaplandi",
            confirmed_by_human=True,
            db_path=db_p,
        )
        assert res["state_changed"] is True
        assert res["card"]["review_status"] == "human_approved"
        assert res["card"]["doc_date"] == "2026-01-15"
        assert res["card"]["state"] == "Kismen_Cevaplandi"

        g2 = get_correspondence_graph(db_path=db_p, project_id="test_proj")
        assert len(g2["pending_review"]) == 0
        assert len(g2["state_history"]) == 1
        assert g2["state_history"][0]["confirmed_by_human"] == 1
        print("[OK] Cytoscape çizgesi ve izole insan onayı (human_approved + state_history) doğrulandı.")


def test_docx_export_roundtrip() -> None:
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
    print(f"[OK] Markdown -> Word (.docx) dönüşümü doğrulandı ({len(raw):,} bayt).")


def test_legislation_center_and_projects() -> None:
    st = get_legislation_sync_status()
    assert st["total_catalog"] == 35
    assert len(st["rows"]) == 35
    projs = list_known_projects()
    assert "ornek_proje" in projs
    print(f"[OK] Mevzuat Merkezi ({st['total_catalog']} kaynak) ve proje keşfi ({projs}) doğrulandı.")


if __name__ == "__main__":
    test_memory_inventory_tree_and_chunks()
    test_correspondence_graph_and_human_approval_isolated()
    test_docx_export_roundtrip()
    test_legislation_center_and_projects()
    print("TÜM UI SERVİS TESTLERİ BAŞARIYLA GEÇTİ ✔")
