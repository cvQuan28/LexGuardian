import json
from pathlib import Path
from fastapi import APIRouter

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
DATA_DIR = Path(__file__).parent.parent.parent / "data"
EVAL_FILE = DATA_DIR / "ragas_history_eval.json"

@router.get("/")
def get_evaluations():
    """Retrieve the latest RAGAS evaluation results from history."""
    if not EVAL_FILE.exists():
        return {"evaluations": []}
    try:
        with open(EVAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e), "evaluations": []}
