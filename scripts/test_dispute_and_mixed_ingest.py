# -*- coding: utf-8 -*-
"""
Akıllı Karma Klasör Alıcısı + Uyuşmazlık Zinciri Kümeleyici + UI Graf Filtreleme Testleri
(Tamamen yalıtılmış geçici SQLite + geçici Yazışma ChromaDB — üretim verilerine DOKUNMAZ)
"""
from __future__ import annotations

import gc
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

import docx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from utils.card_extractor import classify_sender_role_and_type
from utils.dispute_analyzer import build_project_dispute_matrix_markdown, discover_dispute_clusters
from utils.project_db import connect, iter_chain
from utils.retriever import get_chroma_collection, get_correspondence_collection, reset_correspondence_cache
from utils.ui_service import build_dispute_matrix_export, get_correspondence_graph


def _load_ingest_history():
    spec = importlib.util.spec_from_file_location("ingest_history_mixed_test", PROJECT_ROOT / "ingest_history.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_1_party_classifier_on_realistic_turkish_letters() -> None:
    """Antet vs muhatap yönü, EBYS/GD/PM evrak kodları ve ortak tutanak tespiti."""
    contractor_txt = (
        "ABC-XYZ RAYLI SİSTEM İNŞAAT ADİ ORTAKLIĞI\n"
        "T.C. İSTANBUL BÜYÜKŞEHİR BELEDİYESİ\n"
        "AVRUPA YAKASI RAYLI SİSTEM MÜDÜRLÜĞÜ'NE\n\n"
        "Tarih: 12.04.2023\n"
        "Sayı: ATI-AS-TR-PM-9400\n"
        "Konu: CBTC Hassas Duruş SAT Test Sonuçları ve Süre Uzatımı Talebi\n\n"
        "EN 50129 standardı uyarınca hazırlanan SAT raporumuz ekte sunulmuştur.\n"
        "Gereğini saygılarımızla arz ederiz.\n"
        "Proje Müdürü\n"
    )
    c1 = classify_sender_role_and_type(contractor_txt, filename="9400.pdf", doc_no="ATI-AS-TR-PM-9400")
    assert c1["sender_role"] == "contractor", f"Yüklenici olmalıydı (muhatap İdare'ye kanmamalı!): {c1}"
    assert c1["confidence"] >= 0.85, f"Güven yüksek olmalı: {c1}"

    admin_txt = (
        "T.C.\n"
        "İSTANBUL BÜYÜKŞEHİR BELEDİYESİ\n"
        "RAYLI SİSTEM DAİRE BAŞKANLIĞI\n\n"
        "Sayı: E-70659999-755.02.S.23-401\n"
        "Tarih: 18.05.2023\n"
        "Konu: Hassas Duruş SAT Raporuna Cevap\n"
        "İlgi: 12.04.2023 tarihli ve ATI-AS-TR-PM-9400 sayılı yazınız.\n\n"
        "ABC-XYZ RAYLI SİSTEM İNŞAAT ADİ ORTAKLIĞINA\n\n"
        "Sunulan SAT test sonuçları uygun görülmemiş olup talebiniz reddedilmiştir.\n"
        "Bilgilerinizi ve gereğini rica ederim.\n"
        "Başkan a. Daire Başkanı\n"
        "5070 sayılı Elektronik İmza Kanunu gereğince elektronik imza ile imzalanmıştır.\n"
    )
    c2 = classify_sender_role_and_type(admin_txt, filename="cevap_401.pdf", doc_no="E-70659999-755.02.S.23-401")
    assert c2["sender_role"] == "administration", f"İdare olmalıydı: {c2}"
    assert c2["doc_type"] == "idare_cevabi"
    assert c2["confidence"] >= 0.85

    consultant_txt = (
        "EMAY ULUSLARARASI MÜHENDİSLİK VE MÜŞAVİRLİK A.Ş.\n"
        "Kontrollük Teşkilatı\n\n"
        "Tarih: 25.04.2023\n"
        "Sayı: 2016.03/GD-5751\n"
        "Konu: SAT Raporu Teknik Değerlendirmesi\n"
        "İlgi: ATI-AS-TR-PM-9400 sayılı yazınız.\n\n"
        "ABC-XYZ ADİ ORTAKLIĞINA\n\n"
        "Teknik inceleme sonucunda eksik belgelerin tamamlanması gerekmektedir.\n"
        "Kontrol Amiri / Müşavir Proje Müdürü\n"
    )
    c3 = classify_sender_role_and_type(consultant_txt, filename="5751_degerlendirme.pdf", doc_no="2016.03/GD-5751")
    assert c3["sender_role"] == "consultant", f"Müşavir olmalıydı: {c3}"
    assert c3["doc_type"] == "musavir_yazisi"

    joint_txt = (
        "MÜŞTEREK SAHA TESPİT TUTANAĞI\n"
        "Tarih: 02.06.2023\n"
        "Sayı: TUT-2023-07\n"
        "Konu: İstasyon Peron Kapısı Sinyal Arayüz Tespiti\n\n"
        "İşbu tutanak İdare, Müşavir ve Yüklenici temsilcilerince müştereken imza altına alınmıştır.\n"
        "İdare Temsilcisi | Müşavir Temsilcisi | Yüklenici Temsilcisi\n"
    )
    c4 = classify_sender_role_and_type(joint_txt, filename="tutanak_07.md", doc_no="TUT-2023-07")
    assert c4["sender_role"] == "joint" and c4["doc_type"] == "tutanak", f"Ortak tutanak olmalıydı: {c4}"
    print("PASS [Test 1]: Antet/muhatap/evrak-no tabanlı 4 taraflı otomatik sınıflandırma doğrulandı.")


def test_2_mixed_folder_ingest_organize_and_dispute_clusters() -> None:
    """Karma tek klasör alımı + --organize + 2. tur OCR İlgi + Uyuşmazlık Kümeleri + UI filtreleri."""
    proj = "test_sinyal_karma_405"
    norm_col = get_chroma_collection()
    norm_before = norm_col.count()

    ih = _load_ingest_history()
    tmp_obj = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    tmp = Path(tmp_obj.name)
    src_mixed = tmp / "indirilen_karma_sinyal"
    src_mixed.mkdir(parents=True)
    proj_dir = tmp / "3_yuklenici_talepleri" / proj
    proj_dir.mkdir(parents=True)
    tmp_db = tmp / "graph.db"
    tmp_chroma = tmp / "corr_chroma"

    try:
        # KÜME 1 (4 yazı: Yüklenici -> Müşavir + İdare -> Yüklenici itirazı [OCR 5.23-401])
        (src_mixed / "doc_a_9400.md").write_text(
            "ABC-XYZ İNŞAAT ADİ ORTAKLIĞI\n"
            "T.C. İSTANBUL BÜYÜKŞEHİR BELEDİYESİ RAYLI SİSTEM MÜDÜRLÜĞÜ'NE\n"
            "Tarih: 12.04.2023\nSayı: ATI-AS-TR-PM-9400\n"
            "Konu: CBTC Hassas Duruş SAT Testi ve Süre Uzatımı Talebi\n\n"
            "EN 50129 ve IEEE 1474 uyarınca CBTC testlerimiz tamamlandı, 60 gün süre uzatımı talep ederiz.\n"
            "Saygılarımızla arz ederiz.\n",
            encoding="utf-8",
        )
        (src_mixed / "doc_b_5751.md").write_text(
            "EMAY MÜHENDİSLİK MÜŞAVİRLİK A.Ş.\n"
            "Tarih: 25.04.2023\nSayı: 2016.03/GD-5751\n"
            "İlgi: 12.04.2023 tarihli ATI-AS-TR-PM-9400 sayılı yazınız.\n"
            "Konu: CBTC SAT Testi Eksik Belge İncelemesi\n\n"
            "ABC-XYZ ADİ ORTAKLIĞINA\n"
            "EN 50129 emniyet dosyasında uygunsuzluk ve eksik bilgi tespit edilmiştir.\n"
            "Kontrol Amiri / Müşavir Proje Müdürü\n",
            encoding="utf-8",
        )
        (src_mixed / "doc_c_401.md").write_text(
            "T.C. İSTANBUL BÜYÜKŞEHİR BELEDİYESİ\nRAYLI SİSTEM DAİRE BAŞKANLIĞI\n"
            "Tarih: 18.05.2023\nSayı: E-70659999-755.02.S.23-401\n"
            "İlgi: 12.04.2023 tarihli ATI-AS-TR-PM-9400 sayılı yazınız.\n"
            "Konu: CBTC Süre Uzatımı Talebine Cevap\n\n"
            "ABC-XYZ ADİ ORTAKLIĞINA\n"
            "Süre uzatımı talebiniz uygun görülmemiş olup reddedilmiştir.\n"
            "Başkan a. Daire Başkanı\nGereğini rica ederim.\n",
            encoding="utf-8",
        )
        (src_mixed / "doc_d_9488.md").write_text(
            "ABC-XYZ İNŞAAT ADİ ORTAKLIĞI\n"
            "T.C. İSTANBUL BÜYÜKŞEHİR BELEDİYESİ RAYLI SİSTEM MÜDÜRLÜĞÜ'NE\n"
            "Tarih: 10.06.2023\nSayı: ATI-AS-TR-PM-9488\n"
            "İlgi: 18.05.2023 tarihli 5.23-401 sayılı yazınız.\n"
            "Konu: CBTC Süre Uzatımı Reddine İtiraz\n\n"
            "EN 50129 kapsamında ret kararına itiraz ediyoruz; ek maliyet hakkımız saklıdır.\n"
            "Saygılarımızla arz ederiz.\n",
            encoding="utf-8",
        )

        # KÜME 2 (Arşivde OLMAYAN ortak 'ATI-AS-TR-PM-8800' referansıyla köprülenen 2 yazı!)
        (src_mixed / "doc_e_8810.md").write_text(
            "ABC-XYZ İNŞAAT ADİ ORTAKLIĞI\n"
            "T.C. İSTANBUL BÜYÜKŞEHİR BELEDİYESİ RAYLI SİSTEM MÜDÜRLÜĞÜ'NE\n"
            "Tarih: 05.08.2023\nSayı: ATI-AS-TR-PM-8810\n"
            "İlgi: ATI-AS-TR-PM-8800 sayılı yazımız.\n"
            "Konu: ISA Bağımsız Emniyet Değerlendirme Raporu Gecikmesi\n\n"
            "EN 50126 ISA sertifikasyonu için onay gecikmesi yaşanmaktadır.\n"
            "Saygılarımızla arz ederiz.\n",
            encoding="utf-8",
        )
        (src_mixed / "doc_f_8890.md").write_text(
            "ABC-XYZ İNŞAAT ADİ ORTAKLIĞI\n"
            "T.C. İSTANBUL BÜYÜKŞEHİR BELEDİYESİ RAYLI SİSTEM MÜDÜRLÜĞÜ'NE\n"
            "Tarih: 22.09.2023\nSayı: ATI-AS-TR-PM-8890\n"
            "İlgi: ATI-AS-TR-PM-8800 sayılı yazımız.\n"
            "Konu: ISA Gecikmesi İhtar ve Tahkim Rezervi\n\n"
            "EN 50126 ISA gecikmesine ilişkin ihtar ve ek süre talebimizi yineliyoruz.\n"
            "Saygılarımızla arz ederiz.\n",
            encoding="utf-8",
        )

        # KÜME 3 (Tekil Ortak Tutanak)
        (src_mixed / "doc_g_tutanak.md").write_text(
            "MÜŞTEREK SAHA TESPİT TUTANAĞI\n"
            "Tarih: 01.10.2023\nSayı: TUT-2023-15\n"
            "Konu: Depo Sahası Ray Devresi Ölçüm Tutanağı\n\n"
            "İdare, Müşavir ve Yüklenici temsilcilerince müştereken imzalanmıştır.\n",
            encoding="utf-8",
        )

        stats = ih.ingest_project_history(
            proj,
            project_dir=proj_dir,
            source_dir=src_mixed,
            history_root_dir=tmp / "3_yuklenici_talepleri",
            db_path=tmp_db,
            chroma_dir=tmp_chroma,
            organize=True,
            use_llm=False,
        )
        assert stats["processed"] == 7 and stats["failed"] == 0, f"7 belge hatasız işlenmeliydi: {stats}"
        assert stats["role_counts"].get("contractor") == 4, f"4 yüklenici yazısı olmalı: {stats['role_counts']}"
        assert stats["role_counts"].get("administration") == 1, f"1 idare yazısı olmalı: {stats['role_counts']}"
        assert stats["role_counts"].get("consultant") == 1, f"1 müşavir yazısı olmalı: {stats['role_counts']}"
        assert stats["role_counts"].get("joint") == 1, f"1 tutanak olmalı: {stats['role_counts']}"

        # --organize fiziksel kopyaları taraf/yıl klasörlerine oluşturmuş ve orijinalleri korumuş olmalı
        assert (proj_dir / "1_yuklenici_yazilari" / "2023" / "doc_a_9400.md").exists()
        assert (proj_dir / "2_idare_cevaplari" / "2023" / "doc_c_401.md").exists()
        assert (proj_dir / "3_tutanak_ve_toplantilar" / "2023" / "doc_g_tutanak.md").exists()
        assert (src_mixed / "doc_a_9400.md").exists(), "Orijinal dosya asla silinmemeli!"

        # Fiziksel Dual-DB izolasyonu kontrolü
        assert norm_col.count() == norm_before, "Normatif DB değişmemeli!"
        assert get_correspondence_collection(db_dir=tmp_chroma).count() >= 7

        conn = connect(tmp_db)
        try:
            # 2. tur OCR zinciri: ATI-AS-TR-PM-9488 -> E-70659999-755.02.S.23-401 (cevaplar) -> ATI-AS-TR-PM-9400
            d9488 = conn.execute("SELECT doc_id FROM documents WHERE doc_no='ATI-AS-TR-PM-9488'").fetchone()
            chain = iter_chain(conn, d9488["doc_id"])
            chain_nos = [c["doc_no"] for c in chain]
            assert "E-70659999-755.02.S.23-401" in chain_nos and "ATI-AS-TR-PM-9400" in chain_nos, (
                f"ilgi_zinciri + cevaplar karma zinciri tam yürünmeliydi: {chain_nos}"
            )

            # Uyuşmazlık kümeleme doğrulaması
            disc = discover_dispute_clusters(conn, project_id=proj)
            assert disc["total_docs"] == 7
            assert disc["cluster_count"] == 3, f"3 küme bekleniyordu (4+2+1), bulunan: {disc['cluster_count']}"
            assert disc["multi_doc_cluster_count"] == 2
            assert disc["high_risk_count"] >= 2

            c_big = next(c for c in disc["clusters"] if c["doc_count"] == 4)
            assert c_big["party_counts"]["contractor"] == 2
            assert c_big["party_counts"]["administration"] == 1
            assert c_big["party_counts"]["consultant"] == 1
            # ATI-AS-TR-PM-9488 henüz cevapsız yüklenici yazısı olarak yakalanmalı!
            assert any(u["doc_no"] == "ATI-AS-TR-PM-9488" for u in c_big["unanswered_docs"])
            assert "EN 50129" in c_big["shared_standards"]
            assert c_big["risk_level"] == "Yüksek"

            c_bridged = next(c for c in disc["clusters"] if c["doc_count"] == 2)
            assert any("8800" in r for r in c_bridged["missing_refs"]), (
                f"Ortak eksik İlgi (8800) ile 2 yazı köprülenmeliydi: {c_bridged}"
            )
            assert c_bridged["unanswered_count"] == 2

            # 0-LLM Markdown & Word matrisi
            md_mat = build_project_dispute_matrix_markdown(disc)
            assert "ATI-AS-TR-PM-8800" in md_mat and "K01" in md_mat
        finally:
            conn.close()

        exp = build_dispute_matrix_export(project_id=proj, db_path=tmp_db)
        d_obj = docx.Document(io.BytesIO(exp["docx_bytes"]))
        assert len(d_obj.tables) >= 1

        # UI Graf filtreleri + max_nodes tavanı doğrulaması
        g_cluster = get_correspondence_graph(db_path=tmp_db, project_id=proj, cluster_doc_ids=c_big["doc_ids"])
        assert len(g_cluster["documents"]) == 4 and not g_cluster["truncated"]

        g_search = get_correspondence_graph(db_path=tmp_db, project_id=proj, search_query="EN 50126")
        assert len(g_search["documents"]) == 2

        g_role = get_correspondence_graph(db_path=tmp_db, project_id=proj, role_filter="consultant")
        assert len(g_role["documents"]) == 1 and g_role["documents"][0]["doc_no"] == "2016.03/GD-5751"

        g_cap = get_correspondence_graph(db_path=tmp_db, project_id=proj, max_nodes=3)
        assert g_cap["truncated"] is True and g_cap["shown_docs"] == 3 and g_cap["total_matching"] == 7

        print(
            f"PASS [Test 2]: Karma klasör alımı + --organize + 3 uyuşmazlık kümesi "
            f"(4+2+1, eksik İlgi köprüsü, cevapsız tespit) + UI filtre/tavan doğrulandı."
        )
    finally:
        reset_correspondence_cache(tmp_chroma)
        gc.collect()
        try:
            tmp_obj.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    test_1_party_classifier_on_realistic_turkish_letters()
    test_2_mixed_folder_ingest_organize_and_dispute_clusters()
    print("\nTÜM KARMA KLASÖR + UYUŞMAZLIK KÜMELEME + UI FİLTRE TESTLERİ BAŞARIYLA GEÇTİ ✔")
