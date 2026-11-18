# -*- coding: utf-8 -*-
"""
Katman 1 Resmi Mevzuat Senkronizasyon ve Otomatik Güncelleme Kontrol CLI'si
==========================================================================
Kullanım:
  python -X utf8 scripts/sync_mevzuat.py --check
  python -X utf8 scripts/sync_mevzuat.py --check --deep
  python -X utf8 scripts/sync_mevzuat.py --sync --purge-legacy --ingest
  python -X utf8 scripts/sync_mevzuat.py --sync --keys fiyat_farki_yapim_2013_5217 yigs_yapim
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.mevzuat_sync import MevzuatSyncEngine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Katman 1 Resmi Mevzuat Senkronizasyon Motoru")
    parser.add_argument("--check", action="store_true", help="Değişiklik yapmadan resmi kaynaklarda güncelleme kontrolü yapar.")
    parser.add_argument("--deep", action="store_true", help="--check ile tüm mevzuat.gov.tr metin hash'lerini de canlı kontrol eder.")
    parser.add_argument("--sync", action="store_true", help="Güncel mevzuatı indirir, eski sürümü arşivler ve fark raporu üretir.")
    parser.add_argument("--purge-legacy", action="store_true", help="Eski/eksik/hatalı AI özet .md dosyalarını temizler.")
    parser.add_argument("--keys", nargs="*", help="Sadece belirtilen katalog anahtarlarını senkronize eder.")
    parser.add_argument("--ingest", action="store_true", help="Senkronizasyon sonrası artımlı `1_ingest.py` çalıştırır.")
    parser.add_argument("--json", action="store_true", help="Çıktıyı JSON olarak yazar.")
    args = parser.parse_args()

    engine = MevzuatSyncEngine()

    if not args.check and not args.sync and not args.purge_legacy:
        args.check = True

    if args.check:
        res = engine.check_updates(deep=args.deep)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"Kontrol zamanı: {res['checked_at']} (deep={res['deep']})")
            for item in res["items"]:
                st = item["status"]
                if st == "update_available":
                    print(f"  [GÜNCELLEME VAR] {item['key']}: {item.get('old_version')} -> {item.get('new_version', '')}")
                elif st == "error":
                    print(f"  [HATA]           {item['key']}: {item.get('error')}")
                elif st == "missing_local":
                    print(f"  [EKSİK]          {item['key']}: {item.get('title')}")
                else:
                    print(f"  [OK:{st:14s}] {item['key']}")
        updates = [i for i in res["items"] if i["status"] in ("update_available", "missing_local")]
        errors = [i for i in res["items"] if i["status"] == "error"]
        if not args.sync:
            return 2 if errors else 0

    if args.sync or args.purge_legacy:
        if args.sync:
            out = engine.sync_all(purge_legacy=args.purge_legacy, keys=args.keys)
        else:
            purged = engine.purge_legacy_broken_files()
            out = {"purged": purged, "outcomes": [], "report_path": None}

        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            if out["purged"]:
                print(f"Temizlenen eski/hatalı dosya sayısı: {len(out['purged'])}")
            for o in out["outcomes"]:
                st = o["status"]
                if st == "error":
                    print(f"  [HATA]    {o['key']}: {o.get('error')}")
                elif st == "updated":
                    d = o.get("diff", {})
                    print(
                        f"  [GÜNCEL]  {o['key']}: +{len(d.get('added_articles', []))} "
                        f"-{len(d.get('removed_articles', []))} ~{len(d.get('modified_articles', []))} "
                        f"(arşiv: {o.get('archive_path')})"
                    )
                elif st == "added":
                    print(f"  [EKLENDİ] {o['key']}: {o.get('char_count', 0):,} krk -> {o['rel_path']}")
                else:
                    print(f"  [{st.upper():8s}] {o['key']}")
            if out.get("report_path"):
                print(f"Rapor yazıldı: {out['report_path']}")

        if args.ingest:
            print("Artımlı 1_ingest.py çalıştırılıyor...")
            cmd = [sys.executable, "-X", "utf8", str(BASE_DIR / "1_ingest.py")]
            proc = subprocess.run(cmd, cwd=str(BASE_DIR), check=False)
            return proc.returncode

        errs = [o for o in out["outcomes"] if o["status"] == "error"]
        return 1 if errs else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
