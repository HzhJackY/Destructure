"""Structured, idempotent review issues and tasks for Capture Versions."""
from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any

from metadata_registry import now_iso
from final_data_review import review_final_data_columns


TASK_TYPES=(
    "SOURCE_IDENTITY_REVIEW","PDF_BOUNDARY_REVIEW","TABLE_BLOCK_REVIEW",
    "HEADER_TOPOLOGY_REVIEW","ROW_STRUCTURE_REVIEW","FINAL_DATA_COLUMN_REVIEW",
    "UNIT_SCOPE_PERIOD_REVIEW","RECONCILIATION_REVIEW","FINAL_CERTIFICATION",
)

ISSUE_CATALOG={
    "RESEARCH_DEFINITION_MISSING":("研究定义缺失","该版本未关联可复现的研究定义。","关联 Research Definition。","SOURCE_IDENTITY_REVIEW"),
    "DEFINITION_VERSION_MISSING":("定义版本缺失","研究定义没有明确版本，结果不可复现。","选择并保存 Definition Version。","SOURCE_IDENTITY_REVIEW"),
    "TABLE_FAMILY_MISSING":("表族缺失","该 Capture 未关联正式 Table Family。","选择与证据一致的表族。","SOURCE_IDENTITY_REVIEW"),
    "STATEMENT_SCOPE_UNKNOWN":("报表口径未识别","合并或母公司口径尚未确认。","在结构化口径控件中确认 Scope。","UNIT_SCOPE_PERIOD_REVIEW"),
    "NON_CURRENT_CAPTURE":("当前查看的不是活动版本","该 Capture Version 不是 Logical Asset 的 current。","查看替代链路并切换到 current。","SOURCE_IDENTITY_REVIEW"),
    "ORPHAN_NON_CURRENT_VERSION":("非当前版本缺少替代链路","is_current=false，但没有 supersedes/superseded_by 记录。","通过 CaptureVersionService 修复 lineage。","SOURCE_IDENTITY_REVIEW"),
    "HEADER_TOPOLOGY_AMBIGUOUS":("表头拓扑需要复核","机器未能唯一确定表头层级。","前往表头拓扑，确认候选或创建结构修订。","HEADER_TOPOLOGY_REVIEW"),
    "HEADER_PERIOD_MAPPING_AMBIGUOUS":("期间列映射不明确","数据年度与表头列的对应关系存在歧义。","逐列确认 data_year 与 period_type。","HEADER_TOPOLOGY_REVIEW"),
    "LAST_COLUMN_MAPPING_UNCERTAIN":("最后一列映射不确定","最右侧 Header 与数据 token 未形成稳定对应。","前往最终数据复核检查末列。","FINAL_DATA_COLUMN_REVIEW"),
    "ROW_STRUCTURE_AMBIGUOUS":("行结构需要复核","父子行、层级或行角色存在歧义。","前往行结构确认。","ROW_STRUCTURE_REVIEW"),
    "IMPLICIT_TOTAL_UNCERTIFIED":("隐式合计尚未认证","Required 派生合计行尚未确认，阻断合表。","确认或拒绝 IMPLICIT_TOTAL。","ROW_STRUCTURE_REVIEW"),
    "IMPLICIT_TOTAL_UNCERTIFIED_NON_BLOCKING":("隐式合计未认证（不阻断）","可选派生合计尚未确认，不影响来源行认证与合表。","可选: 验证或排除派生行。","ROW_STRUCTURE_REVIEW"),
    "DERIVED_OBSERVATION_WARNING":("派生观察值需审核","存在自动推导的隐式合计或匿名数值行。","审核派生行，可选择接受或排除。","ROW_STRUCTURE_REVIEW"),
    "NUMERIC_TOKEN_ORIGIN_AMBIGUOUS":("数值 token 来源可疑","年份或日期可能进入金额列。","核对原始 bbox 和金额列。","FINAL_DATA_COLUMN_REVIEW"),
    "UNIT_UNCERTAIN":("单位不确定","文档单位继承或列单位未确认。","确认单位及上下文来源页。","UNIT_SCOPE_PERIOD_REVIEW"),
    "PERIOD_COLUMN_SWAP_RISK":("当期与上期可能交换","数据列顺序与期间顺序不一致。","逐列确认数据年度。","FINAL_DATA_COLUMN_REVIEW"),
    "VALUE_COLUMN_COUNT_MISMATCH":("数值列数量不一致","部分行的数值 token 数与 Header 数据列数不同。","检查漏列、错位或污染 token。","FINAL_DATA_COLUMN_REVIEW"),
    "RECONCILIATION_WARNING":("勾稽关系警告","表内或跨表勾稽未通过。","查看差额和容差证据。","RECONCILIATION_REVIEW"),
    "RECONCILIATION_MISMATCH":("勾稽不一致","合计与明细之和超出容差，属于已证实的数值不一致，需人工复核后才能合表。","查看差额与容差证据。","RECONCILIATION_REVIEW"),
    "SOURCE_IDENTITY_MISSING":("来源身份缺失","PDF、页码或来源主表身份不完整。","补齐来源身份后再认证。","SOURCE_IDENTITY_REVIEW"),
    "BLOCK_SEGMENTATION_AMBIGUOUS":("表块分割需要复核","Note Container 中的表块边界或角色不确定。","前往附注容器与表块处理。","TABLE_BLOCK_REVIEW"),
    "PDF_BOUNDARY_UNCERTAIN":("整表末尾边界需要复核","机器未找到可信的下一同级附注标题，可能包含页脚或下一段内容。","在附注容器与表块中确认最后一条有效行。","PDF_BOUNDARY_REVIEW"),
    "BOUNDARY_AUTO_ACCEPTED_WITH_WARNING":("自动边界闭合（存在低风险警告）","边界已自动闭合，但存在需注意的低风险不确定性（如同附注不同表块）。","可选：在附注容器中复查表块划分。","PDF_BOUNDARY_REVIEW"),
    "CANONICAL_OUTPUT_INCOMPLETE":("Canonical 输出不完整","机器结果无法形成完整观察值。","检查表头、行和最终数据列。","FINAL_DATA_COLUMN_REVIEW"),
    "LEGACY_REVIEW_REASON_MISSING":("历史复核原因缺失","旧数据只有 REVIEW_REQUIRED 总状态，没有可解释原因。","人工检查全部必需审核任务。","FINAL_CERTIFICATION"),
    "RESEARCH_DEFINITION_MISMATCH":("研究定义不一致","Capture 固定的研究定义与决策输入不一致。","核对并生成正确身份的新 Capture Version。","SOURCE_IDENTITY_REVIEW"),
    "DEFINITION_VERSION_MISMATCH":("研究定义版本不一致","Capture 固定的 Definition Version 与决策输入不一致。","核对并固定正确 Definition Version。","SOURCE_IDENTITY_REVIEW"),
    "REGISTRATION_INCOMPLETE":("Capture 注册未完成","Capture 尚未完成正式 Registry 注册。","修复注册事务后重新执行状态决策。","SOURCE_IDENTITY_REVIEW"),
    "LIFECYCLE_NOT_ACTIVE":("Capture 生命周期不可用","Capture 已失效、归档、回收或被替代。","切换到 current active Capture Version。","SOURCE_IDENTITY_REVIEW"),
    "IMPLICIT_ROW_UNRESOLVED":("匿名数值行尚未解决","存在仍需恢复或排除的匿名数值候选行。","在行结构审核中处理该来源行。","ROW_STRUCTURE_REVIEW"),
}


