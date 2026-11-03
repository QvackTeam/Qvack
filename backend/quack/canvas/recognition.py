"""Output schema of the `recognizer@1` role for a canvas line (ТЗ Ф4 WP21.3, S8; Т-§15.3, Т-§22.7).

The API renders the strokes of a finished line into an image and sends it to `recognizer` (Spark
with an image, class P0, called by the WebSocket handler directly, without a queue). The model
reads the line: LaTeX or text (`canvas.line_committed.kind`, Q-A-3), SymPy where the line is
math (`Т-§22.7`), its confidence and whether the line is crossed out. The schema lives in the
package that calls the role (§7.2 S8); `tests/llm/prompt_contracts.py` registers it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RecognizerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["latex", "text"]
    text: str
    sympy: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    crossed_out: bool
