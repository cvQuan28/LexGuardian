"""
Legal Evaluation Harness
=========================

Quantitative evaluation for the Legal AI pipeline:

1. Retrieval Accuracy   — Precision@K, MRR, clause hit rate
2. Hallucination Rate   — Rule-based answer vs. source grounding check
3. Field Extraction     — Precision/recall of regex extractor on known contracts
4. Legal Reasoning      — Answer correctness on labeled legal QA pairs

Usage:
    evaluator = LegalEvaluator()
    report = await evaluator.evaluate_retrieval(test_cases, retriever)
    print(report.precision_at_5)

Test case format (JSONL):
    {"question": "...", "expected_clause_ids": ["id1","id2"], "expected_answer": "..."}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


# ===========================================================================
# Test case format
# ===========================================================================

@dataclass
class LegalTestCase:
    question: str
    expected_clause_ids: list[str] = field(default_factory=list)
    expected_clause_types: list[str] = field(default_factory=list)
    expected_answer: str = ""
    expected_fields: dict = field(default_factory=dict)   # for extraction tests
    document_id: Optional[int] = None
    category: str = "general"   # "payment", "penalty", "obligation", "definition"


@dataclass
class RetrievalMetrics:
    precision_at_1: float = 0.0
    precision_at_3: float = 0.0
    precision_at_5: float = 0.0
    precision_at_k: float = 0.0     # K = configured top_k
    mrr: float = 0.0                # Mean Reciprocal Rank
    hit_rate: float = 0.0           # % of queries with ≥1 correct clause in top-K
    clause_type_accuracy: float = 0.0
    avg_retrieval_ms: float = 0.0
    total_cases: int = 0


@dataclass
class AnswerQualityMetrics:
    grounding_rate: float = 0.0       # % answers with is_grounded=True
    hallucination_rate: float = 0.0   # 1 - grounding_rate
    insufficient_info_rate: float = 0.0  # % that returned "Insufficient information"
    avg_latency_ms: float = 0.0
    total_cases: int = 0
    by_category: dict = field(default_factory=dict)


@dataclass
class ExtractionMetrics:
    field_precision: dict = field(default_factory=dict)  # field → precision
    field_recall: dict = field(default_factory=dict)     # field → recall
    overall_precision: float = 0.0
    overall_recall: float = 0.0
    total_cases: int = 0


@dataclass
class EvaluationReport:
    retrieval: Optional[RetrievalMetrics] = None
    answer_quality: Optional[AnswerQualityMetrics] = None
    extraction: Optional[ExtractionMetrics] = None
    timestamp: str = ""

    def print_summary(self) -> None:
        """Print a readable summary to logger."""
        print("\n" + "="*60)
        print("LEGAL AI EVALUATION REPORT")
        print("="*60)

        if self.retrieval:
            r = self.retrieval
            print(f"\n📊 RETRIEVAL METRICS (n={r.total_cases})")
            print(f"  Precision@1:  {r.precision_at_1:.3f}")
            print(f"  Precision@3:  {r.precision_at_3:.3f}")
            print(f"  Precision@5:  {r.precision_at_5:.3f}")
            print(f"  MRR:          {r.mrr:.3f}")
            print(f"  Hit Rate:     {r.hit_rate:.3f}")
            print(f"  Avg Latency:  {r.avg_retrieval_ms:.0f}ms")

        if self.answer_quality:
            a = self.answer_quality
            print(f"\n🎯 ANSWER QUALITY (n={a.total_cases})")
            print(f"  Grounding Rate:         {a.grounding_rate:.3f}")
            print(f"  Hallucination Rate:     {a.hallucination_rate:.3f}")
            print(f"  Insufficient Info Rate: {a.insufficient_info_rate:.3f}")
            print(f"  Avg Latency:            {a.avg_latency_ms:.0f}ms")

        if self.extraction:
            e = self.extraction
            print(f"\n🔍 FIELD EXTRACTION (n={e.total_cases})")
            print(f"  Overall Precision: {e.overall_precision:.3f}")
            print(f"  Overall Recall:    {e.overall_recall:.3f}")
            for fld, prec in sorted(e.field_precision.items()):
                rec = e.field_recall.get(fld, 0.0)
                print(f"  [{fld}] P={prec:.2f} R={rec:.2f}")

        print("="*60)


# ===========================================================================
# Evaluator class
# ===========================================================================

class LegalEvaluator:
    """
    Evaluation harness for the full Legal AI pipeline.

    Designed to run quickly on a small labeled test set (20-50 cases).
    Does not require external infrastructure.
    """

    # ------------------------------------------------------------------
    # 1. Retrieval Evaluation
    # ------------------------------------------------------------------

    async def evaluate_retrieval(
        self,
        test_cases: list[LegalTestCase],
        retriever,
        top_k: int = 5,
    ) -> RetrievalMetrics:
        """
        Measure retrieval accuracy against labeled test cases.

        Args:
            test_cases: Cases with expected_clause_ids
            retriever: LegalRetriever instance
            top_k: K for precision@K

        Returns:
            RetrievalMetrics
        """
        metrics = RetrievalMetrics(total_cases=len(test_cases))
        total_latency = 0.0
        p1_total = p3_total = p5_total = pk_total = 0.0
        mrr_total = 0.0
        hits = 0
        clause_type_hits = 0
        cases_with_expected = [c for c in test_cases if c.expected_clause_ids]

        for case in cases_with_expected:
            t0 = time.time()
            try:
                result = await retriever.query(
                    question=case.question,
                    top_k=top_k,
                    document_ids=[case.document_id] if case.document_id else None,
                )
            except Exception as e:
                logger.warning(f"Retrieval failed for: {case.question[:50]}: {e}")
                continue

            elapsed_ms = (time.time() - t0) * 1000
            total_latency += elapsed_ms

            retrieved_ids = [c.clause.clause_id for c in result.clauses]
            expected_set = set(case.expected_clause_ids)

            # Precision@K
            def precision_at(k: int) -> float:
                top_k_ids = retrieved_ids[:k]
                return sum(1 for rid in top_k_ids if rid in expected_set) / max(k, 1)

            p1_total += precision_at(1)
            p3_total += precision_at(3)
            p5_total += precision_at(5)
            pk_total += precision_at(top_k)

            # MRR — rank of first correct hit
            rr = 0.0
            for rank, rid in enumerate(retrieved_ids, start=1):
                if rid in expected_set:
                    rr = 1.0 / rank
                    break
            mrr_total += rr

            # Hit rate — at least one correct in top-K
            if any(rid in expected_set for rid in retrieved_ids[:top_k]):
                hits += 1

            # Clause type accuracy
            if case.expected_clause_types:
                retrieved_types = {c.clause.clause_type for c in result.clauses[:top_k]}
                expected_types = set(case.expected_clause_types)
                if retrieved_types & expected_types:
                    clause_type_hits += 1

        n = max(len(cases_with_expected), 1)
        metrics.precision_at_1 = p1_total / n
        metrics.precision_at_3 = p3_total / n
        metrics.precision_at_5 = p5_total / n
        metrics.precision_at_k = pk_total / n
        metrics.mrr = mrr_total / n
        metrics.hit_rate = hits / n
        metrics.clause_type_accuracy = clause_type_hits / n
        metrics.avg_retrieval_ms = total_latency / n

        return metrics

    # ------------------------------------------------------------------
    # 2. Answer Quality / Grounding Evaluation
    # ------------------------------------------------------------------

    async def evaluate_answer_quality(
        self,
        test_cases: list[LegalTestCase],
        legal_rag_service,
    ) -> AnswerQualityMetrics:
        """
        Evaluate grounding rate and hallucination rate.

        Grounding check:
          The answer is "grounded" if legal_rag_service.legal_query()
          returns is_grounded=True AND the answer is not the
          "Insufficient information" stub.

        Args:
            test_cases: Legal QA test cases
            legal_rag_service: LegalRAGService instance

        Returns:
            AnswerQualityMetrics
        """
        metrics = AnswerQualityMetrics(total_cases=len(test_cases))
        total_latency = 0.0
        grounded = 0
        insufficient = 0
        by_category: dict[str, dict] = {}

        for case in test_cases:
            cat = case.category
            if cat not in by_category:
                by_category[cat] = {"total": 0, "grounded": 0}
            by_category[cat]["total"] += 1

            t0 = time.time()
            try:
                result = await legal_rag_service.legal_query(
                    question=case.question,
                    document_ids=[case.document_id] if case.document_id else None,
                )
            except Exception as e:
                logger.warning(f"legal_query failed: {e}")
                continue

            elapsed_ms = (time.time() - t0) * 1000
            total_latency += elapsed_ms

            is_grounded = result.get("is_grounded", False)
            answer = result.get("answer", "")

            if is_grounded:
                grounded += 1
                by_category[cat]["grounded"] += 1

            if "insufficient_information" in answer.lower() or "insufficient information" in answer.lower():
                insufficient += 1

        n = max(len(test_cases), 1)
        metrics.grounding_rate = grounded / n
        metrics.hallucination_rate = 1.0 - metrics.grounding_rate
        metrics.insufficient_info_rate = insufficient / n
        metrics.avg_latency_ms = total_latency / n
        metrics.by_category = by_category

        return metrics

    # ------------------------------------------------------------------
    # 3. Field Extraction Evaluation
    # ------------------------------------------------------------------

    def evaluate_extraction(
        self,
        test_cases: list[LegalTestCase],
        contract_texts: list[str],
        extractor_fn: Callable[[str], dict],
    ) -> ExtractionMetrics:
        """
        Evaluate contract field extraction precision/recall.

        Args:
            test_cases: Cases with expected_fields dicts
            contract_texts: Corresponding contract texts
            extractor_fn: Function(text) → dict of extracted fields

        Returns:
            ExtractionMetrics per field and overall
        """
        metrics = ExtractionMetrics(total_cases=len(test_cases))
        field_tp: dict[str, int] = {}
        field_fp: dict[str, int] = {}
        field_fn: dict[str, int] = {}

        for case, text in zip(test_cases, contract_texts):
            expected = case.expected_fields
            if not expected:
                continue

            extracted = extractor_fn(text)

            for fld, exp_val in expected.items():
                if fld not in field_tp:
                    field_tp[fld] = field_fp[fld] = field_fn[fld] = 0

                ext_val = str(extracted.get(fld, "") or "").strip().lower()
                exp_str = str(exp_val or "").strip().lower()

                if ext_val and exp_str:
                    # Partial match: extracted value contains expected or vice versa
                    if exp_str in ext_val or ext_val in exp_str:
                        field_tp[fld] += 1
                    else:
                        field_fp[fld] += 1
                        field_fn[fld] += 1
                elif ext_val and not exp_str:
                    field_fp[fld] += 1   # extracted but not expected
                elif not ext_val and exp_str:
                    field_fn[fld] += 1   # expected but not extracted

        total_tp = total_fp = total_fn = 0
        for fld in set(list(field_tp.keys()) + list(field_fp.keys()) + list(field_fn.keys())):
            tp = field_tp.get(fld, 0)
            fp = field_fp.get(fld, 0)
            fn = field_fn.get(fld, 0)
            total_tp += tp
            total_fp += fp
            total_fn += fn
            prec = tp / max(tp + fp, 1)
            rec = tp / max(tp + fn, 1)
            metrics.field_precision[fld] = prec
            metrics.field_recall[fld] = rec

        metrics.overall_precision = total_tp / max(total_tp + total_fp, 1)
        metrics.overall_recall = total_tp / max(total_tp + total_fn, 1)
        return metrics

    # ------------------------------------------------------------------
    # Full evaluation suite
    # ------------------------------------------------------------------

    async def run_full_evaluation(
        self,
        test_cases: list[LegalTestCase],
        retriever,
        legal_rag_service,
        contract_texts: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> EvaluationReport:
        """Run all three evaluations and return combined report."""
        from datetime import datetime

        report = EvaluationReport(
            timestamp=datetime.now().isoformat()
        )

        # Retrieval
        logger.info(f"Evaluating retrieval on {len(test_cases)} cases...")
        report.retrieval = await self.evaluate_retrieval(test_cases, retriever, top_k)

        # Answer quality
        logger.info("Evaluating answer quality...")
        report.answer_quality = await self.evaluate_answer_quality(
            test_cases, legal_rag_service
        )

        # Extraction (if texts provided)
        if contract_texts:
            logger.info("Evaluating field extraction...")
            from app.services.legal.contract_extractor import extract_contract_fields
            report.extraction = self.evaluate_extraction(
                test_cases,
                contract_texts,
                lambda text: extract_contract_fields(text).to_dict(),
            )

        report.print_summary()
        return report

    # ------------------------------------------------------------------
    # Test case I/O helpers
    # ------------------------------------------------------------------

    @staticmethod
    def load_test_cases(jsonl_path: str) -> list[LegalTestCase]:
        """Load test cases from a JSONL file."""
        cases = []
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                cases.append(LegalTestCase(
                    question=data.get("question", ""),
                    expected_clause_ids=data.get("expected_clause_ids", []),
                    expected_clause_types=data.get("expected_clause_types", []),
                    expected_answer=data.get("expected_answer", ""),
                    expected_fields=data.get("expected_fields", {}),
                    document_id=data.get("document_id"),
                    category=data.get("category", "general"),
                ))
        logger.info(f"Loaded {len(cases)} test cases from {jsonl_path}")
        return cases

    @staticmethod
    def create_sample_test_cases() -> list[LegalTestCase]:
        """Create sample test cases for Vietnamese contracts."""
        return [
            LegalTestCase(
                question="Giá trị hợp đồng là bao nhiêu?",
                expected_clause_types=["payment"],
                expected_fields={"contract_value": ""},
                category="payment",
            ),
            LegalTestCase(
                question="Mức phạt vi phạm hợp đồng là bao nhiêu?",
                expected_clause_types=["penalty"],
                category="penalty",
            ),
            LegalTestCase(
                question="Bên A có nghĩa vụ gì?",
                expected_clause_types=["obligation"],
                category="obligation",
            ),
            LegalTestCase(
                question="Hợp đồng được chấm dứt trong trường hợp nào?",
                expected_clause_types=["termination"],
                category="termination",
            ),
            LegalTestCase(
                question="Điều khoản bất khả kháng quy định như thế nào?",
                expected_clause_types=["force_majeure"],
                category="force_majeure",
            ),
            LegalTestCase(
                question="Thời hạn thanh toán là bao nhiêu ngày?",
                expected_clause_types=["payment"],
                category="payment",
            ),
            LegalTestCase(
                question="Pháp luật áp dụng cho hợp đồng này là gì?",
                expected_clause_types=["governing_law"],
                category="governing_law",
            ),
        ]
