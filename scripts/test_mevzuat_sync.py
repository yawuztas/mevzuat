# -*- coding: utf-8 -*-
"""
Katman 1 Mevzuat Senkronizasyon Motoru Testleri (Gerçek Dönüşüm, Diff ve Sürüm Koruması)
Not: Üretim data/ ve vector_db/ klasörlerine dokunmaz; geçici dizin üzerinde gerçek docx/html üretip test eder.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
from pathlib import Path

import docx

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.mevzuat_sync import (  # noqa: E402
    MevzuatSource,
    MevzuatSyncEngine,
    compute_article_diff,
    compute_sha256_text,
    docx_bytes_to_body_markdown,
    html_text_to_body_markdown,
    strip_sync_header,
)

# 1_ingest.py modülünü doğrudan yükle (sayı ile başladığı için importlib)
spec = importlib.util.spec_from_file_location("ingest_mod", BASE_DIR / "1_ingest.py")
ingest_mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(ingest_mod)


def _build_sample_docx_bytes(paragraphs: list[str], table_rows: list[list[str]]) -> bytes:
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    t = d.add_table(rows=len(table_rows), cols=len(table_rows[0]))
    for r_i, row in enumerate(table_rows):
        for c_i, val in enumerate(row):
            t.cell(r_i, c_i).text = val
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_html_and_docx_converters_and_tables() -> None:
    html = """
    <html><body>
      <h2>BİRİNCİ BÖLÜM</h2>
      <p>Amaç ve kapsam</p>
      <p>MADDE 1 – (1) Bu Yönetmeliğin amacı raylı sistem işlerinde usul ve esasları düzenlemektir.</p>
      <table>
        <tr><th>Kalem</th><th>Oran</th></tr>
        <tr><td>Demir</td><td>0,35</td></tr>
      </table>
      <p>MADDE 2 – (1) İdare onayından itibaren 15 gün içinde işe başlanır.</p>
    </body></html>
    """
    md_html = html_text_to_body_markdown(html)
    assert "## BİRİNCİ BÖLÜM" in md_html
    assert "### MADDE 1 – (1)" in md_html
    assert "| Kalem | Oran |" in md_html
    assert "| Demir | 0,35 |" in md_html
    assert "### MADDE 2 – (1)" in md_html

    raw_docx = _build_sample_docx_bytes(
        [
            "BİRİNCİ BÖLÜM",
            "Madde 5- Fiyat farkı formülü aşağıda verilmiştir.",
        ],
        [
            ["Katsayı", "Açıklama"],
            ["a", "Sabit katsayı"],
        ],
    )
    md_docx = docx_bytes_to_body_markdown(raw_docx)
    assert "## BİRİNCİ BÖLÜM" in md_docx
    assert "### Madde 5-" in md_docx
    assert "| Katsayı | Açıklama |" in md_docx
    assert "| a | Sabit katsayı |" in md_docx
    print("[OK] HTML ve DOCX -> Yasal Markdown + tablo dönüşümü doğrulandı.")


def test_version_protection_archive_and_article_diff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_data = Path(tmp) / "data"
        rel = "1_genel_mevzuat_ve_standartlar/1_kanunlar/4735_test.md"
        legacy_rel = "1_genel_mevzuat_ve_standartlar/1_kanunlar/eski_bozuk.md"
        (tmp_data / legacy_rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_data / legacy_rel).write_text("eski bozuk özet", encoding="utf-8")

        src = MevzuatSource(
            key="test_4735",
            title="Test 4735 Sayılı Kanun",
            rel_path=rel,
            source_kind="mevzuat_html",
            mevzuat_tur=1,
            mevzuat_no=4735,
        )
        engine = MevzuatSyncEngine(data_dir=tmp_data, catalog=[src])
        reg = engine.load_registry()
        reg_sources = reg.setdefault("sources", {})

        v1_body = (
            "## BİRİNCİ BÖLÜM\n\n"
            "### MADDE 1 – Amaç\n\nBu kanun kamu ihale sözleşmelerini düzenler.\n\n"
            "### MADDE 10 – Mücbir sebepler\n\nDoğal afetler mücbir sebep sayılır.\n\n"
            "### MADDE 20 – İdarenin feshi\n\nYirmi gün süre verilir."
        )
        res1 = engine.apply_local_update(
            src,
            {"body": v1_body, "source_url": "https://example.test", "version_tag": "v1"},
            reg_sources,
            "2026-11-13_1000",
        )
        assert res1["status"] == "added"

        # Aynı gövde (yalnızca sonda boşluk farkı) tekrar gelirse UNCHANGED dönmeli ve arşiv oluşturmamalı
        res_same = engine.apply_local_update(
            src,
            {"body": v1_body + "\n   \n", "source_url": "https://example.test", "version_tag": "v1"},
            reg_sources,
            "2026-11-13_1005",
        )
        assert res_same["status"] == "unchanged"
        assert not (tmp_data / "_arsiv").exists()

        # Şimdi MADDE 10 değişsin, MADDE 20 kalsın, EK MADDE 1 eklensin -> UPDATED + ARŞİV + DIFF
        v2_body = (
            "## BİRİNCİ BÖLÜM\n\n"
            "### MADDE 1 – Amaç\n\nBu kanun kamu ihale sözleşmelerini düzenler.\n\n"
            "### MADDE 10 – Mücbir sebepler\n\nDoğal afetler ve salgın hastalıklar mücbir sebep sayılır.\n\n"
            "### MADDE 20 – İdarenin feshi\n\nYirmi gün süre verilir.\n\n"
            "### EK MADDE 1 – Yeni hüküm\n\nEk düzenleme."
        )
        res2 = engine.apply_local_update(
            src,
            {"body": v2_body, "source_url": "https://example.test", "version_tag": "v2"},
            reg_sources,
            "2026-11-13_1010",
        )
        assert res2["status"] == "updated"
        archive_p = Path(res2["archive_path"])
        assert archive_p.exists(), "Önceki sürüm arşivlenmedi!"
        archived_meta, archived_body = strip_sync_header(archive_p.read_text(encoding="utf-8"))
        assert archived_meta is not None and archived_meta["version_tag"] == "v1"
        assert compute_sha256_text(archived_body) == compute_sha256_text(v1_body)

        diff = res2["diff"]
        assert diff["added_articles"] == ["EK MADDE 1 – Yeni hüküm"]
        assert [m["article"] for m in diff["modified_articles"]] == ["MADDE 10 – Mücbir sebepler"]
        assert diff["removed_articles"] == []

        purged = engine.purge_legacy_broken_files([legacy_rel])
        assert purged == [legacy_rel] and not (tmp_data / legacy_rel).exists()

        report_p = engine.write_sync_report([res2], purged, "2026-11-13_1010")
        rep_txt = report_p.read_text(encoding="utf-8")
        assert "MADDE 10 – Mücbir sebepler" in rep_txt
        assert "EK MADDE 1 – Yeni hüküm" in rep_txt

        # 1_ingest.py chunking & metadata uyumluluğu testi
        chunks = ingest_mod.split_markdown_into_legal_chunks(
            (tmp_data / rel).read_text(encoding="utf-8"),
            filename="4735_test.md",
            domain="mevzuat",
            scope="global",
            project_id="global",
            rel_path=rel,
            procurement_type="ortak",
        )
        assert len(chunks) >= 4
        assert all(c["metadata"]["doc_type"] == "kanun" for c in chunks)
        assert any("MADDE 10" in c["metadata"]["title"] for c in chunks)
        print("[OK] Sürüm koruma (arşiv + diff + rapor + 1_ingest chunk uyumu) doğrulandı.")


if __name__ == "__main__":
    test_html_and_docx_converters_and_tables()
    test_version_protection_archive_and_article_diff()
    print("TÜM TESTLER BAŞARIYLA GEÇTİ.")
