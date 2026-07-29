"""Getting source material into a shape the distiller can read.

One question, asked once: *what is this?* Everything downstream — the
distiller, the promotion bar, the connector — works on plain text and does not
care where it came from. This package is the only place that knows the
difference between a subtitle file and a PDF.

Two routes do not produce text here at all. A YouTube link and an article URL
are handed to the model as references, because it can watch and read them
directly and any transcript we assembled ourselves would be worse.

Deliberately absent: audio and video transcription. It needs MLX, which is
Apple-Silicon-only and about a gigabyte of native libraries, and a recorded
talk is better served today by pasting a transcript than by doubling the size
of the app.
"""

from __future__ import annotations

from tilt.ingest.extract import ExtractionError, extract
from tilt.ingest.route import Medium, Route, classify

__all__ = ["ExtractionError", "Medium", "Route", "classify", "extract"]
