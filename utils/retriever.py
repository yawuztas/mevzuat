import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import torch
import chromadb
from chromadb.api.models.Collection import Collection
from utils.config import (
    VECTOR_DB_DIR,
    CORRESPONDENCE_VECTOR_DB_DIR,
    NORMATIVE_COLLECTION_NAME,
    CORRESPONDENCE_COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    RERANKER_MODEL_NAME,
)
from utils.text_tr import tr_lower
from utils.standards import extract_standard_refs

# Global lazy-loaded models & in-memory caches (fiziksel olarak ayrılmış 2 ChromaDB)
_embedding_model = None
_reranker_model = None
_chroma_client = None
_collection = None
_corr_clients: Dict[str, chromadb.PersistentClient] = {}
_corr_collections: Dict[Tuple[str, str], Collection] = {}
_bm25_caches: Dict[str, Dict[str, Any]] = {}


def get_device() -> str:
    """CUDA çalışabiliyorsa cuda, aksi halde cpu döndürür."""
    if torch.cuda.is_available():
        try:
            _ = torch.zeros(1, device="cuda")
            return "cuda"
        except Exception:
            return "cpu"
    return "cpu"


def get_embedding_model():
    """BGE-M3 modelini yükler (Cuda veya CPU)."""
    global _embedding_model
    if _embedding_model is None:
        device = get_device()
        print(f"[*] BGE-M3 Embedding modeli yükleniyor ({device})...")
        try:
            from FlagEmbedding import BGEM3FlagModel

            _embedding_model = BGEM3FlagModel(
                EMBEDDING_MODEL_NAME,
                use_fp16=(device == "cuda"),
                device=device,
            )
        except Exception as e:
            print(f"[!] FlagEmbedding yüklenirken hata oluştu ({e}), SentenceTransformer deneniyor...")
            from sentence_transformers import SentenceTransformer

            _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device)
    return _embedding_model


def get_reranker_model():
    """BGE-Reranker modelini yükler."""
    global _reranker_model
    if _reranker_model is None:
        device = get_device()
        print(f"[*] BGE-Reranker modeli yükleniyor ({device})...")
        try:
            from FlagEmbedding import FlagReranker

            _reranker_model = FlagReranker(
                RERANKER_MODEL_NAME,
                use_fp16=(device == "cuda"),
                device=device,
            )
        except Exception as e:
            print(f"[!] FlagReranker yüklenemedi: {e}")
            _reranker_model = None
    return _reranker_model


def get_chroma_client() -> chromadb.PersistentClient:
    """Normatif (Katman 1 & 2) ChromaDB Persistent Client döndürür (`vector_db/`)."""
    global _chroma_client
    if _chroma_client is None:
        VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(VECTOR_DB_DIR))
    return _chroma_client


def get_chroma_collection(collection_name: str = NORMATIVE_COLLECTION_NAME) -> Collection:
    """Normatif (Katman 1 & 2) ChromaDB koleksiyonunu döndürür (`vector_db/insaat_mevzuat`)."""
    global _collection
    if collection_name == NORMATIVE_COLLECTION_NAME and _collection is not None:
        return _collection
    client = get_chroma_client()
    col = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    if collection_name == NORMATIVE_COLLECTION_NAME:
        _collection = col
    return col


def get_correspondence_client(db_dir: Optional[Path] = None) -> chromadb.PersistentClient:
    """Katman 3 Yazışma Geçmişi için fiziksel olarak ayrı ChromaDB Client döndürür (`vector_db_yazismalar/`)."""
    target_dir = Path(db_dir).resolve() if db_dir else CORRESPONDENCE_VECTOR_DB_DIR.resolve()
    key = str(target_dir)
    if key not in _corr_clients:
        target_dir.mkdir(parents=True, exist_ok=True)
        _corr_clients[key] = chromadb.PersistentClient(path=key)
    return _corr_clients[key]


