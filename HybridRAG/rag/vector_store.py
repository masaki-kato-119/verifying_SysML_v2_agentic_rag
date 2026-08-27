"""ベクトルストアAPIモジュール。

このモジュールは、ChromaDBを使用したベクトルデータベースの
登録、検索、更新、削除機能を提供します。
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import chromadb
from chromadb.api.models.Collection import Collection

# chromadb のバージョンによっては InternalError が存在しないため、
# その場合は汎用 Exception にフォールバックする。
try:  # pragma: no cover - バージョン依存の分岐
    from chromadb.errors import InternalError  # type: ignore
except (ImportError, AttributeError):  # モジュール自体が無い/属性が無い、両バージョンに対応
    InternalError = Exception  # type: ignore[misc,assignment]

from . import embedding
from .config import CHROMA_DIR

logger = logging.getLogger(__name__)


@dataclass
class VectorRecord:
    """ベクトルDBに登録されている1チャンク分のレコード表現。

    Attributes:
        id: レコードの一意識別子（通常は ``document_id::chunk-{index}`` 形式）。
        text: チャンクのテキスト内容。
        metadata: メタデータの辞書（ファイル名、パス、種別など）。
        distance: 検索時の類似度距離（小さいほど類似度が高い）。
            Noneの場合は未設定。
    """

    id: str
    text: str
    metadata: Dict[str, Any]
    distance: Optional[float] = None


class VectorStoreAPI:
    """ChromaDB を用いたベクトル登録・検索・更新・削除のAPI。

    ベクトルは OpenAI 埋め込みで事前計算してから登録します。

    Attributes:
        EMBEDDING_BATCH_SIZE: 一度の埋め込みリクエストで処理する
            チャンク数の上限（デフォルト: 32）。
            トークン上限 300k を超えないよう、小さめに分割します。
    """

    # 一度の埋め込みリクエストで処理するチャンク数の上限
    # （トークン上限 300k を超えないよう、小さめに分割する）
    EMBEDDING_BATCH_SIZE: int = 32

    def __init__(
        self,
        collection_name: str | None = None,
        persist_directory: str | None = None,
    ) -> None:
        """VectorStoreAPIを初期化する。

        Args:
            collection_name: ChromaDBコレクション名。
                Noneの場合は環境変数 ``RAG_CHROMA_COLLECTION`` を参照し、
                未設定なら "rag_documents" を使用します。
            persist_directory: データベースの永続化ディレクトリ。
                Noneの場合は ``config.CHROMA_DIR`` を使用。
        """
        self._collection_name = collection_name or os.getenv("RAG_CHROMA_COLLECTION") or "rag_documents"
        self._persist_path = str(persist_directory or CHROMA_DIR)
        self._client = chromadb.PersistentClient(path=self._persist_path)
        self._collection: Collection = self._client.get_or_create_collection(name=self._collection_name)

    def _reset_chroma_storage(self) -> None:
        """ChromaDB永続領域を削除して作り直す（最後の手段）。

        Windows/Chroma/RustのHNSW周りで壊れた状態になることがあるため、
        本プロジェクトでは「確実に動く」ことを優先して自動リセットを許可する。
        """
        try:
            shutil.rmtree(self._persist_path, ignore_errors=True)
        except Exception:
            # ignore_errors=True でも例外が出る場合があるため握る。
            # 削除しきれなくても後続の PersistentClient 生成を試みる価値があるため継続する。
            logger.warning(
                "ChromaDB永続領域の削除に失敗しました: %s", self._persist_path, exc_info=True
            )
        self._client = chromadb.PersistentClient(path=self._persist_path)
        self._collection = self._client.get_or_create_collection(name=self._collection_name)

    # -------- ベクトル登録 --------
    def register_texts(
        self,
        *,
        document_id: str,
        texts: Sequence[str],
        base_metadata: Optional[Dict[str, Any]] = None,
        per_chunk_metadata: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> List[str]:
        """
        複数チャンクのテキストをベクトル化し、コレクションに登録する。

        Args:
            document_id: 元ファイルを識別するID（パスなど）
            texts: チャンク済みテキスト群
            base_metadata: 全チャンク共通で付与するメタデータ
            per_chunk_metadata: 各チャンクに付与する追加メタデータ。
                ``texts`` と同じ長さのシーケンスを想定します。

        Returns:
            登録されたレコードIDのリスト
        """
        if not texts:
            return []

        if per_chunk_metadata is not None and len(per_chunk_metadata) != len(texts):
            raise ValueError(
                f"per_chunk_metadata length mismatch: {len(per_chunk_metadata)} != {len(texts)}"
            )

        ids = [f"{document_id}::chunk-{i}" for i in range(len(texts))]
        metadatas: List[Dict[str, Any]] = []
        base_metadata = dict(base_metadata or {})
        base_metadata.setdefault("document_id", document_id)

        for i, _text in enumerate(texts):
            md = dict(base_metadata)
            md["chunk_index"] = i
            if per_chunk_metadata is not None:
                md.update(dict(per_chunk_metadata[i]))
            metadatas.append(md)

        def _do_add() -> None:
            # 大きなドキュメントでも OpenAI の max_tokens_per_request を超えないよう、
            # 複数回に分けて埋め込みリクエストを行う。
            batch_size = self.EMBEDDING_BATCH_SIZE
            for start in range(0, len(texts), batch_size):
                end = start + batch_size
                batch_ids = ids[start:end]
                batch_texts = list(texts[start:end])
                batch_metadatas = metadatas[start:end]

                batch_embeddings = embedding.embed_texts(batch_texts)

                self._collection.add(
                    ids=batch_ids,
                    documents=batch_texts,
                    metadatas=batch_metadatas,
                    embeddings=batch_embeddings,
                )

        auto_reset = os.getenv("RAG_CHROMA_AUTO_RESET_ON_ERROR", "1") not in {"0", "false", "False"}
        try:
            _do_add()
        except InternalError as e:
            msg = str(e).lower()
            if auto_reset and ("hnsw" in msg or "compaction" in msg):
                logger.warning(
                    "chroma.add_failed_resetting",
                    extra={"event": "chroma.add_failed_resetting", "error": str(e), "persist_path": self._persist_path},
                )
                self._reset_chroma_storage()
                _do_add()
            else:
                raise

        return ids

    # -------- ベクトル検索 --------
    def search(
        self,
        query_text: str,
        *,
        top_k: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[VectorRecord]:
        """クエリテキストに対するベクトル検索を実行する。

        Args:
            query_text: 検索クエリのテキスト。
            top_k: 返す結果の最大件数（デフォルト: 10）。
            where: メタデータによるフィルタ条件（オプション）。

        Returns:
            List[VectorRecord]: 検索結果のリスト。距離の昇順でソートされます。

        Example:
            >>> store = VectorStoreAPI()
            >>> results = store.search("サンプルクエリ", top_k=5)
            >>> print(len(results))
            5
        """
        # 単一クエリでも embed_texts を使う（テスト時の monkeypatch と次元整合を保つため）。
        # embed_texts は内部で embed_text（LRUキャッシュ）を使うため、性能面でも問題ない。
        query_embedding = embedding.embed_texts([query_text])[0]

        def _do_query() -> List[VectorRecord]:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where,
            )

            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            records: List[VectorRecord] = []
            for _id, doc, md, dist in zip(ids, documents, metadatas, distances):
                records.append(
                    VectorRecord(
                        id=_id,
                        text=doc,
                        metadata=md or {},
                        distance=dist,
                    )
                )
            return records

        auto_reset = os.getenv("RAG_CHROMA_AUTO_RESET_ON_ERROR", "1") not in {"0", "false", "False"}
        try:
            return _do_query()
        except InternalError as e:
            msg = str(e).lower()
            if auto_reset and ("hnsw" in msg or "compaction" in msg or "index" in msg):
                logger.warning(
                    "chroma.search_failed_resetting",
                    extra={
                        "event": "chroma.search_failed_resetting",
                        "error": str(e),
                        "persist_path": self._persist_path,
                    },
                )
                self._reset_chroma_storage()
                return _do_query()
            else:
                raise

    # -------- ベクトル更新 --------
    def update_text(
        self,
        record_id: str,
        new_text: str,
        new_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """既存レコードのテキスト・メタデータを更新する。

        Args:
            record_id: 更新対象のレコードID。
            new_text: 新しいテキスト内容。
            new_metadata: 新しいメタデータ（オプション）。
                Noneの場合はメタデータは更新されません。

        Raises:
            Exception: レコードが見つからない場合、または更新に失敗した場合。
        """
        new_emb = embedding.embed_text(new_text)
        md = new_metadata or {}

        self._collection.update(
            ids=[record_id],
            documents=[new_text],
            metadatas=[md] if md else None,
            embeddings=[new_emb],
        )

    # -------- ベクトル削除 --------
    def delete(self, record_ids: Iterable[str]) -> None:
        """指定したIDのレコードを削除する。

        Args:
            record_ids: 削除対象のレコードIDのイテラブル。

        Example:
            >>> store = VectorStoreAPI()
            >>> store.delete(["doc1::chunk-0", "doc1::chunk-1"])
        """
        ids = list(record_ids)
        if not ids:
            return
        
        def _do_delete() -> None:
            self._collection.delete(ids=ids)
        
        auto_reset = os.getenv("RAG_CHROMA_AUTO_RESET_ON_ERROR", "1") not in {"0", "false", "False"}
        try:
            _do_delete()
        except InternalError as e:
            msg = str(e).lower()
            if auto_reset and ("hnsw" in msg or "compaction" in msg or "index" in msg):
                logger.warning(
                    "chroma.delete_failed_resetting",
                    extra={
                        "event": "chroma.delete_failed_resetting",
                        "error": str(e),
                        "persist_path": self._persist_path,
                        "num_ids": len(ids),
                    },
                )
                self._reset_chroma_storage()
                # リセット後は削除をスキップ（既にデータが消えているため）
                logger.info(
                    "chroma.delete_skipped_after_reset",
                    extra={
                        "event": "chroma.delete_skipped_after_reset",
                        "num_ids": len(ids),
                    },
                )
            else:
                raise



