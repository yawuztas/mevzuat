# -*- coding: utf-8 -*-
"""
Otomatik Mevzuat Senkronizasyon, Dönüştürme ve Sürüm Korumalı Fark (Diff) Motoru
=================================================================================
Katman 1 (data/1_genel_mevzuat_ve_standartlar) için resmi Türkiye Cumhuriyeti
kaynaklarından (mevzuat.gov.tr ve ihale.gov.tr/KİK) güncel mevzuat metinlerini
indirir, yapısal Yasal Markdown'a (## Bölüm / ### Madde + Markdown tabloları)
dönüştürür ve SÜRÜM KORUMALI olarak yönetir.

Temel Güvenlik / Hukuk Kuralları:
1. Hiçbir eski mevzuat sürümü sessizce silinmez; değişiklik tespit edildiğinde
   önceki metin `data/_arsiv/mevzuat_surumleri/<YYYY-MM-DD>/` altına taşınır.
2. Hash karşılaştırması yalnızca normalleştirilmiş GÖVDE metni (`body_sha256`)
   üzerinden yapılır; indirme tarihi/üstbilgi sahte fark üretmez.
3. Madde bazlı fark (diff) raporu `data/raporlar/` altında kaydedilir.
"""

from __future__ import annotations

import difflib
import hashlib
import io
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import docx
import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from utils.text_tr import ascii_fold, tr_lower

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
LAYER1_REL = Path("1_genel_mevzuat_ve_standartlar")
DEFAULT_REGISTRY_NAME = ".mevzuat_registry.json"
DEFAULT_ARCHIVE_REL = Path("_arsiv") / "mevzuat_surumleri"
DEFAULT_REPORT_REL = Path("raporlar")

KIK_NS = {"t": "http://tempuri.org/"}
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
HTTP_TIMEOUT = 45

META_PREFIX = "<!-- MEVZUAT_SYNC_META:"
META_SUFFIX = "-->"


# ==============================================================================
# Eski / Hatalı AI Özet Dosyaları (Kullanıcı talebiyle temizlenecek havuz)
# ==============================================================================
LEGACY_BROKEN_FILES: List[str] = [
    "1_genel_mevzuat_ve_standartlar/1_kanunlar/4734_Kamu_Ihale_Kanunu_Guncel.md",
    "1_genel_mevzuat_ve_standartlar/1_kanunlar/4735_Kamu_Ihale_Sozlesmeleri_Kanunu_Guncel.md",
    "1_genel_mevzuat_ve_standartlar/1_kanunlar/4735_Gecici_5_ve_6_Madde_Ek_Fiyat_Farki_ve_Sure_Uzatimi_Kararnameleri.md",
    "1_genel_mevzuat_ve_standartlar/1_kanunlar/yigs_ve_4735_maddeleri.md",
    "1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/yapim_isleri/Yapim_Isleri_Genel_Sartnamesi_YIGS_Tam_Metin.md",
    "1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/yapim_isleri/Yapim_Isleri_Ihaleleri_Uygulama_Yonetmeligi_Alt_Yuklenici_ve_Is_Artisi.md",
    "1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/yapim_isleri/Yapim_Isleri_Muayene_ve_Kabul_Yonetmeligi.md",
    "1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/Danismanlik_Hizmet_Isleri_Genel_Sartnamesi_ve_Muayene_Kabul.md",
    "1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/Kamu_Ihale_Genel_Tebligi_Yapim_Isleri_ve_Yeni_Fiyat.md",
    "1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/Yapim_Islerinde_Fiyat_Farki_Esaslari_2013_5608.md",
]


@dataclass
class MevzuatSource:
    """Resmi mevzuat kaynağının bildirim tanımı."""
    key: str
    title: str
    rel_path: str  # data/ altında göreli yol
    source_kind: str  # "mevzuat_html" | "kik_item" | "mevzuat_html_with_zip" | "mevzuat_html_with_docx" | "local_pdf_watched"
    mevzuat_tur: Optional[int] = None
    mevzuat_no: Optional[int] = None
    kik_item_id: Optional[int] = None
    kik_dokuman_title_match: Optional[str] = None  # Örn: Item 234 içinde "Yapım İşleri" seçimi
    zip_member_match: Optional[str] = None         # Zip içinden seçilecek asıl docx anahtarı (ascii_fold)
    extra_attachment_url: Optional[str] = None     # Ek .zip/.docx URL (ör. 34909 Tünel Deprem eki)
    procurement_type: str = "ortak"
    notes: str = ""