def get_correspondence_collection(
    collection_name: str = CORRESPONDENCE_COLLECTION_NAME,
    db_dir: Optional[Path] = None,
) -> Collection:
    """Katman 3 Yazışma Geçmişi için ayrı ChromaDB koleksiyonunu döndürür (`vector_db_yazismalar/proje_yazismalari`)."""
    target_dir = Path(db_dir).resolve() if db_dir else CORRESPONDENCE_VECTOR_DB_DIR.resolve()
    cache_key = (str(target_dir), collection_name)
    if cache_key not in _corr_collections:
        client = get_correspondence_client(target_dir)
        _corr_collections[cache_key] = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine", "description": "Fiziksel olarak ayrılmış Katman 3 proje yazışma koleksiyonu"},
        )
    return _corr_collections[cache_key]


def reset_correspondence_cache(db_dir: Optional[Path] = None) -> None:
    """İzole testler veya temizlik sonrası yazışma Chroma/BM25 önbelleğini boşaltır."""
    if db_dir is None:
        _corr_collections.clear()
        _corr_clients.clear()
        for k in [key for key in _bm25_caches if key.startswith("corr::")]:
            _bm25_caches.pop(k, None)
        return
    target = str(Path(db_dir).resolve())
    for k in [key for key in _corr_collections if key[0] == target]:
        _corr_collections.pop(k, None)
    _corr_clients.pop(target, None)
    for k in [key for key in _bm25_caches if target in key]:
        _bm25_caches.pop(k, None)


def generate_embedding(text: str) -> List[float]:
    """Metin için BGE-M3 embedding vektörü üretir."""
    model = get_embedding_model()
    if hasattr(model, "encode"):
        res = model.encode([text], return_dense=True)
        if isinstance(res, dict) and "dense_vecs" in res:
            return res["dense_vecs"][0].tolist()
        elif hasattr(res, "tolist"):
            return res.tolist()[0]
        return list(res[0])
    elif hasattr(model, "encode_queries"):
        res = model.encode_queries([text])
        if isinstance(res, dict) and "dense_vecs" in res:
            return res["dense_vecs"][0].tolist()
        return res[0].tolist()
    else:
        raise RuntimeError("Embedding model interface uyumsuz.")


def tokenize_for_bm25(text: str) -> List[str]:
    """Türkçe ve teknik terim (EN 50122, Poz 04.191, Madde 10) duyarlı tokenizasyon."""
    cleaned = tr_lower(text)
    # Kelimeler, tireli standartlar ve noktalı poz/madde numaralarını koru
    tokens = re.findall(r"[a-zçğıöşü0-9]+(?:[-./][a-zçğıöşü0-9]+)*", cleaned)
    tokens = [t for t in tokens if len(t) > 1]
    # Adım 2: Standart kodlarının kanonik biçimlerini ayrı token olarak ekle.
    # "EN50126" / "EN 50126:2006" / "TS EN 50126-1" yazım farkları aynı
    # kanonik tokenla (en_50126, en_50126_1) BM25'te eşleşir.
    for ref in extract_standard_refs(text):
        for key in (ref["canonical"], ref["family"]):
            tok = key.lower().replace(" ", "_")
            if tok not in tokens:
                tokens.append(tok)
    return tokens


