# -*- coding: utf-8 -*-
"""
Proje Grafiği / Yazışma Defteri — SQLite katmanı (Adım 3).

Amaç:
    Yazışma kronolojisinin, Kimlik Kartı'larının, bağlantı köprülerinin ve
    durum geçmişinin KALICI kaynağı burasıdır (Neo4j/Docker yok).

Tablolar:
    documents     : Kimlik Kartı (tarih, sayı, taraf, durum, güven, özet ...)
    links         : 4 köprü kenarı (ilgi_zinciri / cevaplar / standart_ref / konu)
    tags          : çoklu etiketler (konu, alt_sistem, poz_no, standart)
    state_history : durum geçiş denetim izi (kim, hangi evrakla, insan onaylı mı)

Kural:
    - SQLite tek kaynak-of-truth'tür; bellek-içi grafik/gezinme buradan üretilir.
    - update_state insan onayı ile çağrılmalı (confirmed_by_human=1) — dava izi.
"""
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "project_graph.db"

# Geçerli durumlar (durum makinesi: sırayla ilerler, geri geçiş insan onayına tabidir)
VALID_STATES = ("Acik", "Kismen_Cevaplandi", "Cevaplandi", "Kapatildi")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id               TEXT PRIMARY KEY,          -- kanonik anahtar (ör. sha256 öneki)
    project_id           TEXT NOT NULL,
    file_path            TEXT,
    doc_sha256           TEXT,                      -- offset kilidi (char_start/end buna bağlı)
    doc_type             TEXT,                      -- yuklenici_yazisi / idare_cevabi / tutanak / hakedis / rapor
    sender_role          TEXT,                      -- contractor / administration / consultant / joint
    doc_date             TEXT,                      -- ISO YYYY-MM-DD (dateparser DMY ile)
    doc_no               TEXT,                      -- resmi sayı (E-84920, S.23-401 ...)
    subject              TEXT,
    ilgi_raw             TEXT,                      -- "İlgi:" satırı ham metni
    evidence_weight      TEXT,                      -- IDDIA_YUKLENICI / RESMI_POZISYON_IDARE / TUTANAK_ORTAK
    state                TEXT DEFAULT 'Acik',
    review_status        TEXT DEFAULT 'pending_review',  -- auto_approved / pending_review / human_approved
    extraction_confidence REAL DEFAULT 0.0,
    summary              TEXT,
    created_at           TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_project_date ON documents(project_id, doc_date);
CREATE INDEX IF NOT EXISTS idx_documents_doc_no ON documents(doc_no);
CREATE INDEX IF NOT EXISTS idx_documents_state ON documents(project_id, state);

