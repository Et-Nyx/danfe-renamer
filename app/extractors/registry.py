"""Known DANFE parsers.

Adding support for a new layout means writing a parser and adding it here.
"""

from __future__ import annotations

from .base import DanfeExtractor
from .danfe_standard import DanfeStandardExtractor

#: Every parser the detector may choose from, in priority order.
PARSERS: tuple[DanfeExtractor, ...] = (DanfeStandardExtractor(),)


def known_parser_ids() -> tuple[str, ...]:
    return tuple(parser.parser_id for parser in PARSERS)