def get_or_build_bm25_index(
    collection: Collection,
    force_rebuild: bool = False,
    db_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """ChromaDB veritabanından mağaza-bazlı izole in-memory BM25Okapi indeksi döndürür.
    Normatif DB (vector_db) ve Yazışma DB (vector_db_yazismalar) önbellekleri asla çakışmaz."""
    current_count = collection.count()
    col_name = getattr(collection, "name", NORMATIVE_COLLECTION_NAME)
    if db_dir is not None:
        eff_dir = Path(db_dir).resolve()
    elif col_name == CORRESPONDENCE_COLLECTION_NAME:
        eff_dir = CORRESPONDENCE_VECTOR_DB_DIR.resolve()
    else:
        eff_dir = VECTOR_DB_DIR.resolve()

    cache_prefix = "corr" if col_name == CORRESPONDENCE_COLLECTION_NAME else "norm"
    cache_key = f"{cache_prefix}::{eff_dir}::{col_name}"
    db_file = eff_dir / "chroma.sqlite3"
    current_mtime = db_file.stat().st_mtime if db_file.exists() else 0.0

    cached = _bm25_caches.get(cache_key)
    if (
        not force_rebuild
        and cached is not None
        and cached.get("bm25") is not None
        and cached.get("count") == current_count
        and cached.get("mtime") == current_mtime
    ):
        return cached

    if current_count == 0:
        empty = {"count": 0, "mtime": current_mtime, "bm25": None, "ids": [], "documents": [], "metadatas": []}
        _bm25_caches[cache_key] = empty
        return empty

    try:
        from rank_bm25 import BM25Okapi
        raw_data = collection.get(include=["documents", "metadatas"])
        docs = raw_data.get("documents", [])
        metas = raw_data.get("metadatas", [])
        ids = raw_data.get("ids", [])

        tokenized_corpus = [tokenize_for_bm25(doc) for doc in docs]
        bm25_model = BM25Okapi(tokenized_corpus)

        entry = {
            "count": current_count,
            "mtime": current_mtime,
            "bm25": bm25_model,
            "ids": ids,
            "documents": docs,
            "metadatas": metas,
        }
        _bm25_caches[cache_key] = entry
    except Exception as e:
        print(f"[!] BM25 indeksi oluşturulamadı ({e}), yalnızca vektör araması kullanılacak.")
        entry = {"count": current_count, "mtime": current_mtime, "bm25": None, "ids": [], "documents": [], "metadatas": []}
        _bm25_caches[cache_key] = entry

    return _bm25_caches[cache_key]


def detect_project_procurement_type(project_id: Optional[str]) -> Optional[str]:
    """Proje kodundan ihale/sözleşme tipini ('yapim' veya 'danismanlik') tespit eder."""
    if not project_id or project_id == "global":
        return None
    pid_lower = project_id.lower()
    if any(k in pid_lower for k in ["musavir", "danisman", "kontrolluk"]):
        return "danismanlik"
    return "yapim"


def search_and_rerank(
    query: str,
    domain: Optional[str] = None,
    subsystem: Optional[str] = None,
    subsystems: Optional[List[str]] = None,
    project_id: Optional[str] = None,
    procurement_type: Optional[str] = None,
    candidate_k: int = 25,
    final_top_k: int = 4,
    doc_role: Optional[str] = None,
    doc_type_filter: Optional[List[str]] = None,
    correspondence_db_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    Hibrit Arama (Dense Cosine + Lexical BM25) + BGE-Reranker ve Parent-Child Bağlam Genişletme:
    - Fiziksel DB Yönlendirmesi:
      * doc_role == "correspondence_history" -> YALNIZCA `vector_db_yazismalar/` (`proje_yazismalari`) taranır.
      * Diğer tüm sorgular ("normative_rule" / None) -> YALNIZCA `vector_db/` (`insaat_mevzuat`) taranır.
    """
    is_correspondence = doc_role == "correspondence_history"
    if is_correspondence:
        eff_db_dir = Path(correspondence_db_dir).resolve() if correspondence_db_dir else CORRESPONDENCE_VECTOR_DB_DIR.resolve()
        collection = get_correspondence_collection(db_dir=eff_db_dir)
    else:
        eff_db_dir = VECTOR_DB_DIR.resolve()
        collection = get_chroma_collection()

    if collection.count() == 0:
        return []

    # 1. Kapsam Filtresi
    # - Yazışma DB'si daima proje bazlıdır (global yazışma yoktur; başka proje asla karışmaz).
    # - Normatif DB: Global mevzuat + yalnızca seçili proje.
    if is_correspondence:
        scope_filter = {"project_id": project_id} if (project_id and project_id != "global") else {"doc_role": "correspondence_history"}
    elif project_id and project_id != "global":
        scope_filter = {"$or": [{"scope": "global"}, {"project_id": project_id}]}
    else:
        scope_filter = {"scope": "global"}

    # 0. Adım 2 sabit filtreleri (tüm gevşetme seviyelerinde geçerlidir)
    hard_conds: List[Dict[str, Any]] = []
    if doc_role and scope_filter != {"doc_role": doc_role}:
        hard_conds.append({"doc_role": doc_role})
    if doc_type_filter:
        hard_conds.append({"doc_type": {"$in": doc_type_filter}})

    # 2. İhale Türü Filtresi (Yapım işi danışmanlık şartnamesini çekmez, danışmanlık işi YİGŞ'yi çekmez; 'ortak' her ikisine açıktır)
    effective_proc_type = procurement_type or detect_project_procurement_type(project_id)
    proc_filter = None
    if not is_correspondence and effective_proc_type in ("yapim", "danismanlik"):
        proc_filter = {"procurement_type": {"$in": [effective_proc_type, "ortak"]}}

    # 3. Hedef Disiplin / Alt Sistem Listesi
    target_subs: List[str] = []
    if subsystems:
        target_subs = [s for s in dict.fromkeys(subsystems) if s]
    elif subsystem:
        target_subs = [subsystem]

    def _build_filter(level: int) -> Dict[str, Any]:
        conds = [scope_filter] + hard_conds
        if proc_filter:
            conds.append(proc_filter)
        if not is_correspondence:
            if level == 1:
                if domain:
                    conds.append({"domain": domain})
                if len(target_subs) == 1:
                    conds.append({"subsystem": target_subs[0]})
                elif len(target_subs) > 1:
                    conds.append({"subsystem": {"$in": target_subs}})
            elif level == 2:
                if domain:
                    conds.append({"domain": domain})
            elif level == 3:
                # Teknik domainlerde (elektromekanik / insaat) domain filtresi asla kaldırılmaz!
                # Yalnızca mevzuat <-> idari arasında çapraz geçişe izin verilir.
                if domain in ("mevzuat", "idari"):
                    conds.append({"domain": {"$in": ["mevzuat", "idari"]}})
                elif domain:
                    conds.append({"domain": domain})
        return conds[0] if len(conds) == 1 else {"$and": conds}

    query_vector = generate_embedding(query)
    actual_k = min(candidate_k, collection.count())

    # Yazışma DB'sinde tek aşamalı proje-izole arama; normatif DB'de disiplin korumalı kademeli gevşetme
    if is_correspondence:
        max_levels = [1]
    else:
        max_levels = [1, 2, 3] if domain in ("mevzuat", "idari", None) else ([1, 2] if target_subs else [2])

    # 4. Dense Arama (Disiplin Korumalı Kademeli Gevşetme)
    dense_docs, dense_metas, dense_ids = [], [], []
    for lvl in max_levels:
        res = collection.query(
            query_embeddings=[query_vector],
            n_results=actual_k,
            where=_build_filter(lvl),
        )
        found_docs = res.get("documents", [[]])[0]
        found_metas = res.get("metadatas", [[]])[0]
        found_ids = res.get("ids", [[]])[0]
        if found_docs:
            dense_docs = found_docs
            dense_metas = found_metas
            dense_ids = found_ids
            min_required = 3 if (lvl == 1 and target_subs and not is_correspondence) else min(actual_k, 5)
            if len(dense_docs) >= min_required:
                break

    # 5. BM25 Lexical Arama (Hassas Kod ve Standart Eşleşmeleri - Disiplin Korumalı)
    bm25_info = get_or_build_bm25_index(collection, db_dir=eff_db_dir)
    bm25_model = bm25_info.get("bm25")
    all_ids = bm25_info.get("ids", [])
    all_docs = bm25_info.get("documents", [])
    all_metas = bm25_info.get("metadatas", [])

    bm25_candidates = []
    if bm25_model is not None and all_docs:
        query_tokens = tokenize_for_bm25(query)
        if query_tokens:
            scores = bm25_model.get_scores(query_tokens)
            for level in max_levels:
                level_candidates = []
                for idx, score in enumerate(scores):
                    if score <= 0.0:
                        continue
                    meta = all_metas[idx]
                    # Scope kontrolü
                    m_scope = meta.get("scope", "global")
                    m_proj = meta.get("project_id", "global")
                    if is_correspondence:
                        if project_id and project_id != "global" and m_proj != project_id:
                            continue
                    elif project_id and project_id != "global":
                        if m_scope != "global" and m_proj != project_id:
                            continue
                    else:
                        if m_scope != "global":
                            continue

                    # İhale türü (procurement_type) kontrolü (yalnızca normatif DB)
                    if not is_correspondence and effective_proc_type in ("yapim", "danismanlik"):
                        m_proc = meta.get("procurement_type", "ortak")
                        if m_proc not in (effective_proc_type, "ortak"):
                            continue

                    # Adım 2 sabit filtreleri (doc_role / doc_type)
                    if doc_role and meta.get("doc_role") != doc_role:
                        continue
                    if doc_type_filter and meta.get("doc_type") not in doc_type_filter:
                        continue

                    if not is_correspondence:
                        if level == 1:
                            if domain and meta.get("domain") != domain:
                                continue
                            if target_subs and meta.get("subsystem") not in target_subs:
                                continue
                        elif level == 2:
                            if domain and meta.get("domain") != domain:
                                continue
                        elif level == 3:
                            if domain in ("mevzuat", "idari"):
                                if meta.get("domain") not in ("mevzuat", "idari"):
                                    continue
                            elif domain and meta.get("domain") != domain:
                                continue

                    level_candidates.append((all_ids[idx], all_docs[idx], meta, float(score)))

                min_bm25_req = 3 if (level == 1 and target_subs and not is_correspondence) else min(actual_k // 2, 5)
                if len(level_candidates) >= min_bm25_req or level == max_levels[-1]:
                    level_candidates.sort(key=lambda x: x[3], reverse=True)
                    bm25_candidates = level_candidates[:actual_k]
                    break

    # 4. Reciprocal Rank Fusion (RRF) - Dense + BM25 Birleştirme
    rrf_constant = 60.0
    doc_pool = {}  # doc_id -> {"doc": ..., "meta": ..., "rrf_score": float}

    # Dense katkısı
    for rank, (doc_id, doc, meta) in enumerate(zip(dense_ids, dense_docs, dense_metas)):
        if doc_id not in doc_pool:
            doc_pool[doc_id] = {"doc": doc, "meta": meta, "rrf_score": 0.0}
        doc_pool[doc_id]["rrf_score"] += 1.0 / (rrf_constant + rank + 1)

    # BM25 katkısı
    for rank, (doc_id, doc, meta, _) in enumerate(bm25_candidates):
        if doc_id not in doc_pool:
            doc_pool[doc_id] = {"doc": doc, "meta": meta, "rrf_score": 0.0}
        doc_pool[doc_id]["rrf_score"] += 1.0 / (rrf_constant + rank + 1)

    if not doc_pool:
        return []

    # En yüksek RRF skorlu adayları sırala (Reranker'a gönderilecek havuz)
    sorted_pool = sorted(doc_pool.items(), key=lambda item: item[1]["rrf_score"], reverse=True)
    merged_candidates = sorted_pool[: min(actual_k, 30)]

    cand_ids = [item[0] for item in merged_candidates]
    cand_docs = [item[1]["doc"] for item in merged_candidates]
    cand_metas = [item[1]["meta"] for item in merged_candidates]

    # 5. BGE-Reranker ile Yeniden Sıralama (Cross-Encoder)
    reranker = get_reranker_model()
    scored_candidates = []

    if reranker is not None and cand_docs:
        pairs = [[query, doc] for doc in cand_docs]
        try:
            scores = reranker.compute_score(pairs)
            if not isinstance(scores, list):
                scores = [scores]
            for idx, (doc, meta, score) in enumerate(zip(cand_docs, cand_metas, scores)):
                scored_candidates.append(
                    {
                        "id": cand_ids[idx],
                        "content": doc,
                        "metadata": meta,
                        "rerank_score": float(score),
                    }
                )
            scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        except Exception as e:
            print(f"[!] Reranker scoring hatası ({e}), RRF sırası kullanılıyor.")
            for idx, (doc, meta) in enumerate(zip(cand_docs, cand_metas)):
                scored_candidates.append(
                    {
                        "id": cand_ids[idx],
                        "content": doc,
                        "metadata": meta,
                        "rerank_score": float(merged_candidates[idx][1]["rrf_score"]),
                    }
                )
    else:
        for idx, (doc, meta) in enumerate(zip(cand_docs, cand_metas)):
            scored_candidates.append(
                {
                    "id": cand_ids[idx],
                    "content": doc,
                    "metadata": meta,
                    "rerank_score": float(merged_candidates[idx][1]["rrf_score"]),
                }
            )

    top_results = scored_candidates[:final_top_k]

    # 6. Parent-Child Bağlam Genişletme (Parent Chunk Expansion)
    for res_item in top_results:
        meta = res_item.get("metadata", {})
        parent_content = meta.get("parent_content")
        if parent_content and len(parent_content) > len(res_item["content"]):
            res_item["child_excerpt"] = res_item["content"]
            res_item["content"] = parent_content

    return top_results
