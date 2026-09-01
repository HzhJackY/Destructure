from __future__ import annotations
from typing import Any, Optional
from metadata_registry import MetadataRegistry


class CaptureRepository:
    def __init__(self, registry: MetadataRegistry):
        self.registry = registry

    @staticmethod
    def _row(row) -> dict[str, Any]:
        d = dict(row)
        d['merge_ready'] = bool(d.get('merge_ready'))
        d['is_trashed'] = bool(d.get('is_trashed'))
        d['run_id'] = d.get('capture_id')
        d['run_dir'] = d.get('run_path')
        return d

    def get(self, capture_id: str) -> Optional[dict[str, Any]]:
        with self.registry.connect() as conn:
            row = conn.execute('SELECT * FROM captures WHERE capture_id=?', (str(capture_id),)).fetchone()
        return self._row(row) if row else None

    def get_many(self, capture_ids: list[str]) -> list[dict[str, Any]]:
        ids = list(map(str, capture_ids))
        if not ids:
            return []
        by: dict[str, dict[str, Any]] = {}
        # Stay below conservative SQLite host-parameter limits for large bulk selections.
        with self.registry.connect() as conn:
            for start in range(0, len(ids), 800):
                chunk = ids[start:start + 800]
                marks = ','.join('?' for _ in chunk)
                rows = conn.execute(
                    f'SELECT * FROM captures WHERE capture_id IN ({marks})',
                    tuple(chunk),
                ).fetchall()
                by.update({str(r['capture_id']): self._row(r) for r in rows})
        return [by[x] for x in ids if x in by]

    def list(
        self,
        *,
        lifecycle_status: Optional[str] = None,
        table_query_contains: Optional[str] = None,
        company_contains: Optional[str] = None,
        document_year: Optional[str] = None,
        producer_version: Optional[str] = None,
        batch_id: Optional[str] = None,
        research_batch_id: Optional[str] = None,
        include_trash: bool = False,
        only_trash: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where=[];params=[]
        if only_trash:
            where.append('(is_trashed=1 OR lifecycle_status=\'TRASHED\')')
        elif not include_trash:
            where.append('is_trashed=0 AND lifecycle_status<>\'TRASHED\'')
        if lifecycle_status and lifecycle_status != '全部':
            where.append('lifecycle_status=?');params.append(lifecycle_status)
        if table_query_contains:
            where.append('LOWER(COALESCE(table_query,\'\')) LIKE ?');params.append('%'+table_query_contains.lower()+'%')
        if company_contains:
            where.append('LOWER(COALESCE(company,\'\')) LIKE ?');params.append('%'+company_contains.lower()+'%')
        if document_year:
            where.append('document_year=?');params.append(str(document_year))
        if producer_version and producer_version != '全部':
            where.append('producer_version=?');params.append(str(producer_version))
        if batch_id:
            where.append('batch_id=?');params.append(str(batch_id))
        if research_batch_id:
            where.append("""EXISTS (
                SELECT 1 FROM research_batch_members rb
                WHERE rb.source_batch_id=captures.batch_id
                  AND rb.research_batch_id=? AND rb.status='ACTIVE'
            )""");params.append(str(research_batch_id))
        sql="""SELECT captures.*,
               (SELECT GROUP_CONCAT(DISTINCT rb.research_batch_id)
                  FROM research_batch_members rb
                 WHERE rb.source_batch_id=captures.batch_id
                   AND rb.status='ACTIVE') AS research_batch_ids
               FROM captures"""
        if where: sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY COALESCE(created_at,updated_at) DESC LIMIT ? OFFSET ?'
        params += [int(limit),int(offset)]
        with self.registry.connect() as conn:
            rows=conn.execute(sql,params).fetchall()
        return [self._row(r) for r in rows]

    def count(self, **filters) -> int:
        lifecycle_status=filters.get('lifecycle_status')
        table_query_contains=filters.get('table_query_contains')
        company_contains=filters.get('company_contains')
        document_year=filters.get('document_year')
        producer_version=filters.get('producer_version')
        batch_id=filters.get('batch_id')
        research_batch_id=filters.get('research_batch_id')
        include_trash=filters.get('include_trash',False)
        only_trash=filters.get('only_trash',False)
        where=[];params=[]
        if only_trash: where.append('(is_trashed=1 OR lifecycle_status=\'TRASHED\')')
        elif not include_trash: where.append('is_trashed=0 AND lifecycle_status<>\'TRASHED\'')
        if lifecycle_status and lifecycle_status!='全部': where.append('lifecycle_status=?');params.append(lifecycle_status)
        if table_query_contains: where.append('LOWER(COALESCE(table_query,\'\')) LIKE ?');params.append('%'+table_query_contains.lower()+'%')
        if company_contains: where.append('LOWER(COALESCE(company,\'\')) LIKE ?');params.append('%'+company_contains.lower()+'%')
        if document_year: where.append('document_year=?');params.append(str(document_year))
        if producer_version and producer_version!='全部': where.append('producer_version=?');params.append(str(producer_version))
        if batch_id: where.append('batch_id=?');params.append(str(batch_id))
        if research_batch_id:
            where.append("""EXISTS (
                SELECT 1 FROM research_batch_members rb
                WHERE rb.source_batch_id=captures.batch_id
                  AND rb.research_batch_id=? AND rb.status='ACTIVE'
            )""");params.append(str(research_batch_id))
        sql='SELECT COUNT(*) n FROM captures'+((' WHERE '+' AND '.join(where)) if where else '')
        with self.registry.connect() as conn:
            return int(conn.execute(sql,params).fetchone()['n'])


    def list_ids(
        self,
        *,
        lifecycle_status: Optional[str] = None,
        table_query_contains: Optional[str] = None,
        company_contains: Optional[str] = None,
        document_year: Optional[str] = None,
        producer_version: Optional[str] = None,
        batch_id: Optional[str] = None,
        research_batch_id: Optional[str] = None,
        include_trash: bool = False,
        only_trash: bool = False,
    ) -> list[str]:
        where=[];params=[]
        if only_trash:
            where.append("(is_trashed=1 OR lifecycle_status='TRASHED')")
        elif not include_trash:
            where.append("is_trashed=0 AND lifecycle_status<>'TRASHED'")
        if lifecycle_status and lifecycle_status != '全部':
            where.append('lifecycle_status=?');params.append(lifecycle_status)
        if table_query_contains:
            where.append("LOWER(COALESCE(table_query,'')) LIKE ?");params.append('%'+table_query_contains.lower()+'%')
        if company_contains:
            where.append("LOWER(COALESCE(company,'')) LIKE ?");params.append('%'+company_contains.lower()+'%')
        if document_year:
            where.append('document_year=?');params.append(str(document_year))
        if producer_version and producer_version != '全部':
            where.append('producer_version=?');params.append(str(producer_version))
        if batch_id:
            where.append('batch_id=?');params.append(str(batch_id))
        if research_batch_id:
            where.append("""EXISTS (
                SELECT 1 FROM research_batch_members rb
                WHERE rb.source_batch_id=captures.batch_id
                  AND rb.research_batch_id=? AND rb.status='ACTIVE'
            )""");params.append(str(research_batch_id))
        sql='SELECT capture_id FROM captures'
        if where: sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY COALESCE(created_at,updated_at) DESC'
        with self.registry.connect() as conn:
            rows=conn.execute(sql,params).fetchall()
        return [str(r['capture_id']) for r in rows]

    def distinct_values(self, column: str, *, include_trash: bool=False) -> list[str]:
        allowed={'lifecycle_status','table_query','company','document_year','producer_version','batch_id','header_parser'}
        if column not in allowed: raise ValueError(f'Unsupported distinct column: {column}')
        where='' if include_trash else " WHERE is_trashed=0 AND lifecycle_status<>'TRASHED'"
        with self.registry.connect() as conn:
            rows=conn.execute(f"SELECT DISTINCT {column} v FROM captures{where} AND {column} IS NOT NULL AND {column}<>'' ORDER BY {column}" if where else f"SELECT DISTINCT {column} v FROM captures WHERE {column} IS NOT NULL AND {column}<>'' ORDER BY {column}").fetchall()
        return [str(r['v']) for r in rows]

    def distinct_research_batches(self) -> list[str]:
        """Research batch is a relationship, not a duplicated Capture column."""
        with self.registry.connect() as conn:
            rows=conn.execute(
                """SELECT DISTINCT rb.research_batch_id v
                   FROM research_batch_members rb
                   JOIN captures c ON c.batch_id=rb.source_batch_id
                   WHERE rb.status='ACTIVE' AND c.is_trashed=0
                     AND c.lifecycle_status<>'TRASHED'
                   ORDER BY rb.research_batch_id"""
            ).fetchall()
        return [str(row["v"]) for row in rows if row["v"]]

    def run_paths(self, capture_ids: list[str]) -> list[str]:
        return [str(r['run_path']) for r in self.get_many(capture_ids)]

    def dependent_merges(self, capture_ids: list[str]) -> list[dict[str, Any]]:
        ids = list(map(str, capture_ids))
        if not ids:
            return []
        grouped: dict[str, dict[str, Any]] = {}
        with self.registry.connect() as conn:
            for start in range(0, len(ids), 800):
                chunk = ids[start:start + 800]
                marks = ','.join('?' for _ in chunk)
                rows = conn.execute(
                    f"""SELECT ms.capture_id, mp.merge_id, mp.run_path, mp.display_name, mp.dependency_status
                           FROM merge_sources ms
                           JOIN merge_projects mp ON mp.merge_id=ms.merge_id
                          WHERE ms.capture_id IN ({marks}) AND mp.is_trashed=0""",
                    tuple(chunk),
                ).fetchall()
                for r in rows:
                    d = grouped.setdefault(
                        str(r['merge_id']),
                        {
                            'merge_run_id': r['merge_id'],
                            'run_dir': r['run_path'],
                            'display_name': r['display_name'],
                            'capture_run_ids': [],
                        },
                    )
                    cid = str(r['capture_id'])
                    if cid not in d['capture_run_ids']:
                        d['capture_run_ids'].append(cid)
        return list(grouped.values())