CREATE TABLE IF NOT EXISTS links (
    link_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_doc_id    TEXT NOT NULL,
    to_ref         TEXT NOT NULL,                  -- doc_id (çözülmüşse) veya ham doc_no/standart kodu
    link_type      TEXT NOT NULL,                  -- ilgi_zinciri / cevaplar / standart_ref / sozlesme_madde_ref / konu_benzerligi
    resolved       INTEGER DEFAULT 0,              -- 1: to_ref bir doc_id'ye bağlandı
    evidence_span  TEXT,                           -- JSON: {"char_start":..,"char_end":..,"exact_quote":".."}
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_links_from ON links(from_doc_id);
CREATE INDEX IF NOT EXISTS idx_links_to ON links(to_ref);

CREATE TABLE IF NOT EXISTS tags (
    tag_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id    TEXT NOT NULL,
    tag_type  TEXT NOT NULL,                       -- konu / alt_sistem / poz_no / standart / lokasyon
    tag_value TEXT NOT NULL,
    UNIQUE(doc_id, tag_type, tag_value)
);
CREATE INDEX IF NOT EXISTS idx_tags_doc ON tags(doc_id);
CREATE INDEX IF NOT EXISTS idx_tags_value ON tags(tag_type, tag_value);

CREATE TABLE IF NOT EXISTS state_history (
    history_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id               TEXT NOT NULL,
    old_state            TEXT,
    new_state            TEXT NOT NULL,
    triggered_by_doc_id  TEXT,
    confirmed_by_human   INTEGER DEFAULT 0,
    changed_at           TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_state_history_doc ON state_history(doc_id);
"""


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Bağlantı açar, şemayı garanti eder (idempotent)."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def upsert_document(conn: sqlite3.Connection, card: Dict[str, Any]) -> str:
    """Kimlik Kartı'nı ekler/günceller. card["doc_id"] zorunlu. Mevcut state korunur."""
    doc_id = card["doc_id"]
    fields = [
        "project_id", "file_path", "doc_sha256", "doc_type", "sender_role",
        "doc_date", "doc_no", "subject", "ilgi_raw", "evidence_weight",
        "state", "review_status", "extraction_confidence", "summary",
    ]
    existing = conn.execute("SELECT doc_id, state FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    payload = dict(card)
    if existing:
        if not payload.get("state"):
            payload["state"] = existing["state"] or "Acik"
        sets = ", ".join(f"{f}=?" for f in fields)
        conn.execute(
            f"UPDATE documents SET {sets} WHERE doc_id=?",
            [payload.get(f) for f in fields] + [doc_id],
        )
    else:
        payload["state"] = payload.get("state") or "Acik"
        cols = ["doc_id"] + fields
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO documents ({', '.join(cols)}) VALUES ({placeholders})",
            [doc_id] + [payload.get(f) for f in cols[1:]],
        )
    conn.commit()
    return doc_id


def get_document(conn: sqlite3.Connection, doc_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    return dict(row) if row else None


def find_by_doc_no(conn: sqlite3.Connection, project_id: str, doc_no: str) -> Optional[Dict[str, Any]]:
    """İlgi: satırındaki ham sayıyı (ör. E-84920) proje içinde çözer."""
    row = conn.execute(
        "SELECT * FROM documents WHERE project_id=? AND doc_no=? ORDER BY doc_date LIMIT 1",
        (project_id, doc_no),
    ).fetchone()
    return dict(row) if row else None


def add_link(
    conn: sqlite3.Connection,
    from_doc_id: str,
    to_ref: str,
    link_type: str,
    resolved: bool = False,
    evidence_span: Optional[Dict[str, Any]] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO links (from_doc_id, to_ref, link_type, resolved, evidence_span) VALUES (?,?,?,?,?)",
        (from_doc_id, to_ref, link_type, 1 if resolved else 0,
         json.dumps(evidence_span, ensure_ascii=False) if evidence_span else None),
    )
    conn.commit()
    return cur.lastrowid


def link_exists(conn: sqlite3.Connection, from_doc_id: str, to_ref: str, link_type: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM links WHERE from_doc_id=? AND to_ref=? AND link_type=? LIMIT 1",
        (from_doc_id, to_ref, link_type),
    ).fetchone()
    return row is not None


def add_tags(conn: sqlite3.Connection, doc_id: str, tags: List[Dict[str, str]]) -> None:
    """tags: [{"tag_type": "konu", "tag_value": "mimar_sinan_istasyonu"}, ...]"""
    for t in tags:
        conn.execute(
            "INSERT OR IGNORE INTO tags (doc_id, tag_type, tag_value) VALUES (?,?,?)",
            (doc_id, t["tag_type"], t["tag_value"]),
        )
    conn.commit()


def update_state(
    conn: sqlite3.Connection,
    doc_id: str,
    new_state: str,
    triggered_by_doc_id: Optional[str] = None,
    confirmed_by_human: bool = False,
) -> bool:
    """
    Durumu günceller ve state_history'ye denetim izi yazar.
    Geçersiz durum reddedilir (sessizce değil — ValueError).
    """
    if new_state not in VALID_STATES:
        raise ValueError(f"Geçersiz durum: {new_state} (geçerli: {VALID_STATES})")
    row = conn.execute("SELECT state FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if not row:
        raise ValueError(f"Belge bulunamadı: {doc_id}")
    old = row["state"]
    if old == new_state:
        return False
    conn.execute("UPDATE documents SET state=? WHERE doc_id=?", (new_state, doc_id))
    conn.execute(
        "INSERT INTO state_history (doc_id, old_state, new_state, triggered_by_doc_id, confirmed_by_human) "
        "VALUES (?,?,?,?,?)",
        (doc_id, old, new_state, triggered_by_doc_id, 1 if confirmed_by_human else 0),
    )
    conn.commit()
    return True


def iter_chain(
    conn: sqlite3.Connection,
    doc_id: str,
    link_type: str = "ilgi_zinciri",
    max_depth: int = 10,
    link_types: Optional[tuple] = None,
) -> List[Dict[str, Any]]:
    """
    İlgi / cevap zincirini geriye doğru yürür (doc_id -> to_ref -> ...).
    SQLite recursive CTE — döngülerde dahi her belge en küçük derinliğiyle
    yalnızca bir kez döner, başlangıç belgesi zincire geri sızmaz.
    Döndürür: zincir sırasındaki kart sözlükleri (yeni -> eski yönünde).
    """
    types = tuple(link_types) if link_types else (
        ("ilgi_zinciri", "cevaplar") if link_type == "ilgi_zinciri" else (link_type,)
    )
    placeholders = ",".join("?" for _ in types)
    rows = conn.execute(
        f"""
        WITH RECURSIVE chain(doc_id, to_ref, depth) AS (
            SELECT l.from_doc_id, l.to_ref, 0
            FROM links l WHERE l.from_doc_id=? AND l.resolved=1 AND l.link_type IN ({placeholders})
            UNION ALL
            SELECT l2.from_doc_id, l2.to_ref, c.depth + 1
            FROM links l2
            JOIN chain c ON l2.from_doc_id = c.to_ref
            WHERE l2.resolved=1 AND l2.link_type IN ({placeholders}) AND c.depth < ?
        )
        SELECT d.*, MIN(ch.depth) AS depth
        FROM chain ch
        JOIN documents d ON d.doc_id = ch.to_ref
        WHERE d.doc_id != ?
        GROUP BY d.doc_id
        ORDER BY depth ASC, d.doc_date DESC
        """,
        (doc_id, *types, *types, max_depth, doc_id),
    ).fetchall()
    return [dict(r) for r in rows]


def find_related_by_tags(
    conn: sqlite3.Connection,
    project_id: str,
    tag_pairs: List[tuple],
    exclude_doc_ids: Optional[set] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """
    Aynı projede ortak standart/poz/konu etiketlerini paylaşan belgeleri
    paylaşılan etiket sayısına (ve yeniliğe) göre sıralı döndürür.
    """
    if not tag_pairs or not project_id:
        return []
    excl = set(exclude_doc_ids or ())
    conds = " OR ".join("(t.tag_type=? AND t.tag_value=?)" for _ in tag_pairs)
    params: List[Any] = [project_id]
    for tt, tv in tag_pairs:
        params.extend([tt, tv])
    rows = conn.execute(
        f"""
        SELECT d.*, COUNT(DISTINCT t.tag_type || ':' || t.tag_value) AS shared_tag_count,
               GROUP_CONCAT(DISTINCT t.tag_type || '=' || t.tag_value) AS shared_tags
        FROM tags t
        JOIN documents d ON d.doc_id = t.doc_id
        WHERE d.project_id=? AND ({conds})
        GROUP BY d.doc_id
        ORDER BY shared_tag_count DESC, d.doc_date DESC
        LIMIT ?
        """,
        (*params, limit + len(excl)),
    ).fetchall()
    out = []
    for r in rows:
        rd = dict(r)
        if rd["doc_id"] not in excl:
            out.append(rd)
            if len(out) >= limit:
                break
    return out


def list_open_claims(
    conn: sqlite3.Connection,
    project_id: str,
    exclude_doc_ids: Optional[set] = None,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Projedeki Açık / Kısmen Cevaplandı durumundaki talep defteri kayıtlarını döndürür."""
    if not project_id:
        return []
    excl = set(exclude_doc_ids or ())
    rows = conn.execute(
        """
        SELECT * FROM documents
        WHERE project_id=? AND state IN ('Acik', 'Kismen_Cevaplandi')
        ORDER BY doc_date DESC, created_at DESC
        LIMIT ?
        """,
        (project_id, limit + len(excl)),
    ).fetchall()
    out = []
    for r in rows:
        rd = dict(r)
        if rd["doc_id"] not in excl:
            out.append(rd)
            if len(out) >= limit:
                break
    return out


def pending_review(conn: sqlite3.Connection, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if project_id:
        rows = conn.execute(
            "SELECT * FROM documents WHERE review_status='pending_review' AND project_id=? "
            "ORDER BY created_at", (project_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM documents WHERE review_status='pending_review' ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def approve(conn: sqlite3.Connection, doc_id: str) -> None:
    """İnsan onayı: pending_review -> human_approved (10 saniyelik CLI için)."""
    conn.execute("UPDATE documents SET review_status='human_approved' WHERE doc_id=?", (doc_id,))
    conn.commit()


def find_by_file_path(conn: sqlite3.Connection, project_id: str, file_path: str) -> Optional[Dict[str, Any]]:
    """Artımlı mod: aynı dosya yolu daha önce işlendi mi?"""
    row = conn.execute(
        "SELECT * FROM documents WHERE project_id=? AND file_path=? LIMIT 1",
        (project_id, file_path),
    ).fetchone()
    return dict(row) if row else None


def list_doc_nos(conn: sqlite3.Connection, project_id: str) -> List[str]:
    """Projedeki bilinen tüm evrak numaraları (rapidfuzz çözümleme havuzu)."""
    rows = conn.execute(
        "SELECT DISTINCT doc_no FROM documents WHERE project_id=? AND doc_no IS NOT NULL AND doc_no!=''",
        (project_id,),
    ).fetchall()
    return [r["doc_no"] for r in rows]


def get_unresolved_links(
    conn: sqlite3.Connection,
    project_id: str,
    link_type: str = "ilgi_zinciri",
) -> List[Dict[str, Any]]:
    """2. tur (backfill) çözümleme için çözülmemiş kenarlar (belge + ham referans)."""
    rows = conn.execute(
        """
        SELECT l.link_id, l.from_doc_id, l.to_ref, d.project_id
        FROM links l JOIN documents d ON d.doc_id = l.from_doc_id
        WHERE l.link_type=? AND l.resolved=0 AND d.project_id=?
        """,
        (link_type, project_id),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_link(conn: sqlite3.Connection, link_id: int, to_doc_id: str) -> None:
    """Çözülmemiş kenarı gerçek doc_id'ye bağlar (2. tur backfill)."""
    conn.execute("UPDATE links SET to_ref=?, resolved=1 WHERE link_id=?", (to_doc_id, link_id))
    conn.commit()


def delete_document(conn: sqlite3.Connection, doc_id: str) -> None:
    """Belge ve ona ait giden kenar/etiketleri temizler (dosya güncellendiğinde yenisi yazılmadan önce)."""
    conn.execute("DELETE FROM links WHERE from_doc_id=?", (doc_id,))
    conn.execute("DELETE FROM tags WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
    conn.commit()


def _ocr_docno_skeleton(s: str) -> str:
    """Evrak numarasındaki yaygın OCR karışıklıklarını (S<->5, O<->0, I/L<->1) temizler."""
    s = s.upper().strip()
    s = s.translate(str.maketrans({"5": "S", "0": "O", "1": "I", "L": "I"}))
    return re.sub(r"[\s.\-/]+", "", s)


def match_doc_no_in_project(
    conn: sqlite3.Connection,
    project_id: str,
    ref: str,
    ilgi_dates: Optional[List[str]] = None,
    fuzz_threshold: int = 92,
) -> Optional[Dict[str, Any]]:
    """
    Evrak numarasını proje içinde 3 kademede çözer:
      1) Tam eşleşme (doc_no = ref)
      2) rapidfuzz >= fuzz_threshold (varsayılan 92)
      3) OCR karışıklık iskeleti eşleşmesi (S<->5, 0<->O) veya
         82 <= fuzzy < 92 iken aynı belgenin doc_date'i ilgi_dates içinde doğrulanıyorsa
    """
    hedef = find_by_doc_no(conn, project_id, ref)
    if hedef:
        return hedef

    rows = conn.execute(
        "SELECT doc_id, doc_no, doc_date FROM documents WHERE project_id=? AND doc_no IS NOT NULL AND doc_no!=''",
        (project_id,),
    ).fetchall()
    if not rows:
        return None

    from rapidfuzz import fuzz, process

    doc_nos = list(dict.fromkeys(r["doc_no"] for r in rows))
    best = process.extractOne(ref, doc_nos, scorer=fuzz.token_sort_ratio, score_cutoff=fuzz_threshold)
    if best:
        return find_by_doc_no(conn, project_id, best[0])

    # 3) OCR karışıklık iskeleti veya tarih doğrulamalı bulanık eşleşme
    ref_skel = _ocr_docno_skeleton(ref)
    if len(ref_skel) >= 4:
        for r in rows:
            if _ocr_docno_skeleton(r["doc_no"]) == ref_skel:
                # Tarih de verilmişse çelişmediğini doğrula
                if not ilgi_dates or not r["doc_date"] or r["doc_date"] in ilgi_dates:
                    return get_document(conn, r["doc_id"])

    if ilgi_dates:
        best_mid = process.extractOne(ref, doc_nos, scorer=fuzz.ratio, score_cutoff=80)
        if best_mid:
            cand = find_by_doc_no(conn, project_id, best_mid[0])
            if cand and cand.get("doc_date") in ilgi_dates:
                return cand

    # 4) Ayıraç normalize (ATI/AS/TR/PM/4236 == ATi-AS-TR-PM-4236) ve segment son eki
    #    (hem tam: .S.21-2202 -> S.21-2202, hem OCR iskeletli: .S.23-401 <-> 5.23-401)
    def _norm_sep(val: str) -> str:
        s = val.replace("i", "I").replace("İ", "I").upper().strip()
        return re.sub(r"[-./_\s]+", "-", s).strip("-")

    def _norm_skel_sep(val: str) -> str:
        segs = [s for s in re.split(r"[-./_\s]+", (val or "").strip()) if s]
        return "-".join(_ocr_docno_skeleton(s) for s in segs)

    ref_sep = _norm_sep(ref)
    ref_skel_sep = _norm_skel_sep(ref)
    if len(ref_sep) >= 4:
        suffix_hits = []
        for r in rows:
            d_sep = _norm_sep(r["doc_no"])
            if d_sep == ref_sep:
                return get_document(conn, r["doc_id"])
            d_skel_sep = _norm_skel_sep(r["doc_no"])
            if (
                d_sep.endswith("-" + ref_sep)
                or ref_sep.endswith("-" + d_sep)
                or (len(ref_skel_sep) >= 5 and (d_skel_sep == ref_skel_sep or d_skel_sep.endswith("-" + ref_skel_sep) or ref_skel_sep.endswith("-" + d_skel_sep)))
            ):
                if not ilgi_dates or not r["doc_date"] or r["doc_date"] in ilgi_dates:
                    suffix_hits.append(r)
        # Çıplak sayısal son ekte yalnızca tarih teyitli veya tekil aday varsa bağla
        if len(suffix_hits) == 1 and (len(ref_sep) >= 6 or not ref_sep.isdigit() or (ilgi_dates and suffix_hits[0]["doc_date"] in ilgi_dates)):
            return get_document(conn, suffix_hits[0]["doc_id"])
        if len(suffix_hits) > 1 and ilgi_dates:
            dated = [h for h in suffix_hits if h["doc_date"] in ilgi_dates]
            if len(dated) == 1:
                return get_document(conn, dated[0]["doc_id"])
    return None
