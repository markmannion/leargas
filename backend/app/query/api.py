"""POST /parse — debug endpoint: question -> structured query. Mount with app.include_router(router)."""

from fastapi import APIRouter
from pydantic import BaseModel

from .parser import parse
from .schema import ParseResult

router = APIRouter()


class ParseRequest(BaseModel):
    question: str
    use_llm: bool = True


@router.post("/parse", response_model=ParseResult)
def parse_endpoint(req: ParseRequest) -> ParseResult:
    return parse(req.question, use_llm=req.use_llm)
