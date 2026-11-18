# -*- coding: utf-8 -*-
"""
Adım 4 Gerçek Doğrulama Testleri (Dinamik Vaka Hafızası + Kanıt Ağırlığı + Sabit Bütçe)

Özellikler:
- Tamamen yalıtılmış geçici SQLite veritabanı ve geçici .md evrakları kullanır (sıfır hardcode proje adı).
- 7 seviyeli İlgi zincirinde `2 tam metin + 3 özet` kuralının gerçekten eski seviyeleri kesmesini doğrular.
- Döngüsel İlgi (A <-> B) bağlarında sonsuz döngüye girmeden MIN(depth) ile tekilleştirme doğrular.
- Yüklenicinin atladığı İdare cevabının (`_find_incoming_responses`) yakalanmasını doğrular.
- Kanıt ağırlığı etiketlerini (`BAĞLAYICI KURAL`, `TEKNİK REFERANS`, `RESMİ POZİSYON`, `İDDİA`) doğrular.
- Sabit bütçe motorunun dar bütçede düşük öncelikli (5) blokları eleyip yüksek önceliklileri (1..4) koruduğunu doğrular.
- `2_agents_graph.py` 6 düğümlü graf derlemesini ve `citation_verifier_node` korumasını (`correspondence_history` sızıntı reddini) doğrular.
- Mevcut gerçek `data/project_graph.db` üstünde (varsa salt-okunur) dinamik smoke testi yapar.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.project_db import (
    connect,
    upsert_document,
    add_link,
    add_tags,
    iter_chain,
)
from utils.case_context_builder import (
    PRIORITY_ILGI_CHAIN,
    PRIORITY_LEDGER,
    PRIORITY_NORMATIVE,
    PRIORITY_STANDARDS,
    PRIORITY_SIMILAR_HISTORY,
    DEFAULT_TOTAL_BUDGET_CHARS,
    format_evidence_label,
    assemble_budgeted_context,
    build_case_context,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_agents_graph_module():
    spec = importlib.util.spec_from_file_location("agents_graph_mod", PROJECT_ROOT / "2_agents_graph.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_1_seven_level_chain_and_depth_cutoff():
    """7 belgeli gerçek İlgi zincirinde 2 verbatim + 3 özet seviyesi korunmalı, daha eskiler elenmelidir."""
    proj = "sentetik_rayli_vaka"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        db_path = tmp / "graph.db"
        hist_dir = tmp / "history"
        (hist_dir / proj).mkdir(parents=True)
        conn = connect(db_path)
        try:
            # D0 (en eski) <- D1 <- D2 <- D3 <- D4 <- D5 <- D6 (en yeni DB kaydı)
            doc_ids = []
            for idx in range(7):
                doc_id = f"{proj}::doc_{idx}"
                doc_no = f"SYN-2024-{100 + idx}"
                doc_date = f"2024-0{idx + 1}-10"
                body = (
                    f"Tarih: 10.0{idx + 1}.2024\n"
                    f"Sayı: {doc_no}\n"
                    f"Konu: Zincir Seviyesi {idx} Evrakı\n\n"
                    f"OZEL_ICERIK_SEVIYE_{idx}: Yalnızca seviye {idx} tam metninde geçen benzersiz teknik cümle."
                )
                rel_file = f"{proj}/doc_{idx}.md"
                (hist_dir / rel_file).write_text(body, encoding="utf-8")
                upsert_document(conn, {
                    "doc_id": doc_id,
                    "project_id": proj,
                    "file_path": rel_file,
                    "doc_date": doc_date,
                    "doc_no": doc_no,
                    "sender_role": "RESMI_IDARE" if idx % 2 == 1 else "IDDIA_YUKLENICI",
                    "doc_type": "resmi_yazi",
                    "subject": f"Zincir Seviyesi {idx} Başlığı",
                    "summary": f"Kısa özet seviye {idx}",
                    "extraction_confidence": 0.95,
                    "extraction_method": "regex",
                    "approval_status": "auto_approved",
                    "doc_sha256": _sha(body),
                })
                doc_ids.append(doc_id)

            # Çözümlenmiş bağlar: to_ref hedef doc_id'yi tutar
            for idx in range(1, 7):
                add_link(conn, doc_ids[idx], doc_ids[idx - 1], "ilgi_zinciri", resolved=True)

            # Gelen D7 evrakı SYN-2024-106 (D6)'ya İlgi veriyor
            incoming_text = (
                "Tarih: 15.08.2024\n"
                "Sayı: SYN-2024-107\n"
                "İlgi: SYN-2024-106 sayılı yazımız.\n"
                "Konu: Yeni İtiraz\n\n"
                "Yukarıdaki ilgi yazıya istinaden ek değerlendirme talep ediyoruz."
            )
            res = build_case_context(
                incoming_text,
                doc_path=tmp / "incoming.md",
                project_id=proj,
                conn=conn,
                history_base_dir=hist_dir,
                verbatim_chain_count=2,
                summary_chain_levels=3,
                use_semantic_history=False,
            )
        finally:
            conn.close()

        verbatim_blocks = [b for b in res["blocks"] if b["category"] == "ilgi_chain_verbatim"]
        summary_blocks = [b for b in res["blocks"] if b["category"] == "ilgi_chain_summary"]
        assert len(verbatim_blocks) == 2, f"Tam metin blok sayısı 2 olmalıydı: {len(verbatim_blocks)}"
        verbatim_joined = "\n".join(b["text"] for b in verbatim_blocks)
        assert "OZEL_ICERIK_SEVIYE_6" in verbatim_joined and "OZEL_ICERIK_SEVIYE_5" in verbatim_joined
        assert "OZEL_ICERIK_SEVIYE_4" not in verbatim_joined

        assert len(summary_blocks) == 1
        sum_txt = summary_blocks[0]["text"]
        assert "SYN-2024-104" in sum_txt and "SYN-2024-103" in sum_txt and "SYN-2024-102" in sum_txt
        assert "SYN-2024-101" not in sum_txt and "SYN-2024-100" not in sum_txt, "5. derinlikten eskiler kesilmeliydi"
        print("PASS [Test 1]: 7 seviyeli zincirde 2 tam metin + 3 özet kesimi doğrulandı.")


def test_2_cycle_immunity_and_self_exclusion():
    """Döngüsel İlgi (A <-> B) bağlarında sonsuz döngü oluşmamalı, belge kendini hariç tutmalıdır."""
    proj = "dongu_test_projesi"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        conn = connect(tmp / "cycle.db")
        try:
            body_a = "Sayı: CYC-1\nKonu: İlk Yazı\nMetin A"
            body_b = "Sayı: CYC-2\nİlgi: CYC-1\nKonu: İkinci Yazı\nMetin B"

            upsert_document(conn, {
                "doc_id": f"{proj}::a", "project_id": proj, "file_path": "a.md",
                "doc_date": "2024-01-01", "doc_no": "CYC-1", "sender_role": "IDDIA_YUKLENICI",
                "approval_status": "auto_approved", "doc_sha256": _sha(body_a),
            })
            upsert_document(conn, {
                "doc_id": f"{proj}::b", "project_id": proj, "file_path": "b.md",
                "doc_date": "2024-02-01", "doc_no": "CYC-2", "sender_role": "RESMI_IDARE",
                "approval_status": "auto_approved", "doc_sha256": _sha(body_b),
            })
            # Karşılıklı döngüsel bağ (A -> B ve B -> A)
            add_link(conn, f"{proj}::b", f"{proj}::a", "ilgi_zinciri", resolved=True)
            add_link(conn, f"{proj}::a", f"{proj}::b", "ilgi_zinciri", resolved=True)

            chain = iter_chain(conn, f"{proj}::b", max_depth=8)
            chain_ids = [c["doc_id"] for c in chain]
            assert chain_ids.count(f"{proj}::a") == 1, f"Döngüde tekilleştirme başarısız: {chain_ids}"
            assert f"{proj}::b" not in chain_ids, "Başlangıç düğümü kendi zincirine düşmemeli"

            res = build_case_context(
                body_b, project_id=proj, conn=conn, history_base_dir=tmp, use_semantic_history=False
            )
        finally:
            conn.close()

        returned_ids = {d["doc_id"] for d in res["chain_docs"]}
        assert f"{proj}::b" not in returned_ids
        assert f"{proj}::a" in returned_ids
        print("PASS [Test 2]: Döngüsel bağ koruması (A <-> B) ve self-exclusion doğrulandı.")


def test_3_missed_idare_reply_recovery():
    """Yüklenici önceki talebine İlgi verip İdare cevabını atlasa dahi İdare cevabı RESMİ POZİSYON olarak yakalanmalı."""
    proj = "cevap_kacirma_vaka"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        hist = tmp / "hist"
        (hist / proj).mkdir(parents=True)
        conn = connect(tmp / "missed.db")
        try:
            t1_body = "Tarih: 05.03.2024\nSayı: YUK-300\nKonu: İlk Süre Talebi\n90 gün süre talep ediyoruz."
            r1_body = "Tarih: 20.03.2024\nSayı: IDR-412\nİlgi: YUK-300\nKonu: Süre Talebi Reddi\nBildirim süresi geçtiğinden talebiniz REDDEDİLMİŞTİR."
            (hist / proj / "t1.md").write_text(t1_body, encoding="utf-8")
            (hist / proj / "r1.md").write_text(r1_body, encoding="utf-8")

            upsert_document(conn, {
                "doc_id": f"{proj}::t1", "project_id": proj, "file_path": f"{proj}/t1.md",
                "doc_date": "2024-03-05", "doc_no": "YUK-300", "sender_role": "IDDIA_YUKLENICI",
                "subject": "İlk Süre Talebi", "approval_status": "auto_approved", "doc_sha256": _sha(t1_body),
            })
            upsert_document(conn, {
                "doc_id": f"{proj}::r1", "project_id": proj, "file_path": f"{proj}/r1.md",
                "doc_date": "2024-03-20", "doc_no": "IDR-412", "sender_role": "RESMI_IDARE",
                "subject": "Süre Talebi Reddi", "approval_status": "auto_approved", "doc_sha256": _sha(r1_body),
            })
            add_link(conn, f"{proj}::r1", f"{proj}::t1", "cevaplar", resolved=True)

            # Yüklenici IDR-412'yi kasıtlı olarak atlayıp sadece YUK-300'e İlgi veriyor
            t2_body = "Tarih: 10.05.2024\nSayı: YUK-550\nİlgi: YUK-300 sayılı yazımız.\nKonu: Süre Uzatımı Tekrarı\n90 gün talebimizi yineliyoruz."
            res = build_case_context(
                t2_body, project_id=proj, conn=conn, history_base_dir=hist, use_semantic_history=False
            )
        finally:
            conn.close()

        missed_ids = [d["doc_id"] for d in res["incoming_responses"]]
        assert f"{proj}::r1" in missed_ids, f"Atlanan İdare cevabı IDR-412 yakalanmalıydı: {missed_ids}"
        missed_blocks = [b for b in res["blocks"] if b["category"] == "ilgi_chain_missed_reply"]
        assert len(missed_blocks) == 1
        blk_text = missed_blocks[0]["text"]
        assert "RESMİ POZİSYON (İdare / Müşavir)" in blk_text
        assert "REDDEDİLMİŞTİR" in blk_text
        print("PASS [Test 3]: Atlanan İdare cevabı IDR-412 RESMİ POZİSYON etiketiyle geri getirildi.")


def test_4_evidence_labels_and_budget_priority_eviction():
    """Sabit bütçe motoru yüksek öncelikleri (1..4) koruyup düşük öncelikli (5) benzer tarihçeyi elemelidir."""
    assert "BAĞLAYICI KURAL" in format_evidence_label(doc_role="normative_rule", doc_type="kanun")
    assert "TEKNİK REFERANS" in format_evidence_label(doc_role="normative_rule", doc_type="standart_norm_katalogu")
    assert "RESMİ POZİSYON" in format_evidence_label(sender_role="RESMI_IDARE")
    assert "İDDİA (Yüklenici)" in format_evidence_label(sender_role="IDDIA_YUKLENICI")
    assert "ORTAK TUTANAK" in format_evidence_label(sender_role="ORTAK_TUTANAK")

    blocks = [
        {"priority": PRIORITY_SIMILAR_HISTORY, "category": "similar_history", "text": "P5_BENZER " + ("X" * 700), "allow_truncate": True},
        {"priority": PRIORITY_STANDARDS, "category": "standards", "text": "P4_STANDART EN 50122-1 sınırı 120V.", "allow_truncate": True},
        {"priority": PRIORITY_NORMATIVE, "category": "normative", "text": "P3_BAGLAYICI YİGŞ Madde 29 hükmü.", "allow_truncate": True},
        {"priority": PRIORITY_LEDGER, "category": "ledger_items", "text": "P2_TALEP açık kayıt #42.", "allow_truncate": True},
        {"priority": PRIORITY_ILGI_CHAIN, "category": "ilgi_chain_verbatim", "text": "P1_ILGI en kritik belge " + ("Y" * 300), "allow_truncate": True},
    ]
    out, stats = assemble_budgeted_context(blocks, max_chars=550)
    assert len(out) <= 550, f"Bütçe sınırı aşıldı: {len(out)}"
    assert "P1_ILGI" in out, "Öncelik 1 düşmemeli"
    assert "P2_TALEP" in out, "Öncelik 2 düşmemeli"
    assert "P3_BAGLAYICI" in out, "Öncelik 3 (BAĞLAYICI KURAL) düşmemeli"
    assert "P5_BENZER" not in out, "Öncelik 5 (benzer tarihçe) dar bütçede elenmeliydi"
    assert stats["dropped"] >= 1
    assert DEFAULT_TOTAL_BUDGET_CHARS == 90000
    print("PASS [Test 4]: Kanıt ağırlığı etiketleri ve katı öncelikli bütçe elemesi doğrulandı.")


def test_5_shared_tags_and_open_claims_ledger():
    """Ortak standart/poz etiketi ve açık talep defteri kayıtları ledger_items içinde gelmelidir."""
    proj = "etiket_defteri_vaka"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        conn = connect(tmp / "ledger.db")
        try:
            b1 = "Sayı: E-10\nKonu: Topraklama Testi\nEN 50122-1 ve Poz 15.100.1001"
            b2 = "Sayı: E-11\nKonu: Açık Ek Süre Talebi\nİdare cevabı bekleniyor."

            upsert_document(conn, {
                "doc_id": f"{proj}::e10", "project_id": proj, "file_path": "e10.md",
                "doc_date": "2024-04-01", "doc_no": "E-10", "sender_role": "IDDIA_YUKLENICI",
                "subject": "Topraklama Testi", "approval_status": "auto_approved", "doc_sha256": _sha(b1),
            })
            add_tags(conn, f"{proj}::e10", [
                {"tag_type": "standart", "tag_value": "EN 50122-1"},
                {"tag_type": "poz_no", "tag_value": "15.100.1001"},
            ])

            upsert_document(conn, {
                "doc_id": f"{proj}::e11", "project_id": proj, "file_path": "e11.md",
                "doc_date": "2024-04-05", "doc_no": "E-11", "sender_role": "IDDIA_YUKLENICI",
                "subject": "Açık Ek Süre Talebi", "approval_status": "auto_approved", "doc_sha256": _sha(b2),
            })

            incoming = "Sayı: E-20\nKonu: Ray Potansiyeli\nEN 50122-1 standardı gereği ölçüm yapıldı."
            res = build_case_context(
                incoming, project_id=proj, conn=conn, history_base_dir=tmp, use_semantic_history=False
            )
        finally:
            conn.close()

        ledger_blocks = [b for b in res["blocks"] if b["category"] == "ledger_items"]
        assert len(ledger_blocks) == 1
        ltxt = ledger_blocks[0]["text"]
        assert "E-10" in ltxt and "EN 50122-1" in ltxt
        assert "E-11" in ltxt
        print("PASS [Test 5]: Ortak standart/poz etiketi ve açık talep defteri blokları doğrulandı.")


def test_6_agents_graph_wiring_and_verifier_history_guard():
    """2_agents_graph 6 düğümü derlemeli ve citation_verifier yalnızca yazışma geçmişinde geçen maddeyi reddetmelidir."""
    mod = _load_agents_graph_module()
    graph = mod.create_audit_graph()
    node_names = set(graph.get_graph().nodes.keys())
    expected = {"reader", "case_builder", "router", "experts", "chief_auditor", "verifier"}
    missing = expected - node_names
    assert not missing, f"Graf eksik düğümler içeriyor: {missing}"

    # Yalnızca correspondence_history içinde geçen sahte madde vs gerçek normatif madde
    fake_history_doc = "Yüklenici dilekçesinde YİGŞ Madde 999 uyarınca talepte bulunduğunu iddia etmektedir."
    fake_history_meta = {
        "doc_role": "correspondence_history",
        "source_file": "yigs_yuklenici_dilekcesi.md",
        "scope": "global",
        "project_id": "global",
        "procurement_type": "ortak",
        "title": "YİGŞ Madde 999 Eski Dilekçe",
        "page_num": 1,
    }
    real_norm_doc = "Yapım İşleri Genel Şartnamesi Madde 29 gereğince süre uzatımı şartları düzenlenir."
    real_norm_meta = {
        "doc_role": "normative_rule",
        "source_file": "yigs_yapim_isleri_genel_sartnamesi.pdf",
        "scope": "global",
        "project_id": "global",
        "procurement_type": "yapim",
        "title": "YİGŞ Madde 29",
        "page_num": 18,
    }

    fake_state = {
        "doc_path": "sentetik.md",
        "doc_text": "",
        "project_id": "global",
        "procurement_type": "yapim",
        "case_context": None,
        "router_result": {},
        "expert_analyses": {
            "mevzuat": {
                "retrieved_chunks": [
                    {"content": fake_history_doc, "metadata": fake_history_meta}
                ]
            }
        },
        "final_report": "Denetim sonucunda YİGŞ Madde 999 ve YİGŞ Madde 29 hükümleri incelenmiştir.",
        "verification_notes": None,
    }

    with patch.object(
        mod,
        "get_or_build_bm25_index",
        return_value={"documents": [fake_history_doc, real_norm_doc], "metadatas": [fake_history_meta, real_norm_meta]},
    ):
        out = mod.citation_verifier_node(fake_state)

    notes = out["verification_notes"]
    rows = {line.split("|")[1].strip().strip("`"): line for line in notes.splitlines() if line.startswith("| `")}
    madde_999_row = next((v for k, v in rows.items() if "999" in k), "")
    madde_29_row = next((v for k, v in rows.items() if "29" in k), "")
    assert "TEYİT EDİLEMEDİ" in madde_999_row or "bulunamadı" in madde_999_row, (
        f"Madde 999 yalnızca correspondence_history içinde olduğu için doğrulanmamalıydı! Satır: {madde_999_row}"
    )
    assert "DOĞRULANDI" in madde_29_row, f"Gerçek normatif Madde 29 doğrulanmalıydı! Satır: {madde_29_row}"
    print("PASS [Test 6]: 6 düğümlü graf derlemesi + correspondence_history verifier koruması doğrulandı.")


def test_7_real_db_smoke_if_present():
    """Gerçek data/project_graph.db mevcutsa, sert kod yazmadan var olan projeyi dinamik okuyup build_case_context çalıştır."""
    real_db = PROJECT_ROOT / "data" / "project_graph.db"
    if not real_db.exists():
        print("SKIP [Test 7]: data/project_graph.db bulunamadı.")
        return

    conn = connect(real_db)
    try:
        row = conn.execute(
            "SELECT project_id, doc_no, doc_date, file_path FROM documents WHERE doc_no IS NOT NULL LIMIT 1"
        ).fetchone()
        if not row:
            print("SKIP [Test 7]: project_graph.db içinde doc_no olan kayıt yok.")
            return

        proj = row["project_id"]
        ref_no = row["doc_no"]
        synthetic_followup = (
            f"Tarih: 15.11.2024\n"
            f"Sayı: DENETIM-SMOKE-01\n"
            f"İlgi: {ref_no} sayılı yazı.\n"
            f"Konu: Gerçek Graf Üzerinden İlgi Zinciri Kontrolü\n\n"
            f"Yukarıdaki ilgi yazıya ilişkin süre ve maliyet incelemesi."
        )
        res = build_case_context(
            synthetic_followup,
            project_id=proj,
            conn=conn,
            use_semantic_history=False,
        )
    finally:
        conn.close()

    assert len(res["chain_docs"]) >= 1, f"Gerçek DB'de {ref_no} için zincir bulunamadı!"
    assert ref_no in res["history_text"], f"{ref_no} history_text içine girmeliydi!"
    print(f"PASS [Test 7]: Gerçek project_graph.db ({proj}) üzerinde dinamik zincir smoke testi geçti ({len(res['chain_docs'])} zincir, {res['stats']['used_chars']} krk).")


if __name__ == "__main__":
    test_1_seven_level_chain_and_depth_cutoff()
    test_2_cycle_immunity_and_self_exclusion()
    test_3_missed_idare_reply_recovery()
    test_4_evidence_labels_and_budget_priority_eviction()
    test_5_shared_tags_and_open_claims_ledger()
    test_6_agents_graph_wiring_and_verifier_history_guard()
    test_7_real_db_smoke_if_present()
    print("\n=== ADIM 4 TÜM TESTLER BAŞARIYLA GEÇTİ ===")
