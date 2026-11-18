import os
import re
from typing import List, Dict, Any, Optional, Tuple
import torch
import chromadb
from chromadb.api.models.Collection import Collection
from utils.config import (
    VECTOR_DB_DIR,
    EMBEDDING_MODEL_NAME,
    RERANKER_MODEL_NAME,
)
from utils.text_tr import tr_lower
from utils.standards import extract_standard_refs

# Global lazy-loaded models & in-memory caches
_embedding_model = None
_reranker_model = None
_chroma_client = None
_collection = None
_bm25_cache = {
    "count": -1,
    "bm25": None,
    "ids": [],
    "documents": [],
    "metadatas": [],
}


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
    """ChromaDB Persistent Client döndürür."""
    global _chroma_client
    if _chroma_client is None:
        VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(VECTOR_DB_DIR))
    return _chroma_client


def get_chroma_collection(collection_name: str = "insaat_mevzuat") -> Collection:
    """ChromaDB Persistent Client ve koleksiyonunu döndürür."""
    global _chroma_client, _collection
    if _collection is None:
        client = get_chroma_client()
        _collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


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


def get_or_build_bm25_index(collection: Collection, force_rebuild: bool = False) -> Dict[str, Any]:
    """ChromaDB veritabanından hafif in-memory BM25Okapi indeksi oluşturur veya önbellekten döndürür.
    Veritabanı dosyası (chroma.sqlite3) değiştiğinde sayaç aynı kalsa bile önbelleği otomatik yeniler."""
    global _bm25_cache
    current_count = collection.count()

    db_file = VECTOR_DB_DIR / "chroma.sqlite3"
    current_mtime = db_file.stat().st_mtime if db_file.exists() else 0.0

    if (
        not force_rebuild
        and _bm25_cache["bm25"] is not None
        and _bm25_cache["count"] == current_count
        and _bm25_cache.get("mtime") == current_mtime
    ):
        return _bm25_cache

    if current_count == 0:
        return {"count": 0, "mtime": current_mtime, "bm25": None, "ids": [], "documents": [], "metadatas": []}

    try:
        from rank_bm25 import BM25Okapi
        raw_data = collection.get(include=["documents", "metadatas"])
        docs = raw_data.get("documents", [])
        metas = raw_data.get("metadatas", [])
        ids = raw_data.get("ids", [])

        tokenized_corpus = [tokenize_for_bm25(doc) for doc in docs]
        bm25_model = BM25Okapi(tokenized_corpus)

        _bm25_cache = {
            "count": current_count,
            "mtime": current_mtime,
            "bm25": bm25_model,
            "ids": ids,
            "documents": docs,
            "metadatas": metas,
        }
    except Exception as e:
        print(f"[!] BM25 indeksi oluşturulamadı ({e}), yalnızca vektör araması kullanılacak.")
        _bm25_cache = {"count": current_count, "mtime": current_mtime, "bm25": None, "ids": [], "documents": [], "metadatas": []}

    return _bm25_cache


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
) -> List[Dict[str, Any]]:
    """
    Hibrit Arama (Dense Cosine + Lexical BM25) + BGE-Reranker ve Parent-Child Bağlam Genişletme:
    1. İhale Türü (procurement_type: yapim / danismanlik / ortak) ve Disiplin (subsystem) bazlı akıllı filtreleme uygular.
    2. ChromaDB'den BGE-M3 Dense Vektör araması ile adayları çeker.
    3. BM25Okapi ile exact anahtar kelime, standart no (EN 50122) ve poz (Poz 04.191) adaylarını çeker.
    4. Reciprocal Rank Fusion (RRF) ile iki sıralamayı dengeli birleştirir.
    5. BGE-Reranker-v2-m3 ile birleşik adayları yeniden puanlar.
    6. Parent-Child: Metadata'da parent_content varsa bağlamı tam maddeye genişletir.

    Adım 2 ekleri (geriye uyumlu — verilmezse filtre uygulanmaz):
        doc_role        : Sonuçları bu role kısıtlar ("normative_rule" / "correspondence_history").
        doc_type_filter : doc_type alanı bu listeden bir değere eşit olanları kısıtlar.
    """
    collection = get_chroma_collection()

    if collection.count() == 0:
        return []

    # 1. Kapsam Filtresi (Global mevzuat + Yalnızca seçili proje. Başka proje asla karışmaz)
    if project_id and project_id != "global":
        scope_filter = {"$or": [{"scope": "global"}, {"project_id": project_id}]}
    else:
        scope_filter = {"scope": "global"}

    # 0. Adım 2 sabit filtreleri (tüm gevşetme seviyelerinde geçerlidir)
    hard_conds: List[Dict[str, Any]] = []
    if doc_role:
        hard_conds.append({"doc_role": doc_role})
    if doc_type_filter:
        hard_conds.append({"doc_type": {"$in": doc_type_filter}})

    # 2. İhale Türü Filtresi (Yapım işi danışmanlık şartnamesini çekmez, danışmanlık işi YİGŞ'yi çekmez; 'ortak' her ikisine açıktır)
    effective_proc_type = procurement_type or detect_project_procurement_type(project_id)
    proc_filter = None
    if effective_proc_type in ("yapim", "danismanlik"):
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

    # Teknik disiplin aramalarında alt sistem (subsystem) mevcutsa Seviye 1'de kal (ilgisiz standartları karıştırma)
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
            min_required = 3 if (lvl == 1 and target_subs) else min(actual_k, 5)
            if len(dense_docs) >= min_required:
                break

    # 5. BM25 Lexical Arama (Hassas Kod ve Standart Eşleşmeleri - Disiplin Korumalı)
    bm25_info = get_or_build_bm25_index(collection)
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
                    if project_id and project_id != "global":
                        if m_scope != "global" and m_proj != project_id:
                            continue
                    else:
                        if m_scope != "global":
                            continue

                    # İhale türü (procurement_type) kontrolü
                    if effective_proc_type in ("yapim", "danismanlik"):
                        m_proc = meta.get("procurement_type", "ortak")
                        if m_proc not in (effective_proc_type, "ortak"):
                            continue

                    # Adım 2 sabit filtreleri (doc_role / doc_type)
                    if doc_role and meta.get("doc_role") != doc_role:
                        continue
                    if doc_type_filter and meta.get("doc_type") not in doc_type_filter:
                        continue

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

                min_bm25_req = 3 if (level == 1 and target_subs) else min(actual_k // 2, 5)
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
