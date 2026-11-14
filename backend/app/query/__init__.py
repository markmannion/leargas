"""Question -> structured query. Use `parse(question)`; mount `api.router` for POST /parse."""

from .parser import parse
from .schema import ParseResult, Query

__all__ = ["parse", "ParseResult", "Query"]
