"""Write the answer contract to contracts/ for Mark: JSON Schema + example answers.

    python backend/export_schema.py
"""
import json
from pathlib import Path

from app.schema import Answer, AskRequest

OUT = Path(__file__).resolve().parent.parent / "contracts"

EXAMPLES = [
    {
        "path": "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf",
        "question": "How many windows are shown on this floor plan?",
        "answer": 3, "unit": "count", "type": "count",
        "status": "verified", "confidence": 0.98, "source": "geometry_dxf",
        "evidence": [
            {"shape": {"kind": "polygon", "points": [[0.12, 0.30], [0.16, 0.30], [0.16, 0.31], [0.12, 0.31]]}, "page": 0, "label": "window", "source": "geometry_dxf"},
            {"shape": {"kind": "point", "point": [0.55, 0.12]}, "page": 0, "label": "window", "source": "gemma_ft"},
            {"shape": {"kind": "bbox", "bbox": [0.80, 0.40, 0.82, 0.48]}, "page": 0, "label": "window", "source": "geometry_dxf"},
        ],
        "explanation": "3 entities on the window layer.",
        "sources": [
            {"source": "geometry_dxf", "answer": 3, "unit": "count", "confidence": 0.98},
            {"source": "gemma_ft", "answer": 3, "unit": "count", "confidence": 0.7},
        ],
    },
    {
        "path": "data/cubicasa5k/colorful-10052.png",
        "question": "What is the total floor area of the bedrooms, in m²?",
        "answer": None, "unit": None, "type": "area",
        "status": "cannot_verify", "confidence": 0.1, "source": "gemma_ft",
        "evidence": [],
        "explanation": "No vector twin and no room labels legible on the scan.",
    },
]

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    (OUT / "answer.schema.json").write_text(json.dumps(Answer.model_json_schema(), indent=2) + "\n")
    (OUT / "ask_request.schema.json").write_text(json.dumps(AskRequest.model_json_schema(), indent=2) + "\n")
    for e in EXAMPLES:
        Answer.model_validate(e)
    (OUT / "answer.examples.json").write_text(json.dumps(EXAMPLES, indent=2, ensure_ascii=False) + "\n")
    print("wrote", *sorted(p.name for p in OUT.iterdir()))
