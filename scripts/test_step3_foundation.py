# -*- coding: utf-8 -*-
"""Adım 3 temel testleri: project_db + card_extractor (LLM'siz deterministik katman)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from utils import project_db as pdb
from utils.card_extractor import extract_identity_card, parse_tr_date

hata = []

# ============================================================
print("1) DATEPARSER DMY TUZAĞI")
iso, conf = parse_tr_date("02.04.2023")
print(f"   '02.04.2023' -> {iso} (2023-04-02 OLMALI, 2023-02-04 DEĞİL)")
if iso != "2023-04-02":
    hata.append("DMY tuzağı: gün/ay takası!")
iso2, _ = parse_tr_date("2 Nisan 2023")
print(f"   '2 Nisan 2023' -> {iso2}")
if iso2 != "2023-04-02":
    hata.append("Türkçe ay adı hatası!")
iso3, c3 = parse_tr_date("12/10", default_year=2024)
print(f"   '12/10' (yıl yok, default 2024) -> {iso3} (conf {c3}) — 2024-10-12 beklenir")
if iso3 != "2024-10-12":
    hata.append("yıl tamamlama hatası!")

# ============================================================
print("\n2) PROJECT_DB: CRUD + ZİNCİR + DURUM MAKNESİ")
tmp = Path(tempfile.mkdtemp()) / "project_graph_test.db"
conn = pdb.connect(tmp)

cards = [
    {"doc_id": "p::1", "project_id": "test_proje", "doc_date": "2023-04-02", "doc_no": "E-84920",
     "sender_role": "contractor", "doc_type": "yuklenici_yazisi", "evidence_weight": "IDDIA_YUKLENICI",
     "state": "Acik", "review_status": "auto_approved", "extraction_confidence": 1.0,
     "subject": "Süre uzatımı talebi", "ilgi_raw": "İlgi: 02.02.2023 tarihli yazımız", "summary": "..."},
    {"doc_id": "p::2", "project_id": "test_proje", "doc_date": "2023-05-01", "doc_no": "S.23-401",
     "sender_role": "administration", "doc_type": "idare_cevabi", "evidence_weight": "RESMI_POZISYON_IDARE",
     "state": "Acik", "review_status": "auto_approved", "extraction_confidence": 1.0,
     "subject": "Cevap", "summary": "..."},
    {"doc_id": "p::3", "project_id": "test_proje", "doc_date": "2023-06-01", "doc_no": "E-90001",
     "sender_role": "contractor", "doc_type": "yuklenici_yazisi", "evidence_weight": "IDDIA_YUKLENICI",
     "state": "Acik", "review_status": "pending_review", "extraction_confidence": 0.55,
     "subject": "İtiraz", "summary": "..."},
]
for c in cards:
    pdb.upsert_document(conn, c)
print("   3 kart eklendi")

# İlgi zinciri: 3 -> cevaplar -> 2 ; 1 -> (3'ün ilgisinden önceki) 2 zinciri kur
pdb.add_link(conn, "p::3", "S.23-401", "ilgi_zinciri", resolved=False)  # önce çözümsüz
found = pdb.find_by_doc_no(conn, "test_proje", "S.23-401")
print("   doc_no çözümü: S.23-401 ->", found["doc_id"])
if found["doc_id"] != "p::2":
    hata.append("doc_no çözümlemesi hatalı!")
# çözümle: to_ref'i gerçek doc_id'ye bağla (resolved)
import sqlite3
conn.execute("UPDATE links SET to_ref='p::2', resolved=1 WHERE from_doc_id='p::3' AND link_type='ilgi_zinciri'")
conn.commit()
# 2 -> 1 ilgi (geçmişe bağlantı)
pdb.add_link(conn, "p::2", "p::1", "ilgi_zinciri", resolved=True)

zincir = pdb.iter_chain(conn, "p::3")
zincir_ids = [d["doc_id"] for d in zincir]
print("   p::3 ilgi zinciri (yeni->eski):", zincir_ids)
if zincir_ids != ["p::2", "p::1"]:
    hata.append(f"zincir yürütme hatalı: {zincir_ids}")

# Çoklu etiket
pdb.add_tags(conn, "p::1", [
    {"tag_type": "konu", "tag_value": "sure_uzatimi"},
    {"tag_type": "konu", "tag_value": "iksa"},
    {"tag_type": "poz_no", "tag_value": "15.04"},
])
etiketler = conn.execute("SELECT tag_value FROM tags WHERE doc_id='p::1' ORDER BY tag_value").fetchall()
print("   p::1 etiketleri:", [e[0] for e in etiketler])
if len(etiketler) != 3:
    hata.append("etiket ekleme hatalı!")

# Durum makinesi: insan onaylı geçiş + denetim izi
changed = pdb.update_state(conn, "p::1", "Cevaplandi", triggered_by_doc_id="p::2", confirmed_by_human=True)
hist = conn.execute("SELECT * FROM state_history WHERE doc_id='p::1'").fetchall()
print("   durum geçişi:", changed, "| history kayıt:", len(hist),
      "| confirmed_by_human:", hist[0]["confirmed_by_human"] if hist else "-")
if not changed or len(hist) != 1 or hist[0]["confirmed_by_human"] != 1:
    hata.append("durum makinesi/history hatası!")
try:
    pdb.update_state(conn, "p::1", "Boyle_Durum_Yok", confirmed_by_human=True)
    hata.append("geçersiz durum reddedilmedi!")
except ValueError:
    print("   geçersiz durum ValueError ile reddedildi ✔")

kuyruk = pdb.pending_review(conn)
print("   pending_review kuyruğu:", [d["doc_id"] for d in kuyruk])
if [d["doc_id"] for d in kuyruk] != ["p::3"]:
    hata.append("pending_review kuyruğu hatalı!")
conn.close()

# ============================================================
print("\n3) CARD EXTRACTOR: gerçekçi resmi yazı (LLM'siz)")
ornek_yazi = """T.C. İSTANBUL BÜYÜKŞEHİR BELEDİYESİ
BİMLİK EMLAK KONUTLARI DAİRE BAŞKANLIĞI