MEVZUAT_CATALOG: List[MevzuatSource] = [
    # --- 1. KANUNLAR VE GEÇİCİ MADDE KARARNAMELERİ ---
    MevzuatSource(
        key="kanun_4734",
        title="4734 Sayılı Kamu İhale Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/4734_kamu_ihale_kanunu.md",
        source_kind="mevzuat_html",
        mevzuat_tur=1, mevzuat_no=4734,
        notes="Ana ihale mevzuatı",
    ),
    MevzuatSource(
        key="kanun_4735",
        title="4735 Sayılı Kamu İhale Sözleşmeleri Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/4735_kamu_ihale_sozlesmeleri_kanunu.md",
        source_kind="mevzuat_html",
        mevzuat_tur=1, mevzuat_no=4735,
        notes="Sözleşme uygulama, mücbir sebep, fesih ve geçici maddeler",
    ),
    MevzuatSource(
        key="karar_4735_gecici_5",
        title="4735 Sayılı Kanunun Geçici 5 inci Maddesinin Uygulanmasına İlişkin Esaslar (CB Kararı 5203)",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/4735_gecici_5_esaslari_5203.md",
        source_kind="kik_item",
        kik_item_id=188,
        notes="Ek fiyat farkı ve devir/fesih esasları",
    ),
    MevzuatSource(
        key="karar_4735_gecici_6",
        title="4735 Sayılı Kanunun Geçici 6 ncı Maddesinin Uygulanmasına İlişkin Esaslar (CB Kararı 5546)",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/4735_gecici_6_esaslari_5546.md",
        source_kind="kik_item",
        kik_item_id=189,
        notes="Ek fiyat farkı, artırımlı fiyat farkı, süre uzatımı ve fesih",
    ),
    MevzuatSource(
        key="karar_4735_gecici_7",
        title="4735 Sayılı Kanunun Geçici 7 nci Maddesinin Uygulanmasına İlişkin Esaslar (CB Kararı 8089)",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/4735_gecici_7_esaslari_8089.md",
        source_kind="kik_item",
        kik_item_id=196,
        notes="2024 ek fiyat farkı ve süre uzatımı esasları",
    ),
    MevzuatSource(
        key="kanun_4686",
        title="4686 Sayılı Milletlerarası Tahkim Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/4686_milletlerarasi_tahkim_kanunu.pdf",
        source_kind="local_pdf_watched",
        mevzuat_tur=1, mevzuat_no=4686,
        notes="Yerel resmi PDF korunur; mevzuat.gov.tr hash değişikliği izlenir",
    ),
    MevzuatSource(
        key="kanun_6098",
        title="6098 Sayılı Türk Borçlar Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/6098_turk_borclar_kanunu.pdf",
        source_kind="local_pdf_watched",
        mevzuat_tur=1, mevzuat_no=6098,
        notes="Yerel resmi PDF korunur; eser/vekalet sözleşmeleri ve aşırı ifa güçlüğü",
    ),
    MevzuatSource(
        key="kanun_6100",
        title="6100 Sayılı Hukuk Muhakemeleri Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/6100_hukuk_muhakemeleri_kanunu.md",
        source_kind="mevzuat_html",
        mevzuat_tur=1, mevzuat_no=6100,
        notes="İç tahkim (Bölüm 11), ispat, ticari defter, bilirkişi ve ıslah",
    ),
    MevzuatSource(
        key="kanun_5018",
        title="5018 Sayılı Kamu Malî Yönetimi ve Kontrol Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/5018_kamu_mali_yonetimi_ve_kontrol_kanunu.md",
        source_kind="mevzuat_html",
        mevzuat_tur=1, mevzuat_no=5018,
        notes="Ödenek, harcama yetkilisi, gerçekleştirme görevlisi ve kamu zararı",
    ),
    MevzuatSource(
        key="kanun_6085",
        title="6085 Sayılı Sayıştay Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/6085_sayistay_kanunu.md",
        source_kind="mevzuat_html",
        mevzuat_tur=1, mevzuat_no=6085,
        notes="Sayıştay denetimi, ilam, kamu zararı tazmin ve sorumluluk",
    ),
    MevzuatSource(
        key="kanun_6331",
        title="6331 Sayılı İş Sağlığı ve Güvenliği Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/6331_is_sagligi_ve_guvenligi_kanunu.md",
        source_kind="mevzuat_html",
        mevzuat_tur=1, mevzuat_no=6331,
        notes="İşveren/alt işveren İSG yükümlülükleri ve işin durdurulması",
    ),
    MevzuatSource(
        key="kanun_4857",
        title="4857 Sayılı İş Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/4857_is_kanunu.md",
        source_kind="mevzuat_html",
        mevzuat_tur=1, mevzuat_no=4857,
        notes="Asıl işveren-alt işveren müteselsil sorumluluğu ve ücret alacağı kontrolü",
    ),
    MevzuatSource(
        key="kanun_2872",
        title="2872 Sayılı Çevre Kanunu",
        rel_path="1_genel_mevzuat_ve_standartlar/1_kanunlar/2872_cevre_kanunu.md",
        source_kind="mevzuat_html",
        mevzuat_tur=1, mevzuat_no=2872,
        notes="ÇED, hafriyat, gürültü ve idari çevre yaptırımları",
    ),

    # --- 2A. YAPIM İŞLERİ SÖZLEŞME, GENEL ŞARTNAME VE YÖNETMELİKLERİ ---
    MevzuatSource(
        key="yigs_yapim",
        title="Yapım İşleri Genel Şartnamesi (YİGŞ)",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/yapim_isleri/yapim_isleri_genel_sartnamesi_yigs.md",
        source_kind="kik_item",
        kik_item_id=18,
        zip_member_match="genel sartname",
        procurement_type="yapim",
        notes="İş programı, süre uzatımı (m.29), yeni birim fiyat (m.22), hakediş, geçici/kesin kabul",
    ),
    MevzuatSource(
        key="yapim_uygulama_yon",
        title="Yapım İşleri İhaleleri Uygulama Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/yapim_isleri/yapim_isleri_ihaleleri_uygulama_yonetmeligi.md",
        source_kind="kik_item",
        kik_item_id=18,
        zip_member_match="uygulama yonetmeli",
        procurement_type="yapim",
    ),
    MevzuatSource(
        key="yapim_tip_sozlesme",
        title="Yapım İşlerine Ait Tip Sözleşme",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/yapim_isleri/yapim_isleri_tip_sozlesmesi.md",
        source_kind="kik_item",
        kik_item_id=18,
        zip_member_match="sozlesme",
        procurement_type="yapim",
    ),
    MevzuatSource(
        key="yapim_muayene_kabul",
        title="Yapım İşleri Muayene ve Kabul Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/yapim_isleri/yapim_isleri_muayene_ve_kabul_yonetmeligi.md",
        source_kind="mevzuat_html",
        mevzuat_tur=7, mevzuat_no=12920,
        procurement_type="yapim",
    ),

    # --- 2B. DANIŞMANLIK / MÜŞAVİRLİK VE HİZMET YÖNETMELİKLERİ ---
    MevzuatSource(
        key="danismanlik_uygulama_yon",
        title="Danışmanlık Hizmet Alımı İhaleleri Uygulama Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/danismanlik_hizmet_alimi_uygulama_yonetmeligi.md",
        source_kind="kik_item",
        kik_item_id=21,
        zip_member_match="uygulama yonetmeli",
        procurement_type="danismanlik",
    ),
    MevzuatSource(
        key="danismanlik_tip_sozlesme",
        title="Danışmanlık Hizmet Alımlarına Ait Tip Sözleşme",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/danismanlik_hizmet_alimlari_tip_sozlesmesi.md",
        source_kind="kik_item",
        kik_item_id=21,
        zip_member_match="tip sozlesme",
        procurement_type="danismanlik",
    ),
    MevzuatSource(
        key="danismanlik_muayene_kabul",
        title="Danışmanlık Hizmet Alımları Muayene ve Kabul Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/danismanlik_hizmet_alimlari_muayene_ve_kabul_yonetmeligi.md",
        source_kind="mevzuat_html",
        mevzuat_tur=7, mevzuat_no=4712,
        procurement_type="danismanlik",
    ),
    MevzuatSource(
        key="hizmet_uygulama_yon",
        title="Hizmet Alımı İhaleleri Uygulama Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/hizmet_alimi_ihaleleri_uygulama_yonetmeligi.md",
        source_kind="kik_item",
        kik_item_id=20,
        zip_member_match="uygulama yonetmeli",
        procurement_type="danismanlik",
    ),
    MevzuatSource(
        key="hizmet_muayene_kabul",
        title="Hizmet Alımları Muayene ve Kabul Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/hizmet_alimlari_muayene_ve_kabul_yonetmeligi.md",
        source_kind="mevzuat_html",
        mevzuat_tur=7, mevzuat_no=4714,
        procurement_type="danismanlik",
    ),
    MevzuatSource(
        key="fiyat_farki_hizmet_2013_5215",
        title="Hizmet Alımlarında Uygulanacak Fiyat Farkına İlişkin Esaslar (2013/5215 Güncel)",
        rel_path="1_genel_mevzuat_ve_standartlar/2_sozlesme_ve_genel_sartnameler/danismanlik_ve_musavirlik/danismanlik_hizmet_fiyat_farki_esaslari_2013_5215.md",
        source_kind="kik_item",
        kik_item_id=234,
        kik_dokuman_title_match="hizmet alimlarinda",
        procurement_type="danismanlik",
    ),

    # --- 3. TEBLİĞLER, FİYAT FARKI ESASLARI VE TEKNİK/İDARİ YÖNETMELİKLER ---
    MevzuatSource(
        key="kamu_ihale_genel_tebligi",
        title="Kamu İhale Genel Tebliği",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/kamu_ihale_genel_tebligi.md",
        source_kind="kik_item",
        kik_item_id=38,
        zip_member_match="genel_tebligi",
        notes="Aşırı düşük, fiyat farkı uygulama, iş artışı/eksilişi ve revize fiyat tebliğ hükümleri",
    ),
    MevzuatSource(
        key="fiyat_farki_yapim_2013_5217",
        title="Yapım İşlerinde Uygulanacak Fiyat Farkına İlişkin Esaslar (2013/5217 Güncel)",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/yapim_isleri_fiyat_farki_esaslari_2013_5217.md",
        source_kind="kik_item",
        kik_item_id=234,
        kik_dokuman_title_match="yapim islerinde",
        procurement_type="yapim",
        notes="Pn formülü, a, b1..b5 ağırlık oranları, TÜİK alt endeksleri ve revize iş programı kuralları",
    ),
    MevzuatSource(
        key="fiyat_farki_mal_2013_5216",
        title="Mal Alımlarında Uygulanacak Fiyat Farkına İlişkin Esaslar (2013/5216 Güncel)",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/mal_alimlari_fiyat_farki_esaslari_2013_5216.md",
        source_kind="kik_item",
        kik_item_id=234,
        kik_dokuman_title_match="mal alimlarinda",
    ),
    MevzuatSource(
        key="yapim_benzer_is_gruplari",
        title="Yapım İşlerinde Benzer İş Grupları Tebliği",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/yapim_islerinde_benzer_is_gruplari_tebligi.md",
        source_kind="kik_item",
        kik_item_id=37,
        procurement_type="yapim",
    ),
    MevzuatSource(
        key="ihalelere_yonelik_basvurular_yon",
        title="İhalelere Yönelik Başvurular Hakkında Yönetmelik",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/ihalelere_yonelik_basvurular_yonetmeligi.md",
        source_kind="mevzuat_html",
        mevzuat_tur=7, mevzuat_no=12766,
    ),
    MevzuatSource(
        key="mal_muayene_kabul_yon",
        title="Mal Alımları Denetim Muayene ve Kabul İşlemlerine Dair Yönetmelik",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/mal_alimlari_muayene_kabul_yonetmeligi.md",
        source_kind="mevzuat_html",
        mevzuat_tur=7, mevzuat_no=4713,
    ),
    MevzuatSource(
        key="mahalli_idareler_harcama_yon",
        title="Mahalli İdareler Harcama Belgeleri Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/mahalli_idareler_harcama_belgeleri_yonetmeligi.md",
        source_kind="mevzuat_html",
        mevzuat_tur=7, mevzuat_no=11509,
        notes="Büyükşehir/belediye hakediş ve kesin hesap eki zorunlu belgeler",
    ),
    MevzuatSource(
        key="binalarin_yangindan_korunmasi_yon",
        title="Binaların Yangından Korunması Hakkında Yönetmelik (2007/12937)",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/binalarin_yangindan_korunmasi_yonetmeligi_2007_12937.md",
        source_kind="mevzuat_html",
        mevzuat_tur=21, mevzuat_no=200712937,
        notes="Yeraltı/istasyon duman tahliye, kaçış yolları ve yangın söndürme yükümlülükleri",
    ),
    MevzuatSource(
        key="yapi_isleri_isg_yon",
        title="Yapı İşlerinde İş Sağlığı ve Güvenliği Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/yapi_isleri_is_sagligi_ve_guvenligi_yonetmeligi_18928.md",
        source_kind="mevzuat_html",
        mevzuat_tur=7, mevzuat_no=18928,
        notes="Tünel/kazı/iskele İSG teknik gerekleri ve sağlık-güvenlik planı",
    ),
    MevzuatSource(
        key="hafriyat_atiklari_yon",
        title="Hafriyat Toprağı, İnşaat ve Yıkıntı Atıklarının Kontrolü Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/hafriyat_topragi_insaat_ve_yikinti_atiklari_yonetmeligi_5401.md",
        source_kind="mevzuat_html",
        mevzuat_tur=7, mevzuat_no=5401,
        notes="TBM/kazı hafriyat taşıma izin, döküm sahası ve belediye kuralları",
    ),
    MevzuatSource(
        key="tuneller_deprem_yon",
        title="Deprem Etkisi Altında Karayolu ve Demiryolu Tünelleri ve Diğer Zemin Yapılarının Tasarımı Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/tuneller_deprem_tasarimi_yonetmeligi_34909.md",
        source_kind="mevzuat_html_with_zip",
        mevzuat_tur=7, mevzuat_no=34909,
        extra_attachment_url="https://www.mevzuat.gov.tr/MevzuatMetin/yonetmelik/7.5.34909-Ek.zip",
        notes="Metro ve demiryolu tünel/istasyon sismik tasarım yönetmeliği ve teknik ekleri",
    ),
    MevzuatSource(
        key="yalitimli_kopru_deprem_yon",
        title="Deprem Etkisi Altında Yalıtımlı ve Sönümleyicili Köprüler ve Viyadüklerin Tasarımı Yönetmeliği",
        rel_path="1_genel_mevzuat_ve_standartlar/3_tebligler_ve_kararnameler/yalitimli_kopruler_deprem_yonetmeligi_34912.md",
        source_kind="mevzuat_html_with_docx",
        mevzuat_tur=7, mevzuat_no=34912,
        extra_attachment_url="https://www.mevzuat.gov.tr/MevzuatMetin/yonetmelik/7.5.34912-EK.docx",
        notes="Viyadük/köprü deprem yalıtım tasarımı",
    ),
]


