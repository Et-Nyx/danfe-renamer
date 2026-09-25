"""PDF document access: page text, line geometry and text normalization.

The rest of the application reads documents through this module, so the PDF
library stays in one place and every parser sees the same representation of a
page: visual lines made of positioned words.
"""