Sayı: E-84920
Tarih: 02.04.2023
Konu: Süre Uzatımı Talebi Hk.

İlgi: 02.02.2023 tarihli ve 4236 numaralı yazınız.

İdaremizce yürütülen İkitelli-Ataköy Metro Hattı inşaatında
kış şartları nedeniyle işler 210 gün gecikmiştir. EN 50122-1
standardına uygun geçici teslim talep edilir."""
sonuc = extract_identity_card(
    ornek_yazi,
    filename="2023-04-02_yuk_4236_sure_uzatimi.md",
    rel_path="3_yuklenici_talepleri/test/1_yuklenici_yazilari/2023/x.md",
    doc_sha256="ab" * 16,
    project_id="test_proje",
    doc_type="yuklenici_yazisi",
    sender_role_hint="contractor",
    use_llm=False,
)
card = sonuc["card"]
print(f"   doc_date: {card['doc_date']} | doc_no: {card['doc_no']} | ilgi: {card['ilgi_raw'][:40]}")
print(f"   ilgi_refs: {sonuc['ilgi_refs']} | role: {card['sender_role']} | weight: {card['evidence_weight']}")
print(f"   review_status: {card['review_status']} | confidence: {card['extraction_confidence']}")
if card["doc_date"] != "2023-04-02":
    hata.append("kart tarih hatası!")
if card["doc_no"] != "E-84920":
    hata.append(f"kart sayı hatası: {card['doc_no']}")
if "4236" not in " ".join(sonuc["ilgi_refs"]):
    hata.append("İlgi referansı yakalanamadı!")
if card["evidence_weight"] != "IDDIA_YUKLENICI":
    hata.append("kanıt ağırlığı hatalı!")
if card["review_status"] != "auto_approved":
    hata.append("tam bilgi varken pending_review oldu!")
print("   span alanları:", sorted({s['field'] for s in sonuc['spans']}))

# Eksik başlıklı yazı -> pending_review'a düşmeli
eksik_yazi = "Sayın İdare,\n\nTalep ediyoruz.\n\nSaygılarımızla."
sonuc2 = extract_identity_card(
    eksik_yazi, filename="2024-01-01_yazı.md", project_id="test_proje",
    doc_type="yuklenici_yazisi", use_llm=False,
)
print(f"   eksik yazı review_status: {sonuc2['card']['review_status']} (pending_review beklenir)")
if sonuc2["card"]["review_status"] != "pending_review":
    hata.append("eksik kart kuyruğa düşmedi!")

print("\n" + "=" * 60)
if hata:
    print("HATALAR:")
    for h in hata:
        print("  !!", h)
    raise SystemExit(1)
print("ADIM 3 TEMEL TESTLERİ TAMAMI GEÇTİ ✔")