# ==============================================================================
# Yardımcı İşlemler & Markdown Dönüştürücüler
# ==============================================================================
_ARTICLE_HEADING_RE = re.compile(
    r"^(?:MADDE|Madde|EK\s+MADDE|Ek\s+Madde|GEÇİCİ\s+MADDE|Geçici\s+Madde)\s+\d+",
    re.UNICODE,
)
_SECTION_H1_RE = re.compile(r"^[A-ZÇĞİÖŞÜ0-9İ]+\s+KISIM\b", re.UNICODE)
_SECTION_H2_RE = re.compile(r"^[A-ZÇĞİÖŞÜ0-9İ]+\s+BÖLÜM\b", re.UNICODE)


def _clean_whitespace(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _promote_legal_heading(line: str, style_name: str = "") -> str:
    """Türkçe mevzuat başlık/madde satırlarını chunker uyumlu Markdown başlığına dönüştürür."""
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith("#"):
        return stripped
    # Zaten çok uzun bir gövde cümlesiyse (örneğin madde içi atıf), başlık yapma
    if len(stripped) > 180 and not _ARTICLE_HEADING_RE.match(stripped):
        return stripped
    if _ARTICLE_HEADING_RE.match(stripped):
        return f"### {stripped}"
    if _SECTION_H1_RE.match(stripped) and len(stripped) < 120:
        return f"# {stripped}"
    if _SECTION_H2_RE.match(stripped) and len(stripped) < 120:
        return f"## {stripped}"
    st = ascii_fold(style_name or "")
    if "heading 1" in st or "baslik 1" in st or "toc 1" in st:
        return f"# {stripped}"
    if "heading 2" in st or "baslik 2" in st or "toc 2" in st:
        return f"## {stripped}"
    if "heading 3" in st or "baslik 3" in st or "toc 3" in st:
        return f"### {stripped}"
    return stripped


def _table_rows_to_markdown(rows: List[List[str]]) -> str:
    """2 boyutlu hücre matrisini temiz Markdown tablosuna dönüştürür."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    if width == 0:
        return ""
    norm_rows = []
    for r in rows:
        padded = [(c or "").replace("|", "\\|").replace("\n", " ").strip() for c in r]
        while len(padded) < width:
            padded.append("")
        norm_rows.append(padded)
    # Tamamen boş satırları at
    norm_rows = [r for r in norm_rows if any(r)]
    if not norm_rows:
        return ""
    lines = [
        "| " + " | ".join(norm_rows[0]) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    for r in norm_rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _docx_table_to_markdown(tbl: docx.table.Table) -> str:
    rows: List[List[str]] = []
    for row in tbl.rows:
        rows.append([_clean_whitespace(cell.text) for cell in row.cells])
    return _table_rows_to_markdown(rows)


def _html_table_to_markdown(tbl_tag: Tag) -> str:
    rows: List[List[str]] = []
    for tr in tbl_tag.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False) or tr.find_all(["th", "td"])
        if cells:
            rows.append([_clean_whitespace(c.get_text(" ", strip=True)) for c in cells])
    return _table_rows_to_markdown(rows)


def docx_bytes_to_body_markdown(data: bytes) -> str:
    """DOCX baytlarını paragraf ve tablo sırasını bozmadan yapısal Markdown gövdeye çevirir."""
    doc = docx.Document(io.BytesIO(data))
    out_blocks: List[str] = []
    para_map = {p._element: p for p in doc.paragraphs}
    tbl_map = {t._element: t for t in doc.tables}

    for child in doc.element.body.iterchildren():
        if child in para_map:
            p = para_map[child]
            txt = _clean_whitespace(p.text)
            if txt:
                out_blocks.append(_promote_legal_heading(txt, p.style.name if p.style else ""))
        elif child in tbl_map:
            md_tbl = _docx_table_to_markdown(tbl_map[child])
            if md_tbl:
                out_blocks.append(md_tbl)
    body = "\n\n".join(out_blocks)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def html_text_to_body_markdown(html: str) -> str:
    """mevzuat.gov.tr HTML'ini tablo ve madde başlıklarını koruyarak yapısal Markdown gövdeye çevirir."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "head", "nav"]):
        tag.decompose()

    root = soup.body or soup
    out_blocks: List[str] = []

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                t = _clean_whitespace(str(child))
                if t:
                    out_blocks.append(_promote_legal_heading(t))
                continue
            if not isinstance(child, Tag):
                continue
            name = (child.name or "").lower()
            if name == "table":
                md_tbl = _html_table_to_markdown(child)
                if md_tbl:
                    out_blocks.append(md_tbl)
            elif name in {"p", "h1", "h2", "h3", "h4", "h5", "li", "blockquote", "pre"}:
                # İçinde iç içe tablo varsa walk ile in
                if child.find("table"):
                    walk(child)
                else:
                    t = _clean_whitespace(child.get_text(" ", strip=True))
                    if t:
                        if name == "h1":
                            out_blocks.append(f"# {t}" if not t.startswith("#") else t)
                        elif name == "h2":
                            out_blocks.append(f"## {t}" if not t.startswith("#") else t)
                        elif name in {"h3", "h4"}:
                            out_blocks.append(f"### {t}" if not t.startswith("#") else t)
                        else:
                            out_blocks.append(_promote_legal_heading(t))
            else:
                walk(child)

    walk(root)
    body = "\n\n".join(out_blocks)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def pdf_bytes_to_body_markdown(data: bytes) -> str:
    """PDF baytlarını sayfa belirteçli Yasal Markdown'a dönüştürür (taranmış sayfada RapidOCR destekli)."""
    doc = fitz.open(stream=data, filetype="pdf")
    pages: List[str] = []
    ocr = None
    for idx, page in enumerate(doc, start=1):
        raw = (page.get_text("text") or "").strip()
        if len(raw) < 350:
            if ocr is None:
                from utils.document_parser import get_rapid_ocr
                ocr = get_rapid_ocr()
            if ocr is not None:
                pix = page.get_pixmap(dpi=200)
                res = ocr(pix.tobytes("png"))
                txts = getattr(res, "txts", None)
                if not txts and isinstance(res, tuple) and res and res[0]:
                    txts = [item[1] for item in res[0] if len(item) >= 2]
                if txts:
                    raw = "\n".join(str(t) for t in txts)
        lines = [_promote_legal_heading(_clean_whitespace(ln)) for ln in raw.splitlines()]
        clean_lines = [ln for ln in lines if ln]
        if clean_lines:
            pages.append(f"--- Sayfa {idx} ---\n\n" + "\n\n".join(clean_lines))
    return "\n\n".join(pages).strip()


def normalize_for_hash(body_markdown: str) -> str:
    """Gereksiz boşluk değişimlerinden etkilenmeyen kararlı özet metni üretir."""
    normalized = body_markdown.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


def compute_sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


def compute_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wrap_with_sync_header(meta: Dict[str, Any], title: str, body_markdown: str) -> str:
    header_json = json.dumps(meta, ensure_ascii=False, sort_keys=True)
    parts = [
        f"{META_PREFIX} {header_json} {META_SUFFIX}",
        f"# {title}",
        body_markdown.strip(),
    ]
    return "\n\n".join(parts) + "\n"


def strip_sync_header(full_markdown: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Dosya başındaki sync metadata yorumunu ayırır; gövdeyi saf haliyle döndürür."""
    text = full_markdown.replace("\r\n", "\n")
    meta: Optional[Dict[str, Any]] = None
    lines = text.splitlines()
    idx = 0
    if lines and lines[0].startswith(META_PREFIX) and META_SUFFIX in lines[0]:
        raw_json = lines[0][len(META_PREFIX): lines[0].index(META_SUFFIX)].strip()
        try:
            meta = json.loads(raw_json)
        except json.JSONDecodeError:
            meta = None
        idx = 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        # wrap_with_sync_header tarafından eklenen üst "# <Title>" satırını at
        if meta and idx < len(lines) and lines[idx].strip() == f"# {meta.get('title', '')}":
            idx += 1
            while idx < len(lines) and not lines[idx].strip():
                idx += 1
    body = "\n".join(lines[idx:]).strip()
    return meta, body


# ==============================================================================
# Madde Bazlı Fark (Article-Level Diff) Hesaplama
# ==============================================================================
_ARTICLE_SPLIT_RE = re.compile(
    r"(?m)^(?=#{1,4}\s+(?:MADDE|Madde|EK\s+MADDE|Ek\s+Madde|GEÇİCİ\s+MADDE|Geçici\s+Madde|BÖLÜM)\b)",
)


def split_markdown_articles(body_markdown: str) -> Dict[str, str]:
    """Gövdeyi madde/bölüm başlıklarına göre sıralı sözlüğe böler."""
    sections: Dict[str, str] = {}
    parts = _ARTICLE_SPLIT_RE.split(body_markdown.strip())
    for i, part in enumerate(parts):
        cleaned = part.strip()
        if not cleaned:
            continue
        first_line = cleaned.splitlines()[0].lstrip("#").strip()
        key = first_line[:100] if (i > 0 or first_line.lower().startswith(("madde", "ek madde", "geçici madde"))) else "Başlangıç / Genel Hükümler"
        # Aynı başlık nadiren tekrarlanırsa çakışma olmasın
        if key in sections:
            key = f"{key} (#{i})"
        sections[key] = cleaned
    return sections


def compute_article_diff(old_body: str, new_body: str, max_snippets: int = 12) -> Dict[str, Any]:
    """Eski ve yeni mevzuat gövdesi arasındaki madde bazlı farkları çıkarır."""
    old_arts = split_markdown_articles(old_body)
    new_arts = split_markdown_articles(new_body)

    old_keys = set(old_arts.keys())
    new_keys = set(new_arts.keys())

    added = [k for k in new_arts if k not in old_keys]
    removed = [k for k in old_arts if k not in new_keys]
    modified: List[Dict[str, Any]] = []

    for k in new_arts:
        if k in old_arts and normalize_for_hash(old_arts[k]) != normalize_for_hash(new_arts[k]):
            snippet = ""
            if len(modified) < max_snippets:
                diff_lines = list(
                    difflib.unified_diff(
                        old_arts[k].splitlines(),
                        new_arts[k].splitlines(),
                        fromfile=f"eski/{k}",
                        tofile=f"yeni/{k}",
                        lineterm="",
                        n=2,
                    )
                )
                snippet = "\n".join(diff_lines[:30])
            modified.append({"article": k, "diff_snippet": snippet})

    return {
        "added_articles": added,
        "removed_articles": removed,
        "modified_articles": modified,
        "total_changes": len(added) + len(removed) + len(modified),
    }


# ==============================================================================
# Uzak Resmi Kaynak Okuma Yardımcıları
# ==============================================================================
def _decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode("cp437", errors="ignore")
    try:
        return raw.decode("cp857")
    except Exception:
        return info.filename


def fetch_mevzuat_html_body(tur: int, no: int) -> Tuple[str, str]:
    url = (
        f"https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe"
        f"?MevzuatTur={tur}&MevzuatNo={no}&MevzuatTertip=5"
    )
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return html_text_to_body_markdown(resp.text), url


def fetch_kik_item_metadata(item_id: int) -> List[Dict[str, str]]:
    url = f"https://www.ihale.gov.tr/MevzuatData.asmx/TekItemGetir?ItemID={item_id}"
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    items: List[Dict[str, str]] = []
    for d in root.findall(".//t:Dokuman", KIK_NS):
        items.append({
            "dokuman_id": (d.findtext("t:ID", "", KIK_NS) or "").strip(),
            "baslik": (d.findtext("t:DokumanBaslik", "", KIK_NS) or "").strip(),
            "rg_tarih": (d.findtext("t:RGTarih", "", KIK_NS) or "").strip(),
            "rg_sayi": (d.findtext("t:RGSayi", "", KIK_NS) or "").strip(),
            "doc_type": (d.findtext("t:DokumanType", "", KIK_NS) or "").strip().lower(),
        })
    return items


def select_kik_dokuman(docs: List[Dict[str, str]], title_match: Optional[str]) -> Dict[str, str]:
    if not docs:
        raise ValueError("KİK TekItemGetir boş doküman listesi döndürdü.")
    if not title_match:
        return docs[0]
    target = ascii_fold(title_match)
    for d in docs:
        if target in ascii_fold(d["baslik"]):
            return d
    raise ValueError(f"KİK içinde '{title_match}' ile eşleşen doküman bulunamadı.")


def fetch_kik_document_body(src: MevzuatSource, dok: Dict[str, str]) -> Tuple[str, str]:
    url = f"https://www.ihale.gov.tr/DokumanDownload.aspx?DokumanID={dok['dokuman_id']}"
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    raw_bytes = resp.content
    dtype = dok["doc_type"]

    if dtype == ".docx":
        return docx_bytes_to_body_markdown(raw_bytes), url
    if dtype == ".pdf":
        return pdf_bytes_to_body_markdown(raw_bytes), url
    if dtype == ".zip":
        target_fold = ascii_fold(src.zip_member_match or "")
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            docx_members = [
                (info, _decode_zip_member_name(info))
                for info in zf.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".docx")
            ]
            if not docx_members:
                raise ValueError(f"{src.key}: ZIP içinde .docx üyesi bulunamadı.")
            chosen = None
            if target_fold:
                for info, decoded in docx_members:
                    fname_fold = ascii_fold(Path(decoded).name)
                    if target_fold in fname_fold and not fname_fold.startswith("mulga_"):
                        chosen = (info, decoded)
                        break
            if chosen is None:
                chosen = docx_members[0]
            return docx_bytes_to_body_markdown(zf.read(chosen[0].filename)), url
    raise ValueError(f"{src.key}: Desteklenmeyen KİK doküman uzantısı: {dtype}")


def fetch_extra_attachment_markdown(url: str) -> str:
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT * 2)
    resp.raise_for_status()
    if url.lower().endswith(".docx"):
        return docx_bytes_to_body_markdown(resp.content)
    if url.lower().endswith(".zip"):
        parts: List[str] = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            members = sorted(
                [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith(".docx")],
                key=lambda x: _decode_zip_member_name(x).lower(),
            )
            # Bazı zip arşivlerinde "Ek-1 (2).docx" ve "EK-1.docx" gibi dosyalar bulunabilir; tümünü sırayla ekle
            for info in members:
                name = _decode_zip_member_name(info)
                md = docx_bytes_to_body_markdown(zf.read(info.filename))
                if md:
                    parts.append(f"## Teknik Ek: {Path(name).stem}\n\n{md}")
        return "\n\n".join(parts)
    raise ValueError(f"Desteklenmeyen ek URL türü: {url}")


# ==============================================================================
# Ana Senkronizasyon ve Sürüm Koruma Motoru
# ==============================================================================
class MevzuatSyncEngine:
    def __init__(
        self,
        data_dir: Optional[Path] = None,
        catalog: Optional[List[MevzuatSource]] = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.catalog = catalog if catalog is not None else MEVZUAT_CATALOG
        self.registry_path = self.data_dir / LAYER1_REL / DEFAULT_REGISTRY_NAME
        self.archive_root = self.data_dir / DEFAULT_ARCHIVE_REL
        self.report_dir = self.data_dir / DEFAULT_REPORT_REL

    def load_registry(self) -> Dict[str, Any]:
        if self.registry_path.exists():
            try:
                return json.loads(self.registry_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"updated_at": None, "sources": {}}

    def save_registry(self, reg: Dict[str, Any]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        reg["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.registry_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")

    def purge_legacy_broken_files(self, rel_list: Optional[List[str]] = None) -> List[str]:
        targets = rel_list if rel_list is not None else LEGACY_BROKEN_FILES
        deleted: List[str] = []
        for rel in targets:
            p = self.data_dir / rel
            if p.exists():
                p.unlink()
                deleted.append(rel)
        return deleted

    def _archive_file(self, abs_path: Path, rel_path: str, stamp: str) -> Path:
        dest = self.archive_root / stamp / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(abs_path, dest)
        return dest

    def _fetch_source(self, src: MevzuatSource) -> Dict[str, Any]:
        """Uzak kaynaktan saf gövde ve sürüm bilgisini indirir."""
        if src.source_kind == "mevzuat_html":
            body, url = fetch_mevzuat_html_body(src.mevzuat_tur, src.mevzuat_no)  # type: ignore[arg-type]
            return {
                "body": body,
                "source_url": url,
                "version_tag": f"mevzuat:{src.mevzuat_tur}.{src.mevzuat_no}",
                "rg_tarih": "",
                "rg_sayi": "",
            }
        if src.source_kind in ("mevzuat_html_with_zip", "mevzuat_html_with_docx"):
            html_body, url = fetch_mevzuat_html_body(src.mevzuat_tur, src.mevzuat_no)  # type: ignore[arg-type]
            att_body = fetch_extra_attachment_markdown(src.extra_attachment_url or "")
            combined = f"{html_body}\n\n{att_body}".strip()
            return {
                "body": combined,
                "source_url": url,
                "version_tag": f"mevzuat:{src.mevzuat_tur}.{src.mevzuat_no}+ek",
                "rg_tarih": "",
                "rg_sayi": "",
            }
        if src.source_kind == "kik_item":
            docs = fetch_kik_item_metadata(src.kik_item_id)  # type: ignore[arg-type]
            chosen = select_kik_dokuman(docs, src.kik_dokuman_title_match)
            body, url = fetch_kik_document_body(src, chosen)
            return {
                "body": body,
                "source_url": url,
                "version_tag": f"kik:{chosen['dokuman_id']}|RG:{chosen['rg_tarih']}/{chosen['rg_sayi']}",
                "kik_dokuman_id": chosen["dokuman_id"],
                "kik_baslik": chosen["baslik"],
                "rg_tarih": chosen["rg_tarih"],
                "rg_sayi": chosen["rg_sayi"],
            }
        if src.source_kind == "local_pdf_watched":
            # Yerel PDF dosyasını koru, ama mevzuat.gov.tr HTML özet hash'ini izle
            html_body, url = fetch_mevzuat_html_body(src.mevzuat_tur, src.mevzuat_no)  # type: ignore[arg-type]
            return {
                "body": None,
                "remote_watch_sha256": compute_sha256_text(html_body),
                "source_url": url,
                "version_tag": f"mevzuat:{src.mevzuat_tur}.{src.mevzuat_no}",
                "rg_tarih": "",
                "rg_sayi": "",
            }
        raise ValueError(f"Bilinmeyen source_kind: {src.source_kind}")

    def check_updates(self, deep: bool = False) -> Dict[str, Any]:
        """
        Dosyaları değiştirmeden güncelleme kontrolü yapar.
        - kik_item için hızlı XML sürüm ID + RG Tarih kontrolü yapar.
        - deep=True ise mevzuat_html kaynaklarını da indirip body_sha256 kıyaslar.
        """
        reg = self.load_registry()
        reg_sources = reg.get("sources", {})
        results: List[Dict[str, Any]] = []

        for src in self.catalog:
            target = self.data_dir / src.rel_path
            rec = reg_sources.get(src.key, {})
            if not target.exists():
                results.append({"key": src.key, "status": "missing_local", "title": src.title})
                continue

            if src.source_kind == "kik_item":
                try:
                    docs = fetch_kik_item_metadata(src.kik_item_id)  # type: ignore[arg-type]
                    chosen = select_kik_dokuman(docs, src.kik_dokuman_title_match)
                    old_did = str(rec.get("kik_dokuman_id", ""))
                    new_did = str(chosen["dokuman_id"])
                    if old_did and old_did == new_did:
                        results.append({"key": src.key, "status": "up_to_date", "version_tag": rec.get("version_tag")})
                    else:
                        results.append({
                            "key": src.key,
                            "status": "update_available",
                            "old_version": rec.get("version_tag"),
                            "new_version": f"kik:{new_did}|RG:{chosen['rg_tarih']}/{chosen['rg_sayi']}",
                            "baslik": chosen["baslik"],
                        })
                except Exception as exc:
                    results.append({"key": src.key, "status": "error", "error": str(exc)})
            elif deep:
                try:
                    fetched = self._fetch_source(src)
                    if src.source_kind == "local_pdf_watched":
                        old_watch = rec.get("remote_watch_sha256", "")
                        new_watch = fetched["remote_watch_sha256"]
                        st = "up_to_date" if (old_watch and old_watch == new_watch) else ("update_available" if old_watch else "unregistered")
                        results.append({"key": src.key, "status": st, "title": src.title})
                    else:
                        new_hash = compute_sha256_text(fetched["body"])
                        old_hash = rec.get("body_sha256", "")
                        if not old_hash and target.exists():
                            _, old_body = strip_sync_header(target.read_text(encoding="utf-8", errors="ignore"))
                            old_hash = compute_sha256_text(old_body)
                        st = "up_to_date" if old_hash == new_hash else "update_available"
                        results.append({"key": src.key, "status": st, "title": src.title})
                except Exception as exc:
                    results.append({"key": src.key, "status": "error", "error": str(exc)})
            else:
                results.append({"key": src.key, "status": "registered_ok" if rec else "unregistered", "title": src.title})

        return {
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "deep": deep,
            "items": results,
        }

    def apply_local_update(
        self,
        src: MevzuatSource,
        fetched: Dict[str, Any],
        reg_sources: Dict[str, Any],
        stamp: str,
    ) -> Dict[str, Any]:
        """Tek bir mevzuat kaydını sürüm korumalı şekilde diske yazar ve diff üretir."""
        target = self.data_dir / src.rel_path
        target.parent.mkdir(parents=True, exist_ok=True)

        if src.source_kind == "local_pdf_watched":
            if not target.exists():
                return {"key": src.key, "status": "missing_pdf", "rel_path": src.rel_path}
            pdf_hash = compute_sha256_bytes(target.read_bytes())
            old_rec = reg_sources.get(src.key, {})
            old_watch = old_rec.get("remote_watch_sha256")
            new_watch = fetched["remote_watch_sha256"]
            reg_sources[src.key] = {
                "title": src.title,
                "rel_path": src.rel_path,
                "source_kind": src.source_kind,
                "source_url": fetched["source_url"],
                "file_sha256": pdf_hash,
                "remote_watch_sha256": new_watch,
                "last_checked_at": datetime.now().isoformat(timespec="seconds"),
            }
            if old_watch and old_watch != new_watch:
                return {
                    "key": src.key,
                    "title": src.title,
                    "rel_path": src.rel_path,
                    "status": "remote_html_changed_review_pdf",
                    "note": "mevzuat.gov.tr HTML metni değişti; yerel PDF gözden geçirilmeli.",
                }
            return {"key": src.key, "title": src.title, "rel_path": src.rel_path, "status": "unchanged"}

        new_body = fetched["body"]
        new_sha = compute_sha256_text(new_body)

        if target.exists():
            _, old_body = strip_sync_header(target.read_text(encoding="utf-8", errors="ignore"))
            old_sha = compute_sha256_text(old_body)
            if old_sha == new_sha:
                # İçerik birebir aynı — dosyaya dokunma, yalnız kontrol zamanını güncelle
                if src.key not in reg_sources:
                    reg_sources[src.key] = {}
                reg_sources[src.key].update({
                    "title": src.title,
                    "rel_path": src.rel_path,
                    "source_kind": src.source_kind,
                    "source_url": fetched["source_url"],
                    "version_tag": fetched["version_tag"],
                    "kik_dokuman_id": fetched.get("kik_dokuman_id", ""),
                    "rg_tarih": fetched.get("rg_tarih", ""),
                    "rg_sayi": fetched.get("rg_sayi", ""),
                    "body_sha256": new_sha,
                    "last_checked_at": datetime.now().isoformat(timespec="seconds"),
                })
                return {"key": src.key, "title": src.title, "rel_path": src.rel_path, "status": "unchanged"}

            # İçerik DEĞİŞMİŞ -> eski sürümü koruyarak arşivle + madde diff çıkar!
            archive_path = self._archive_file(target, src.rel_path, stamp)
            diff_info = compute_article_diff(old_body, new_body)
            status = "updated"
        else:
            archive_path = None
            diff_info = None
            status = "added"

        meta = {
            "key": src.key,
            "title": src.title,
            "source_url": fetched["source_url"],
            "version_tag": fetched["version_tag"],
            "rg_tarih": fetched.get("rg_tarih", ""),
            "rg_sayi": fetched.get("rg_sayi", ""),
            "body_sha256": new_sha,
            "synced_at": datetime.now().isoformat(timespec="seconds"),
        }
        full_md = wrap_with_sync_header(meta, src.title, new_body)
        target.write_text(full_md, encoding="utf-8")

        reg_sources[src.key] = {
            **meta,
            "rel_path": src.rel_path,
            "source_kind": src.source_kind,
            "kik_dokuman_id": fetched.get("kik_dokuman_id", ""),
            "char_count": len(new_body),
            "last_checked_at": meta["synced_at"],
        }

        out: Dict[str, Any] = {
            "key": src.key,
            "title": src.title,
            "rel_path": src.rel_path,
            "status": status,
            "char_count": len(new_body),
            "version_tag": fetched["version_tag"],
        }
        if archive_path is not None:
            out["archive_path"] = str(archive_path)
        if diff_info is not None:
            out["diff"] = diff_info
        return out

    def write_sync_report(self, outcomes: List[Dict[str, Any]], purged: List[str], stamp: str) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.report_dir / f"mevzuat_guncelleme_{stamp}.md"
        counts: Dict[str, int] = {}
        for o in outcomes:
            counts[o["status"]] = counts.get(o["status"], 0) + 1

        lines = [
            f"# Katman 1 Mevzuat Senkronizasyon ve Değişiklik Raporu ({stamp})",
            "",
            f"- Tarih: `{datetime.now().isoformat(timespec='seconds')}`",
            f"- Toplam Kaynak: `{len(outcomes)}`",
            f"- Özet: " + ", ".join(f"`{k}={v}`" for k, v in sorted(counts.items())),
            "",
        ]
        if purged:
            lines.append("## Temizlenen Eski / Hatalı Özet Dosyalar")
            for p in purged:
                lines.append(f"- `{p}`")
            lines.append("")

        updated_items = [o for o in outcomes if o["status"] == "updated"]
        if updated_items:
            lines.append("## Güncellenen ve Arşivlenen Mevzuatlar (Madde Farkları)")
            for o in updated_items:
                d = o.get("diff", {})
                lines.append(f"### {o['title']} (`{o['key']}`)")
                lines.append(f"- Arşivlenen Eski Sürüm: `{o.get('archive_path', '-')}`")
                lines.append(
                    f"- Değişiklik Özeti: Eklenen={len(d.get('added_articles', []))}, "
                    f"Kaldırılan={len(d.get('removed_articles', []))}, "
                    f"Değişen={len(d.get('modified_articles', []))}"
                )
                for a in d.get("added_articles", [])[:15]:
                    lines.append(f"  - `[EKLENDİ]` {a}")
                for r in d.get("removed_articles", [])[:15]:
                    lines.append(f"  - `[KALDIRILDI]` {r}")
                for m in d.get("modified_articles", [])[:10]:
                    lines.append(f"  - `[DEĞİŞTİ]` {m['article']}")
                    if m.get("diff_snippet"):
                        lines.append("```diff")
                        lines.append(m["diff_snippet"])
                        lines.append("```")
                lines.append("")

        lines.append("## Tüm Kaynaklar Durum Tablosu")
        lines.append("| Key | Başlık | Durum | Sürüm / Karakter |")
        lines.append("|---|---|---|---|")
        for o in outcomes:
            extra = o.get("error") or o.get("version_tag") or o.get("note") or ""
            if o.get("char_count"):
                extra = f"{extra} ({o['char_count']:,} krk)"
            lines.append(f"| `{o['key']}` | {o.get('title', '')} | `{o['status']}` | {extra} |")

        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path

    def sync_all(self, purge_legacy: bool = False, keys: Optional[List[str]] = None) -> Dict[str, Any]:
        reg = self.load_registry()
        reg_sources = reg.setdefault("sources", {})
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        purged = self.purge_legacy_broken_files() if purge_legacy else []

        selected = [s for s in self.catalog if not keys or s.key in keys]
        outcomes: List[Dict[str, Any]] = []
        for src in selected:
            try:
                fetched = self._fetch_source(src)
                res = self.apply_local_update(src, fetched, reg_sources, stamp)
                outcomes.append(res)
            except Exception as exc:
                outcomes.append({
                    "key": src.key,
                    "title": src.title,
                    "rel_path": src.rel_path,
                    "status": "error",
                    "error": str(exc),
                })

        self.save_registry(reg)
        report_path = self.write_sync_report(outcomes, purged, stamp)
        return {
            "purged": purged,
            "outcomes": outcomes,
            "registry_path": str(self.registry_path),
            "report_path": str(report_path),
        }
