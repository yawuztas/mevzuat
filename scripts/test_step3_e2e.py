# -*- coding: utf-8 -*-
"""Adım 3 uçtan uca doğrulama (Tamamen İzole Geçici DB + Fiziksel Dual-DB Kanıtı):
1) Geçici yazışma klasörleri üzerinde gerçek `ingest_project_history` çalışır (üretim DB'lerine DOKUNMAZ).
2) 2. tur OCR-fuzzy İlgi zinciri çözümlemesi (5.23-401 -> S.23-401 -> YK-2023-4236).
3) state='Acik' varsayılanı ve mevcut durumun (Cevaplandi) yeniden upsert ile korunması.
4) FİZİKSEL İZOLASYON KANITI:
   - Normatif ChromaDB (`vector_db/insaat_mevzuat`) 0 adet `correspondence_history` içerir ve değişmez.
   - Yazışma ChromaDB (`proje_yazismalari`) yalnızca geçici yazışma klasöründe büyür.
   - `doc_role='normative_rule'` yazışmaları ASLA çekmez; `doc_role='correspondence_history'`
     yalnızca yazışma DB'sinden ve yalnızca kendi projesini çeker.
"""
from __future__ import annotations

import gc
import importlib.util
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from utils import project_db as pdb
from utils.case_context_builder import build_case_context
from utils.retriever import (
    get_chroma_collection,
    get_correspondence_collection,
    reset_correspondence_cache,
    search_and_rerank,
)


