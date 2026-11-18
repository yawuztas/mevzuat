# -*- coding: utf-8 -*-
"""
Adım 5 Gerçek Doğrulama Testleri (Kapalı Döngü + İnsan Onaylı Durum Makinesi + Gerçek OCR Zinciri)

Özellikler:
- Sert kodlama ve test hilesi yok; yalıtılmış geçici SQLite DB + geçici dosyalar kullanır.
- `suggest_state_transition`: Kismen_Cevaplandi / Cevaplandi / Kapatildi karar kurallarını sınar.
- `record_admin_reply`: Onay verilmeden durumun DEĞİŞMEDİĞİNİ, insan onayı (`confirmed_by_human=True`) ile
  `documents.state` + `state_history` denetim izinin yazıldığını sınar.
- Kapalı döngü sonrası yeni bir yüklenici dilekçesinde `build_case_context`'in eklenen İdare
  cevabını `RESMİ POZİSYON` damgasıyla geri getirdiğini sınar.
- Gerçek İkitelli taranmış PDF önbellekleri (`4236-yüklenici.pdf` -> `5751-müşavir.pdf` -> `S.21-2202.pdf`)
  üzerinde ayrıştırıcı + `match_doc_no_in_project` segment/ayraç eşleştirmesini doğrular.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.card_extractor import extract_card_regex, extract_identity_card
from utils.case_context_builder import build_case_context
from utils.closed_loop import record_admin_reply, suggest_state_transition
from utils.document_parser import parse_any_document
from utils.project_db import connect, get_document, match_doc_no_in_project, upsert_document


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_1_state_suggestion_patterns():
    """Durum makinesi öneri kalıpları yalnızca tavsiye üretir; öncelik sırası kısmi -> kapanış -> cevap."""
    s1 = suggest_state_transition("Eksik bilgi ve revize iş programı sunulması halinde yeniden değerlendirilecektir.")
    assert s1["suggested_state"] == "Kismen_Cevaplandi"

    s2 = suggest_state_transition("İlgili Başkanlık Oluru gereğince 120 gün süre uzatımı verilmesine olur alınmış ve dosya sonuçlandırılmıştır.")
    assert s2["suggested_state"] == "Kapatildi"

    s3 = suggest_state_transition("Süre uzatımı talebiniz sözleşme süresi içinde bildirilmediğinden reddedilmiştir.")
    assert s3["suggested_state"] == "Cevaplandi"

    # Kısmi şart cümlesi ile ret/değerlendirme bir aradaysa erken kapatmamalı
    s4 = suggest_state_transition("Eksik belge tamamlanmadığından talep şu aşamada uygun görülmemiş olup ek bilgi sunulduğunda yeniden değerlendirilecektir.")
    assert s4["suggested_state"] == "Kismen_Cevaplandi"
    print("PASS [Test 1]: Durum geçiş öneri kalıpları ve kısmi-öncelik kuralı doğrulandı.")


def test_2_closed_loop_human_confirmation_and_retrieval():
    """Onaysız durum değişmemeli; insan onayıyla state_history yazılmalı; sonraki evrak cevabı görmeli."""
    proj = "kapali_dongu_sentetik"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        db_path = tmp / "loop.db"
        conn = connect(db_path)
        try:
            # 1) Yüklenici dilekçesini kaydet
            claim_file = tmp / "2024-02-01_yuk_701.md"
            claim_txt = (
                "Tarih: 01.02.2024\n"
                "Sayı: YK-2024-701\n"
                "Konu: Kazı Desteği Nedeniyle 45 Gün Süre Talebi\n\n"
                "Zemin koşullarındaki değişiklik sebebiyle 45 gün süre uzatımı talep ediyoruz."
            )
            claim_file.write_text(claim_txt, encoding="utf-8")
            c_res = extract_identity_card(
                claim_txt,
                filename=claim_file.name,
                rel_path=str(claim_file),
                doc_sha256=_sha(claim_txt),
                doc_id=f"{proj}::claim701",
                project_id=proj,
                doc_type="yuklenici_yazisi",
                sender_role_hint="contractor",
            )
            upsert_document(conn, c_res["card"])
            assert get_document(conn, f"{proj}::claim701")["state"] == "Acik"

            # 2) İdare cevabını ONAYSIZ kaydet -> link + öneri oluşmalı, ama state 'Acik' kalmalı!
            reply_file = tmp / "2024-02-20_idare_910.md"
            reply_txt = (
                "Tarih: 20.02.2024\n"
                "Sayı: S.24-910\n"
                "İlgi: 01.02.2024 tarih ve YK-2024-701 sayılı yazınız.\n"
                "Konu: Süre Talebi Hakkında Eksik Belge Bildirimi\n\n"
                "Zemin etüt raporu ve revize iş programı eksik bilgi içerdiğinden tamamlandığında "
                "yeniden değerlendirilecektir."
            )
            reply_file.write_text(reply_txt, encoding="utf-8")

            r1 = record_admin_reply(
                reply_path=reply_file,
                project_id=proj,
                conn=conn,
                confirmed_by_human=False,
                index_chroma=False,
            )
            assert r1["reply_card"]["evidence_weight"] == "RESMI_POZISYON_IDARE"
            assert r1["pending_state_confirmation"] is True
            assert len(r1["linked_targets"]) == 1
            assert r1["linked_targets"][0]["doc_id"] == f"{proj}::claim701"
            assert r1["suggestions"][0]["suggested_state"] == "Kismen_Cevaplandi"
            assert get_document(conn, f"{proj}::claim701")["state"] == "Acik", "İnsan onayı olmadan durum değişmemeli!"

            # 3) Şimdi insan onayıyla kaydet -> state_history'ye confirmed_by_human=1 düşmeli
            r2 = record_admin_reply(
                reply_path=reply_file,
                project_id=proj,
                conn=conn,
                confirm_state="Kismen_Cevaplandi",
                confirmed_by_human=True,
                index_chroma=False,
            )
            assert len(r2["state_updates"]) == 1 and r2["state_updates"][0]["changed"] is True
            assert get_document(conn, f"{proj}::claim701")["state"] == "Kismen_Cevaplandi"

            hist_row = conn.execute(
                "SELECT old_state, new_state, confirmed_by_human, triggered_by_doc_id FROM state_history WHERE doc_id=?",
                (f"{proj}::claim701",),
            ).fetchone()
            assert hist_row is not None
            assert hist_row["old_state"] == "Acik" and hist_row["new_state"] == "Kismen_Cevaplandi"
            assert hist_row["confirmed_by_human"] == 1
            assert hist_row["triggered_by_doc_id"] == r2["reply_card"]["doc_id"]

            # 4) Yüklenici S.24-910'u atlayıp yine YK-2024-701'e İlgi verirse Vaka Hafızası S.24-910'u geri getirmeli
            followup_txt = (
                "Tarih: 15.03.2024\n"
                "Sayı: YK-2024-750\n"
                "İlgi: YK-2024-701 sayılı yazımız.\n"
                "Konu: Talebimizin Yinelendiği\n\n"
                "45 günlük talebimiz kabul edilmelidir."
            )
            ctx = build_case_context(
                followup_txt, project_id=proj, conn=conn, history_base_dir=tmp, use_semantic_history=False
            )
            missed_nos = [d.get("doc_no") for d in ctx["incoming_responses"]]
            assert "S.24-910" in missed_nos, f"Kapalı döngü İdare cevabı Vaka Hafızasına düşmeliydi: {missed_nos}"
            assert "RESMİ POZİSYON (İdare / Müşavir)" in ctx["history_text"]
        finally:
            conn.close()
    print("PASS [Test 2]: Onaysız koruma + human_confirmed state_history + vaka hafızası kapalı döngüsü doğrulandı.")


def test_3_real_ocr_three_letter_chain():
    """Gerçek İkitelli taranmış PDF'lerinden (4236, 5751, S.21-2202) oluşan alt kümede ayraç/kod eşleşmesini doğrula."""
    base = PROJECT_ROOT / "_arsiv" / "TAHKİM" / "17.06.2026" / "Ekler" / "Süre Uzatım Yazılar ve İlgileri" / "2484-İlgiler"
    files = [
        (base / "4236-yüklenici.pdf", "contractor", "2020-06-08", "ATI/AS/TR/PM/4236"),
        (base / "5751-müşavir.pdf", "consultant", "2021-05-10", "2016.03/GD-5751"),
        (base / "S.21-2202.pdf", "administration", "2021-06-02", "E-70659999-755.02.S.21-2202"),
    ]
    if not all(p.exists() for p, _, _, _ in files):
        print("SKIP [Test 3]: Arşiv örnek PDF'leri bulunamadı.")
        return

    proj = "gercek_ocr_altkume"
    with tempfile.TemporaryDirectory() as tmpdir:
        conn = connect(Path(tmpdir) / "real3.db")
        try:
            doc_ids = {}
            for fp, role, exp_date, exp_no in files:
                txt = parse_any_document(fp)
                res = extract_identity_card(
                    txt,
                    filename=fp.name,
                    rel_path=str(fp),
                    doc_sha256=_sha(txt),
                    doc_id=f"{proj}::{fp.stem}",
                    project_id=proj,
                    doc_type="idare_cevabi" if role != "contractor" else "yuklenici_yazisi",
                    sender_role_hint=role,
                )
                c = res["card"]
                assert c["doc_date"] == exp_date, f"{fp.name} tarih hatası: {c['doc_date']} != {exp_date}"
                assert c["doc_no"] == exp_no, f"{fp.name} sayı hatası: {c['doc_no']} != {exp_no}"
                upsert_document(conn, c)
                doc_ids[fp.name] = (c["doc_id"], res["ilgi_refs"], res["card"].get("ilgi_raw"))

            # 5751-müşavir yazısının İlgi listesindeki 'ATi-AS-TR-PM-4236' referansı 4236-yüklenici ('ATI/AS/TR/PM/4236') ile eşleşmeli!
            refs_5751 = doc_ids["5751-müşavir.pdf"][1]
            assert any("4236" in r for r in refs_5751), f"5751 İlgi refs 4236 içermeliydi: {refs_5751}"
            matched_4236 = match_doc_no_in_project(
                conn, proj, "ATi-AS-TR-PM-4236", ilgi_dates=["2020-06-08"], fuzz_threshold=92
            )
            assert matched_4236 is not None and matched_4236["doc_no"] == "ATI/AS/TR/PM/4236", (
                f"Slash/Tire farkıyla 4236 çözümlenmeliydi: {matched_4236}"
            )
            # Segment son eki: 'S.21-2202' araması 'E-70659999-755.02.S.21-2202' ile eşleşmeli!
            matched_2202 = match_doc_no_in_project(conn, proj, "S.21-2202", ilgi_dates=["2021-06-02"])
            assert matched_2202 is not None and matched_2202["doc_no"] == "E-70659999-755.02.S.21-2202", (
                f"Son ekle S.21-2202 çözümlenmeliydi: {matched_2202}"
            )
        finally:
            conn.close()
    print("PASS [Test 3]: 3 gerçek taranmış İkitelli PDF'i üzerinde tarih/sayı/İlgi ayraç & son-ek eşleşmesi doğrulandı.")


if __name__ == "__main__":
    test_1_state_suggestion_patterns()
    test_2_closed_loop_human_confirmation_and_retrieval()
    test_3_real_ocr_three_letter_chain()
    print("\n=== ADIM 5 KAPALI DÖNGÜ TESTLERİ BAŞARIYLA GEÇTİ ===")