def _load_result(run_path:str)->dict[str,Any]:
    path=Path(str(run_path or ""))/"table_capture_result.json"
    if not path.is_file(): return {}
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError):return {}


class ReviewTaskService:
    def __init__(self,repository,producer_version:str="v6.9-hotfix-anchor-review"):
        self.repo=repository; self.registry=repository.registry; self.producer_version=producer_version

    def _derive_codes(self,detail:dict[str,Any],result:dict[str,Any])->list[tuple[str,dict[str,Any]]]:
        from services.capture_decision_reducer import CaptureDecisionReducer
        decision = CaptureDecisionReducer().reduce(
            machine_evidence=result,
            capture_version=detail,
            lifecycle_state=detail,
            rule_version=self.producer_version,
        )
        return self._codes_from_decision(decision)

    @staticmethod
    def _codes_from_decision(decision)->list[tuple[str,dict[str,Any]]]:
        evidence = dict(getattr(decision, "decision_evidence", {}) or {})
        return [
            (str(code), {"decision_evidence": evidence})
            for code in (
                list(getattr(decision, "blocking_issues", []) or [])
                + list(getattr(decision, "non_blocking_warnings", []) or [])
            )
        ]

    def _materialize_in_tx(
        self, conn, *, capture_id: str, detail: dict[str, Any],
        result: dict[str, Any], decision,
        stale_resolution_decision: str | None = None,
    )->dict[str,Any]:
        codes=self._codes_from_decision(decision)
        now=now_iso()
        # A deterministic recheck may prove an earlier machine warning was
        # false. Keep history but remove it from the active set.
        active_codes={code for code,_ in codes}
        stale=conn.execute(
            """SELECT review_issue_id,reason_code FROM review_issues
               WHERE capture_version_id=? AND status='OPEN'""",
            (capture_id,),
        ).fetchall()
        for issue in stale:
            if (
                str(issue["reason_code"]) in ISSUE_CATALOG
                and str(issue["reason_code"]) not in active_codes
            ):
                conn.execute(
                    """UPDATE review_issues
                       SET status='RESOLVED',resolved_at=?,reviewer=?,
                           decision=?
                       WHERE review_issue_id=?""",
                    (
                        now,
                        "SYSTEM_RULE_UPGRADE"
                        if stale_resolution_decision
                        else "SYSTEM_RECHECK",
                        stale_resolution_decision
                        or "MACHINE_RECHECK_CLEARED",
                        issue["review_issue_id"],
                    ),
                )
        for code,evidence in codes:
            title,description,action,task_type=ISSUE_CATALOG.get(
                code,
                (
                    "结构化质量门需要复核",
                    f"状态决策产生未登记原因：{code}",
                    "在最终认证前核对机器证据。",
                    "FINAL_CERTIFICATION",
                ),
            )
            non_blocking_codes = {
                "IMPLICIT_TOTAL_UNCERTIFIED_NON_BLOCKING",
                "DERIVED_OBSERVATION_WARNING",
                "BOUNDARY_AUTO_ACCEPTED_WITH_WARNING",
                "ANONYMOUS_NUMERIC_ROW_PRESENT",
                "RECONCILIATION_WARNING",
            }
            if code in non_blocking_codes:
                severity = "LOW"
                blocking = 0
            else:
                severity = "HIGH"
                blocking = 1
            key=f"{capture_id}::{task_type}::{code}::"
            conn.execute(
                """INSERT INTO review_issues(
                   review_issue_id,capture_version_id,table_block_id,review_task_type,
                   reason_code,human_title,human_description,severity,blocking,
                   affected_object_type,affected_object_id,evidence_json,recommended_action,
                   source_quality_gate,status,derivation_key,migration_version,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,'CAPTURE_VERSION',?,?,?,?,'OPEN',?,?,?)
                   ON CONFLICT(derivation_key) DO UPDATE SET
                   human_title=excluded.human_title,human_description=excluded.human_description,
                   severity=excluded.severity,blocking=excluded.blocking,
                   evidence_json=excluded.evidence_json,
                   recommended_action=excluded.recommended_action""",
                ("RISSUE_"+uuid.uuid4().hex,capture_id,None,task_type,code,title,description,
                 severity,blocking,capture_id,json.dumps(evidence,ensure_ascii=False),action,code,
                 key,self.producer_version,now),
            )
        open_issues=conn.execute(
            "SELECT * FROM review_issues WHERE capture_version_id=? AND status='OPEN'",
            (capture_id,),
        ).fetchall()
        grouped={task:[] for task in TASK_TYPES}
        for row in open_issues:grouped[str(row["review_task_type"])].append(dict(row))
        for task_type in TASK_TYPES:
            issues=grouped[task_type]
            blocking_issues=[issue for issue in issues if bool(issue["blocking"])]
            required=task_type=="FINAL_CERTIFICATION" or bool(issues)
            status="PENDING" if issues or task_type=="FINAL_CERTIFICATION" else "NOT_REQUIRED"
            if str(getattr(decision, "review_status", "")) in {
                "CONFIRMED_AUTO","CONFIRMED_HUMAN","CONFIRMED_OVERRIDE",
            }:
                status="CONFIRMED" if required else "NOT_REQUIRED"
            conn.execute(
                """INSERT INTO review_tasks(
                   task_id,capture_version_id,task_type,required,status,reason_codes_json,
                   severity,blocking,affected_rows_json,affected_columns_json,evidence_json,
                   recommended_action,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(capture_version_id,task_type) DO UPDATE SET
                   required=excluded.required,
                   status=CASE WHEN review_tasks.status IN ('CONFIRMED','OVERRIDDEN','REJECTED','UNRESOLVED')
                               THEN review_tasks.status ELSE excluded.status END,
                   reason_codes_json=excluded.reason_codes_json,severity=excluded.severity,
                   blocking=excluded.blocking,evidence_json=excluded.evidence_json,
                   recommended_action=excluded.recommended_action,updated_at=excluded.updated_at""",
                ("RTASK_"+uuid.uuid4().hex,capture_id,task_type,int(required),status,
                 json.dumps([x["reason_code"] for x in issues],ensure_ascii=False),
                 max([x["severity"] for x in issues],default="INFO"),
                 int(bool(blocking_issues)),
                 "[]","[]",json.dumps([json.loads(x["evidence_json"] or "{}") for x in issues],ensure_ascii=False),
                 "；".join(x["recommended_action"] for x in issues),now,now),
            )
        if (
            stale_resolution_decision
            and not grouped.get("PDF_BOUNDARY_REVIEW")
        ):
            conn.execute(
                """UPDATE review_tasks
                   SET required=0,blocking=0,status='NOT_REQUIRED',updated_at=?
                   WHERE capture_version_id=?
                     AND task_type='PDF_BOUNDARY_REVIEW'""",
                (now,capture_id),
            )

        blocking_rows=[
            dict(row) for row in open_issues if bool(row["blocking"])
        ]
        if bool(getattr(decision, "review_inbox_eligible", False)) and blocking_rows:
            primary=blocking_rows[0]
            secondary=[str(row["reason_code"]) for row in blocking_rows[1:]]
            review_id="REVIEW_"+uuid.uuid4().hex
            conn.execute(
                """INSERT INTO review_queue(
                   review_item_id,logical_asset_id,capture_id,primary_review_reason,
                   secondary_review_reasons_json,severity,recommended_action,
                   evidence_summary_json,status,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,'PENDING',?,?)
                   ON CONFLICT(capture_id) DO UPDATE SET
                   primary_review_reason=excluded.primary_review_reason,
                   secondary_review_reasons_json=excluded.secondary_review_reasons_json,
                   severity=excluded.severity,recommended_action=excluded.recommended_action,
                   evidence_summary_json=excluded.evidence_summary_json,status='PENDING',
                   updated_at=excluded.updated_at""",
                (
                    review_id,detail["logical_asset_id"],capture_id,
                    primary["reason_code"],json.dumps(secondary,ensure_ascii=False),
                    "HIGH" if any(row["severity"]=="HIGH" for row in blocking_rows) else "MEDIUM",
                    primary["recommended_action"],
                    json.dumps(
                        {
                            "review_issue_ids":[row["review_issue_id"] for row in blocking_rows],
                            "producer":self.producer_version,
                        },
                        ensure_ascii=False,
                    ),
                    now,now,
                ),
            )
        else:
            conn.execute(
                """UPDATE review_queue SET status='RESOLVED',updated_at=?
                   WHERE capture_id=? AND status='PENDING'""",
                (now,capture_id),
            )

        conn.execute(
            "UPDATE captures SET merge_ready=?,updated_at=? WHERE capture_id=?",
            (int(bool(getattr(decision, "merge_eligible", False))),now,capture_id),
        )
        return self._summary_in_tx(conn,capture_id,result=result)

    def materialize_decision_in_tx(
        self, conn, *, capture_id: str, detail: dict[str, Any],
        result: dict[str, Any], decision,
        stale_resolution_decision: str | None = None,
    )->dict[str,Any]:
        """Persist reducer-derived issues/tasks/queue in the caller transaction."""
        return self._materialize_in_tx(
            conn,capture_id=capture_id,detail=detail,result=result,
            decision=decision,
            stale_resolution_decision=stale_resolution_decision,
        )

    def materialize(self,capture_id:str)->dict[str,Any]:
        """Explicit migration/reassessment entry point; never call from render."""
        detail=self.repo.capture_detail(capture_id)
        if not detail:raise KeyError(capture_id)
        result=_load_result(detail.get("run_path"))
        from services.capture_decision_reducer import CaptureDecisionReducer
        decision=CaptureDecisionReducer().reduce(
            machine_evidence=result,capture_version=detail,
            lifecycle_state=detail,rule_version=self.producer_version,
        )
        with self.registry.connect() as conn:
            return self._materialize_in_tx(
                conn,capture_id=capture_id,detail=detail,result=result,
                decision=decision,
            )

    def summary(self,capture_id:str,*,result:dict[str,Any]|None=None)->dict[str,Any]:
        with self.registry.connect() as conn:
            if result is None:
                detail=self.repo.capture_detail(capture_id) or {}
                result=_load_result(detail.get("run_path"))
            return self._summary_in_tx(conn,capture_id,result=result)

    def _summary_in_tx(
        self,conn,capture_id:str,*,result:dict[str,Any]|None=None,
    )->dict[str,Any]:
        issues=[dict(x) for x in conn.execute(
            "SELECT * FROM review_issues WHERE capture_version_id=? AND status='OPEN' ORDER BY severity DESC,created_at",
            (capture_id,),
        ).fetchall()]
        tasks=[dict(x) for x in conn.execute(
            "SELECT * FROM review_tasks WHERE capture_version_id=? ORDER BY rowid",
            (capture_id,),
        ).fetchall()]
        for issue in issues: issue["evidence"]=json.loads(issue.pop("evidence_json") or "{}")
        for task in tasks:
            task["reason_codes"]=json.loads(task.pop("reason_codes_json") or "[]")
            task["evidence"]=json.loads(task.pop("evidence_json") or "[]")
        completed=sum(x["status"] in {"CONFIRMED","OVERRIDDEN","NOT_REQUIRED"} for x in tasks if x["task_type"]!="FINAL_CERTIFICATION")
        denominator=sum(x["task_type"]!="FINAL_CERTIFICATION" for x in tasks)
        blockers=[x for x in tasks if x["task_type"]!="FINAL_CERTIFICATION" and x["required"] and x["blocking"] and x["status"] not in {"CONFIRMED","OVERRIDDEN","NOT_REQUIRED"}]
        return {"issues":issues,"tasks":tasks,"completed":completed,"total":denominator,
                "can_final_confirm":not blockers,"blocking_tasks":blockers,
                "final_data_review":review_final_data_columns(result or {})}

    def decide_task(self,capture_id:str,task_type:str,decision:str,*,reviewer:str="local_user",
                    reason:str="",evidence:dict[str,Any]|None=None)->dict[str,Any]:
        decision=decision.upper()
        if decision not in {"CONFIRMED","OVERRIDDEN","REJECTED","UNRESOLVED"}:raise ValueError(decision)
        if decision=="OVERRIDDEN" and not str(reason).strip():
            raise ValueError("OVERRIDE_REASON_REQUIRED")
        now=now_iso()
        with self.registry.connect() as conn:
            task=conn.execute(
                "SELECT task_id,status FROM review_tasks WHERE capture_version_id=? AND task_type=?",
                (capture_id,task_type),
            ).fetchone()
            if not task:raise KeyError(f"{capture_id}:{task_type}")
            conn.execute(
                "UPDATE review_tasks SET status=?,reviewer=?,decision=?,updated_at=? WHERE capture_version_id=? AND task_type=?",
                (decision,reviewer,decision,now,capture_id,task_type),
            )
            conn.execute(
                """UPDATE review_issues SET status=CASE WHEN ? IN ('CONFIRMED','OVERRIDDEN') THEN 'RESOLVED' ELSE ? END,
                   resolved_at=?,reviewer=?,decision=?
                   WHERE capture_version_id=? AND review_task_type=? AND status='OPEN'""",
                (decision,decision,now,reviewer,decision,capture_id,task_type),
            )
            conn.execute(
                """INSERT INTO review_task_decisions(
                   decision_id,capture_version_id,task_id,task_type,previous_status,new_status,
                   reviewer,reason,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("RTDEC_"+uuid.uuid4().hex,capture_id,task["task_id"],task_type,
                 task["status"],decision,reviewer,str(reason or ""),
                 json.dumps(evidence or {},ensure_ascii=False),now),
            )
        return self.summary(capture_id)

    def reassess_stale_boundary_issues(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Controlled reassessment of historical ``PDF_BOUNDARY_UNCERTAIN`` issues.

        Queries all OPEN boundary issues, re-runs :func:`derive_boundary_decision`
        against the current rule set, and resolves any that now meet auto-closure
        criteria.  Issues are marked ``RESOLVED_BY_RULE_UPGRADE`` — never deleted
        — and dependent review tasks, capture quality_status, and inbox entries
        are recalculated.

        Returns counts of affected objects.
        """
        from services.capture_completion_service import CaptureCompletionService

        stats_out = {
            "total_boundary_issues": 0,
            "resolved_by_rule_upgrade": 0,
            "still_require_review": 0,
            "captures_quality_upgraded": 0,
            "inbox_entries_cleared": 0,
            "review_tasks_recalculated": 0,
        }

        with self.registry.connect() as conn:
            stale = conn.execute(
                """SELECT review_issue_id, capture_version_id, reason_code
                   FROM review_issues
                   WHERE reason_code = 'PDF_BOUNDARY_UNCERTAIN' AND status = 'OPEN'"""
            ).fetchall()
        stats_out["total_boundary_issues"] = len(stale)

        capture_ids = {str(row["capture_version_id"]) for row in stale}
        completion = CaptureCompletionService(
            governance_repository=self.repo,
            review_task_service=self,
            producer_version=self.producer_version,
        )

        for capture_id in capture_ids:
            detail = self.repo.capture_detail(capture_id)
            if not detail:
                continue
            result = _load_result(detail.get("run_path"))
            if not result:
                continue

            active_codes = {
                code for code,_ in self._derive_codes(detail,result)
            }
            if "PDF_BOUNDARY_UNCERTAIN" in active_codes:
                stats_out["still_require_review"] += sum(
                    1 for row in stale
                    if str(row["capture_version_id"]) == capture_id
                )
                continue

            if dry_run:
                stats_out["resolved_by_rule_upgrade"] += sum(
                    1 for row in stale
                    if str(row["capture_version_id"]) == capture_id
                )
                continue

            with self.registry.connect() as conn:
                pending_before = conn.execute(
                    """SELECT COUNT(*) n FROM review_queue
                       WHERE capture_id=? AND status='PENDING'""",
                    (capture_id,),
                ).fetchone()["n"]
            before_quality = str(detail.get("quality_status") or "")
            outcome = completion.complete(
                capture_id=capture_id,
                machine_evidence=result,
                metadata=detail,
                capture_record=detail,
                research_definition={
                    "definition_id": detail.get("research_definition_id"),
                    "definition_version": detail.get("definition_version"),
                },
                stale_resolution_decision="RESOLVED_BY_RULE_UPGRADE",
            )
            with self.registry.connect() as conn:
                resolved_count = conn.execute(
                    """SELECT COUNT(*) n FROM review_issues
                       WHERE capture_version_id=?
                         AND reason_code='PDF_BOUNDARY_UNCERTAIN'
                         AND status='RESOLVED'
                         AND decision='RESOLVED_BY_RULE_UPGRADE'""",
                    (capture_id,),
                ).fetchone()["n"]
                pending_after = conn.execute(
                    """SELECT COUNT(*) n FROM review_queue
                       WHERE capture_id=? AND status='PENDING'""",
                    (capture_id,),
                ).fetchone()["n"]
            stats_out["resolved_by_rule_upgrade"] += resolved_count
            if not resolved_count:
                stats_out["still_require_review"] += sum(
                    1 for row in stale
                    if str(row["capture_version_id"]) == capture_id
                )
            stats_out["review_tasks_recalculated"] += 1
            if (
                before_quality != "READY"
                and outcome["decision"].quality_status == "READY"
            ):
                stats_out["captures_quality_upgraded"] += 1
            stats_out["inbox_entries_cleared"] += max(
                0,int(pending_before)-int(pending_after)
            )

        return stats_out

    def validate_final_confirm(self,capture_id:str)->dict[str,Any]:
        summary=self.materialize(capture_id)
        if not summary["can_final_confirm"]:
            raise PermissionError("FINAL_CONFIRM_BLOCKED:"+",".join(x["task_type"] for x in summary["blocking_tasks"]))
        detail=self.repo.capture_detail(capture_id) or {}
        missing=[]
        for field in ("research_definition_id","definition_version","table_family_id"):
            if not str(detail.get(field) or "").strip():missing.append(field)
        if str(detail.get("statement_scope") or "UNKNOWN").upper() in {"","UNKNOWN","NONE"}:
            missing.append("statement_scope")
        if not detail.get("is_current"):
            missing.append("current_capture")
        if missing:
            raise PermissionError("FINAL_CONFIRM_IDENTITY_INCOMPLETE:"+",".join(missing))
        return summary

    def backfill(self)->dict[str,int]:
        with self.registry.connect() as conn:
            ids=[x["capture_id"] for x in conn.execute(
                "SELECT capture_id FROM capture_versions WHERE quality_status='REVIEW_REQUIRED'"
            ).fetchall()]
            before=conn.execute("SELECT COUNT(*) n FROM review_issues").fetchone()["n"]
        for capture_id in ids:self.materialize(str(capture_id))
        with self.registry.connect() as conn:
            after=conn.execute("SELECT COUNT(*) n FROM review_issues").fetchone()["n"]
            legacy=conn.execute("SELECT COUNT(*) n FROM review_issues WHERE reason_code='LEGACY_REVIEW_REASON_MISSING'").fetchone()["n"]
        return {"review_required_captures":len(ids),"issues_added":after-before,
                "legacy_reason_missing":legacy}