def _load_ingest_history():
    spec = importlib.util.spec_from_file_location("ingest_history_mod", PROJECT_ROOT / "ingest_history.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    proj = "test_izole_yazisma_projesi"
    norm_col = get_chroma_collection()
    norm_count_before = norm_col.count()
    norm_corr_before = norm_col.get(where={"doc_role": "correspondence_history"}).get("ids") or []
    assert len(norm_corr_before) == 0, (
        f"Normatif DB (vector_db/insaat_mevzuat) içinde correspondence_history olmamalı! Bulunan: {len(norm_corr_before)}"
    )

    ih = _load_ingest_history()

    tmp_obj = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    tmp = Path(tmp_obj.name)
    tmp_chroma = tmp / "vector_db_yazismalar_test"
    tmp_db = tmp / "project_graph_test.db"
    hist_root = tmp / "3_yuklenici_talepleri"
    proj_dir = hist_root / proj

    try:
        # Sentetik 4 yazışma oluştur (2. tur OCR-fuzzy zinciri: 5.23-401 -> S.23-401 -> YK-2023-4236)
        (proj_dir / "1_yuklenici_yazilari" / "2023").mkdir(parents=True)
        (proj_dir / "2_idare_cevaplari" / "2023").mkdir(parents=True)
        (proj_dir / "4_hakedis_ozetleri" / "2024").mkdir(parents=True)

        (proj_dir / "1_yuklenici_yazilari" / "2023" / "2023-04-02_yuk_4236_sure_uzatimi.md").write_text(
            "Tarih: 02.04.2023\n"
            "Sayı: YK-2023-4236\n"
            "İlgi: 12.03.2023 tarihli iş programı güncellememiz.\n"
            "Konu: Süre Uzatımı Talebi (210 Gün Yer Teslimi Gecikmesi)\n\n"
            "EN 50122-1 standardı ve yer teslimi gecikmesi nedeniyle 210 gün süre uzatımı talep ediyoruz.\n",
            encoding="utf-8",
        )
        (proj_dir / "1_yuklenici_yazilari" / "2023" / "2023-06-10_yuk_4289_itiraz.md").write_text(
            "Tarih: 10.06.2023\n"
            "Sayı: YK-2023-4289\n"
            "İlgi: 18.05.2023 tarihli ve 5.23-401 sayılı yazınız.\n"
            "Konu: Süre Uzatım Cevabına İtiraz\n\n"
            "IEC 60870-5-104 kapsamında verilen 120 günlük süre uzatımı yetersizdir, itiraz ediyoruz.\n",
            encoding="utf-8",
        )
        (proj_dir / "2_idare_cevaplari" / "2023" / "2023-05-18_S.23-401_cevap.md").write_text(
            "Tarih: 18.05.2023\n"
            "Sayı: S.23-401\n"
            "İlgi: 02.04.2023 tarihli ve YK-2023-4236 sayılı yazınız.\n"
            "Konu: Süre Uzatımı Talebine Cevap\n\n"
            "Yapılan inceleme sonucu 120 gün süre uzatımı uygun görülmüştür.\n",
            encoding="utf-8",
        )
        (proj_dir / "4_hakedis_ozetleri" / "2024" / "2024-01-15_hakedis_ozet_112.md").write_text(
            "Tarih: 15.01.2024\n"
            "HAKEDİŞ 112 ÖZETİ: 12.450.000 TL tutarlı imalat; EN 50122-1 ve IEC 60870-5-104.\n",
            encoding="utf-8",
        )

        print("1) İZOLE İNGEST + 2 TURLU OCR-FUZZY ZİNCİR + STATE KONTROLÜ")
        stats = ih.ingest_project_history(
            proj,
            project_dir=proj_dir,
            history_root_dir=hist_root,
            db_path=tmp_db,
            chroma_dir=tmp_chroma,
            use_llm=False,
        )
        assert stats["processed"] == 4, f"4 belge işlenmeliydi: {stats}"

        conn = pdb.connect(tmp_db)
        try:
            docs = conn.execute(
                "SELECT doc_id, doc_no, state, review_status FROM documents WHERE project_id=?", (proj,)
            ).fetchall()
            assert len(docs) == 4, f"Beklenen 4 belge, bulunan {len(docs)}"
            assert all(d["state"] in pdb.VALID_STATES for d in docs)

            d4289 = pdb.find_by_doc_no(conn, proj, "YK-2023-4289")
            assert d4289 is not None, "YK-2023-4289 bulunamadı"
            chain = pdb.iter_chain(conn, d4289["doc_id"])
            chain_nos = [c["doc_no"] for c in chain]
            print("   YK-2023-4289 zinciri:", chain_nos)
            assert chain_nos == ["S.23-401", "YK-2023-4236"], f"Zincir bozuk: {chain_nos}"

            # Mevcut state koruma testi
            pdb.upsert_document(conn, {"doc_id": f"{proj}::state_chk", "project_id": proj, "state": "Acik"})
            pdb.update_state(conn, f"{proj}::state_chk", "Cevaplandi", confirmed_by_human=True)
            pdb.upsert_document(conn, {"doc_id": f"{proj}::state_chk", "project_id": proj})
            st = pdb.get_document(conn, f"{proj}::state_chk")["state"]
            assert st == "Cevaplandi", f"State ezildi: {st}"
            pdb.delete_document(conn, f"{proj}::state_chk")
            print("   ✔ state koruması ve 2 turlu OCR-fuzzy zincir doğrulandı")

            print("\n2) FİZİKSEL DUAL-DB İZOLASYONU KANITI")
            assert norm_col.count() == norm_count_before, "Normatif DB sayısı yazışma eklenince değişmemeli!"
            norm_corr_after = norm_col.get(where={"doc_role": "correspondence_history"}).get("ids") or []
            assert len(norm_corr_after) == 0, "Normatif DB'ye yazışma sızdı!"

            corr_col = get_correspondence_collection(db_dir=tmp_chroma)
            corr_cnt = corr_col.count()
            print(f"   Normatif DB (vector_db): {norm_col.count()} (0 yazışma) | İzole Yazışma DB: {corr_cnt} parça")
            assert corr_cnt >= 4, f"Yazışma DB'sinde en az 4 parça olmalı: {corr_cnt}"

            # Normatif arama sızıntı testi
            res_norm = search_and_rerank(
                query="HAKEDİŞ 112 12.450.000 TL 210 gün 5.23-401 süre uzatımı",
                domain="idari",
                project_id=proj,
                candidate_k=15,
                final_top_k=4,
                doc_role="normative_rule",
            )
            leak = [x for x in res_norm if x.get("metadata", {}).get("doc_role") != "normative_rule"]
            print(f"   normative_rule sorgusu: {len(res_norm)} sonuç | sızan yazışma: {len(leak)}")
            assert not leak, f"SIZINTI VAR: {leak}"

            # Yazışma DB semantik arama testi
            res_hist = search_and_rerank(
                query="210 gün süre uzatımı yer teslimi gecikmesi 120 gün cevap",
                project_id=proj,
                candidate_k=10,
                final_top_k=3,
                doc_role="correspondence_history",
                correspondence_db_dir=tmp_chroma,
            )
            print("   correspondence_history sorgusu:", [(x["metadata"].get("doc_no"), x["metadata"].get("evidence_weight")) for x in res_hist])
            assert len(res_hist) >= 1 and all(x["metadata"].get("doc_role") == "correspondence_history" for x in res_hist)

            # Çapraz proje izolasyon testi (başka proje yazışma DB'sinden 0 sonuç almalı)
            res_other = search_and_rerank(
                query="210 gün süre uzatımı",
                project_id="baska_hayali_proje",
                candidate_k=10,
                final_top_k=3,
                doc_role="correspondence_history",
                correspondence_db_dir=tmp_chroma,
            )
            assert len(res_other) == 0, f"Başka projeye yazışma sızdı: {res_other}"

            # CaseContextBuilder semantik tarihçe entegrasyonu
            ctx = build_case_context(
                "Tarih: 01.07.2023\nSayı: YK-2023-9999\nKonu: Ek Süre Talebi\nYer teslimi gecikmesi ve 120 gün süre uzatımı cevabı hk.",
                project_id=proj,
                conn=conn,
                history_base_dir=hist_root,
                use_semantic_history=True,
                correspondence_db_dir=tmp_chroma,
            )
            assert ctx["stats"]["related_count"] >= 1, "CaseContextBuilder ayrı yazışma DB'den ilişkili belge çekebilmeli"
            print("   ✔ Fiziksel Dual-DB izolasyonu + çapraz proje koruması + CaseContextBuilder semantik arama doğrulandı")
        finally:
            conn.close()
    finally:
        reset_correspondence_cache(tmp_chroma)
        gc.collect()
        try:
            tmp_obj.cleanup()
        except Exception:
            pass

    print("\nADIM 3 UÇTAN UCA (FİZİKSEL DUAL-DB) TESTİ TAMAMEN GEÇTİ ✔")


if __name__ == "__main__":
    main()
