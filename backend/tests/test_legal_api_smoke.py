import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api import legal as legal_api
from app.schemas.legal import ConsultationRiskRequest, RiskAnalysisRequest


class LegalApiSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_ask_route_returns_typed_legal_query_response(self):
        service = SimpleNamespace(
            route_legal_intent=AsyncMock(
                return_value={
                    "intent": "INTERNAL_RECALL",
                    "reasoning": "Grounded legal QA fits best.",
                    "suggested_tools": ["legal_rag_service.legal_query"],
                }
            ),
            smart_legal_query=AsyncMock(
                return_value={
                    "answer": "Penalty cap is limited by statute.",
                    "is_grounded": True,
                    "clauses": [
                        {
                            "clause_id": "c1",
                            "reference": "Article 301",
                            "text": "Penalty must not exceed 8%.",
                            "article": "Article 301",
                            "clause": "Clause 1",
                            "clause_type": "penalty",
                            "score": 0.91,
                            "retrieval_source": "vector",
                            "index_scope": "static",
                            "canonical_citation": "Luật Thương mại 2005",
                            "title": "Luật Thương mại 2005",
                        }
                    ],
                    "kg_context": "",
                    "domain": "legal",
                    "domain_confidence": 0.95,
                    "clause_type_filter": ["penalty"],
                    "article_filter": ["Article 301"],
                    "domain_signals": ["penalty", "article"],
                    "field_tags_filter": ["thuong_mai"],
                    "static_doc_types_filter": ["law"],
                    "rewritten_query": "What is the penalty cap?",
                }
            ),
        )

        with patch.object(legal_api, "_verify_workspace", AsyncMock(return_value=SimpleNamespace(id=1))), patch.object(
            legal_api, "_get_legal_service", return_value=service
        ):
            response = await legal_api.ask_legal_copilot(
                workspace_id=1,
                request=legal_api.LegalAskRequest(question="What is the penalty cap?"),
                db=SimpleNamespace(),
                current_user=SimpleNamespace(id=1),
            )

        self.assertEqual(response.intent, "INTERNAL_RECALL")
        self.assertTrue(response.is_grounded)
        self.assertEqual(response.evidence_overview.total_sources, 1)
        self.assertEqual(len(response.clauses), 1)

    async def test_review_summary_alias_reuses_analyze_risk(self):
        expected = legal_api.RiskAnalysisResponse(
            document_id=10,
            document_name="contract.docx",
            overall_risk_level="high",
            risks=[],
            parties_identified=[],
            governing_law="",
            summary="summary",
            missing_clauses=[],
        )

        with patch.object(legal_api, "analyze_contract_risk", AsyncMock(return_value=expected)):
            response = await legal_api.review_contract_summary(
                workspace_id=1,
                request=RiskAnalysisRequest(document_id=10),
                db=SimpleNamespace(),
                current_user=SimpleNamespace(id=1),
            )

        self.assertEqual(response.document_id, 10)
        self.assertEqual(response.summary, "summary")

    async def test_review_findings_alias_reuses_consult_risk(self):
        expected = legal_api.ConsultationRiskResponse(
            document_name="contract.docx",
            document_type="contract",
            findings=[],
            summary="review findings",
        )

        with patch.object(legal_api, "analyze_contract_consultation", AsyncMock(return_value=expected)):
            response = await legal_api.review_contract_findings(
                workspace_id=1,
                document_id=10,
                db=SimpleNamespace(),
                current_user=SimpleNamespace(id=1),
            )

        self.assertEqual(response.document_name, "contract.docx")
        self.assertEqual(response.summary, "review findings")
        self.assertIsInstance(response, legal_api.ConsultationRiskResponse)


if __name__ == "__main__":
    unittest.main()
