"""
NexusRAG - Historical Evaluation with RAGAS
Fetches User -> Assistant pairs from chat_messages and evaluates quality.
"""

import asyncio
import json
import os
import argparse
import sys
import math
from pathlib import Path

# Adjust Python path
sys.path.append(str(Path(__file__).parent.parent))

from app.core.database import AsyncSessionLocal
from app.models.chat_message import ChatMessage
from sqlalchemy import select

DATA_DIR = Path(__file__).parent.parent / "data"
EVAL_FILE = DATA_DIR / "ragas_history_eval.json"

async def fetch_history_pairs(workspace_id: int = None, limit: int = 20):
    pairs = []
    async with AsyncSessionLocal() as db:
        query = select(ChatMessage).order_by(ChatMessage.workspace_id, ChatMessage.created_at.desc())
        if workspace_id:
            query = query.where(ChatMessage.workspace_id == workspace_id)
        
        result = await db.execute(query)
        messages = list(result.scalars().all())
        
        # Iterate to find an Assistant message with sources, then find its preceding User query.
        for i in range(len(messages) - 1):
            msg_curr = messages[i]
            msg_prev = messages[i+1] # older message since ordered by desc
            
            if msg_curr.role == "assistant" and msg_prev.role == "user":
                if msg_curr.workspace_id == msg_prev.workspace_id:
                    contexts = []
                    if msg_curr.sources:
                        contexts = [s.get("content", "") for s in msg_curr.sources if s.get("content")]
                    
                    if contexts:
                        pairs.append({
                            "question": msg_prev.content,
                            "answer": msg_curr.content,
                            "contexts": contexts,
                            "workspace_id": msg_curr.workspace_id,
                            "timestamp": msg_curr.created_at.isoformat(),
                            "id": msg_curr.message_id
                        })
                        if len(pairs) >= limit:
                            break
    return pairs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=int, help="Workspace ID to evaluate")
    parser.add_argument("--limit", type=int, default=20, help="Number of recent queries to eval")
    parser.add_argument("--gemini-key", type=str, help="Gemini API Key")
    args = parser.parse_args()
    
    gemini_key = args.gemini_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_AI_API_KEY")
    if not gemini_key:
        print("ERROR: --gemini-key required or set GOOGLE_AI_API_KEY / GOOGLE_API_KEY in environment.")
        sys.exit(1)
        
    os.environ["GOOGLE_API_KEY"] = gemini_key

    print(f"Fetching up to {args.limit} historical pairs...")
    pairs = asyncio.run(fetch_history_pairs(args.workspace, args.limit))
    
    if not pairs:
        print("No historical pairs found with retrieved contexts.")
        sys.exit(0)
        
    print(f"Found {len(pairs)} interactions. Running RAGAS...")

    try:
        from ragas import evaluate, EvaluationDataset
        from ragas.llms import llm_factory
        from google import genai
        
        try:
            from ragas.metrics import AnswerRelevancy as Relevancy
        except ImportError:
            from ragas.metrics import ResponseRelevancy as Relevancy
            
        from ragas.metrics import Faithfulness, ContextPrecision

        client = genai.Client(api_key=gemini_key)
        evaluator_llm = llm_factory("gemini-2.0-flash", provider="google", client=client)

        eval_samples = []
        for p in pairs:
            eval_samples.append({
                "user_input": p["question"],
                "response": p["answer"],
                "retrieved_contexts": p["contexts"],
                "reference": p["answer"], # To bypass context_precision requirement if needed
                "id": p["id"],
                "timestamp": p["timestamp"]
            })
            
        dataset = EvaluationDataset.from_list(eval_samples)
        
        metrics = [
            Faithfulness(llm=evaluator_llm),
            Relevancy(llm=evaluator_llm),
            ContextPrecision(llm=evaluator_llm),
        ]
        
        result = evaluate(dataset=dataset, metrics=metrics, llm=evaluator_llm)
        df = result.to_pandas()
        
        output_results = []
        for index, row in df.iterrows():
            output_results.append({
                "id": eval_samples[index]["id"],
                "timestamp": eval_samples[index]["timestamp"],
                "question": eval_samples[index]["user_input"],
                "answer_preview": eval_samples[index]["response"][:100] + "...",
                "faithfulness": 0 if math.isnan(float(row.get("faithfulness", 0))) else float(row.get("faithfulness", 0)),
                "answer_relevancy": 0 if math.isnan(float(row.get("answer_relevancy", row.get("response_relevancy", 0)))) else float(row.get("answer_relevancy", row.get("response_relevancy", 0))),
                "context_precision": 0 if math.isnan(float(row.get("context_precision", 0))) else float(row.get("context_precision", 0))
            })
            
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(EVAL_FILE, "w", encoding="utf-8") as f:
            json.dump({"evaluations": output_results}, f, indent=2, ensure_ascii=False)
            
        print(f"Evaluations completed and saved to {EVAL_FILE}")
        
    except ImportError as e:
        print(f"Failed to import Ragas. Please ensure ragas is installed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
