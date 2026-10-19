# Third-party notices

DANFE Renamer is distributed under GPL-3.0-or-later (see [LICENSE](LICENSE)).
The packaged `DANFE_Renamer.exe` also contains the unmodified runtime
dependencies below. Each one remains under its own license; the links point to
its source and license text.

| Library | License | Source |
|---|---|---|
| PyMuPDF | AGPL-3.0 or commercial | https://github.com/pymupdf/PyMuPDF |
| BrazilFiscalReport | LGPL-3.0 | https://github.com/Engenere/BrazilFiscalReport |
| fpdf2 | LGPL-3.0 | https://github.com/py-pdf/fpdf2 |
| phonenumbers | Apache-2.0 | https://github.com/daviddrysdale/python-phonenumbers |
| python-barcode | MIT | https://github.com/WhyNotHugo/python-barcode |
| qrcode | BSD-3-Clause | https://github.com/lincolnloop/python-qrcode |
| defusedxml | PSF-2.0 | https://github.com/tiran/defusedxml |
| Pillow | HPND | https://github.com/python-pillow/Pillow |
| fonttools | MIT | https://github.com/fonttools/fonttools |
| tkinterdnd2 | MIT | https://github.com/pmgagne/tkinterdnd2 |

BrazilFiscalReport is the library that turns an authorized NF-e/NFC-e XML into
the DANFE/DANFCe PDF. It is used as a separate, unmodified dependency; the
corresponding source of the version bundled in a release can be fetched from
the link above and rebuilt from this repository's
`requirements.txt`.
