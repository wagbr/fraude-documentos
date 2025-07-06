"""document_preprocessor.py
================================
Pré‑processador de documentos (PDF ou DOCX) para pipeline forense
-----------------------------------------------------------------

* Calcula hashes (SHA‑256/512) para cadeia de custódia.
* Determina o tipo de documento.
* Para PDF:
    - Extrai metadados via pikepdf.
    - Conta páginas & verifica se contém texto via pdfplumber.
    - Se raster (scan) e `out_dir` definido, renderiza cada página
      em PNG (300 dpi) usando pdf2image.
* Para DOCX:
    - Extrai propriedades básicas via python‑docx.
* Retorna um `PreprocessInfo` (dataclass) serializável em JSON.

Uso CLI
~~~~~~~
    python document_preprocessor.py arquivo.pdf --out tmp_img

Dependências
~~~~~~~~~~~~
    pikepdf, pdfplumber, pdf2image, python-docx, pillow, tqdm
    (todas já listadas no requirements.txt)

Nota: Poppler e QPDF devem estar instalados no sistema.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# libs opcionais (import late to allow graceful degradation)


@dataclass
class PreprocessInfo:
    path: str
    file_type: str  # "PDF" | "DOCX" | "UNKNOWN"
    sha256: str
    sha512: str
    pages: int | None = None
    is_pdf_text: bool | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    rendered_images: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _hash_file(path: Path) -> tuple[str, str]:
    """Return (sha256, sha512) of the file."""
    h256 = hashlib.sha256()
    h512 = hashlib.sha512()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h256.update(chunk)
            h512.update(chunk)
    return h256.hexdigest(), h512.hexdigest()


def _detect_mime(path: Path) -> str | None:
    mime, _ = mimetypes.guess_type(path.name)
    return mime


# ---------------------------------------------------------------------------
# PDF handling
# ---------------------------------------------------------------------------


def _preprocess_pdf(path: Path, out_dir: Optional[Path] = None, verbose=False) -> dict:
    info: dict[str, Any] = {}

    # Basic stats via pdfplumber
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(str(path)) as pdf:
            num_pages = len(pdf.pages)
            # A heurística: se a primeira página tem char objects => texto
            try:
                first_page = pdf.pages[0]
                is_text = len(first_page.chars) > 0
            except Exception:
                is_text = False
            info["pages"] = num_pages
            info["is_pdf_text"] = is_text
    except ImportError:
        if verbose:
            print("[WARN] pdfplumber não instalado – pulando detecção de texto.")
    except Exception as e:
        if verbose:
            print(f"[WARN] Falha ao abrir PDF com pdfplumber: {e}")

    # Metadata & revisions via pikepdf
    try:
        import pikepdf  # type: ignore

        with pikepdf.open(str(path)) as pdf:
            info["metadata"] = {
                k[1:]: str(v) for k, v in pdf.docinfo.items()
            }
            info["revisions"] = pdf.pdf_version
            info["has_xref_streams"] = pdf.has_xref_streams
    except ImportError:
        if verbose:
            print("[WARN] pikepdf não instalado – metadados não extraídos.")
    except Exception as e:
        if verbose:
            print(f"[WARN] Falha ao ler metadados com pikepdf: {e}")

    # Render pages if needed
    if out_dir and info.get("is_pdf_text") is False:
        try:
            from pdf2image import convert_from_path  # type: ignore
            from tqdm import tqdm  # type: ignore

            out_dir.mkdir(parents=True, exist_ok=True)
            images = convert_from_path(str(path), dpi=300)
            img_paths: list[str] = []
            for idx, img in enumerate(tqdm(images, desc="Renderizando páginas")):
                img_path = out_dir / f"{path.stem}_page_{idx+1}.png"
                img.save(img_path, "PNG")
                img_paths.append(str(img_path))
            info["rendered_images"] = img_paths
        except ImportError:
            if verbose:
                print("[INFO] pdf2image/Tesseract não instalados – pulando renderização.")
        except Exception as e:
            if verbose:
                print(f"[WARN] Falha ao renderizar páginas: {e}")

    return info


# ---------------------------------------------------------------------------
# DOCX handling
# ---------------------------------------------------------------------------


def _preprocess_docx(path: Path, verbose=False) -> dict:
    info: dict[str, Any] = {}
    try:
        import docx  # python-docx, type: ignore

        doc = docx.Document(str(path))
        core = doc.core_properties
        info["metadata"] = {
            "author": core.author,
            "created": str(core.created),
            "last_modified_by": core.last_modified_by,
            "modified": str(core.modified),
            "title": core.title,
        }
        info["paragraphs"] = len(doc.paragraphs)
    except ImportError:
        if verbose:
            print("[WARN] python-docx não instalado – metadados não extraídos.")
    except Exception as e:
        if verbose:
            print(f"[WARN] Falha ao processar DOCX: {e}")

    return info


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess(filepath: str | Path, out_dir: str | Path | None = None, verbose=False) -> PreprocessInfo:
    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    sha256, sha512 = _hash_file(path)

    mime = _detect_mime(path) or ""
    ext = path.suffix.lower()

    if mime == "application/pdf" or ext == ".pdf":
        file_type = "PDF"
        extra = _preprocess_pdf(path, Path(out_dir) if out_dir else None, verbose)
    elif ext in {".docx", ".doc"} or "word" in mime:
        file_type = "DOCX"
        extra = _preprocess_docx(path, verbose)
    else:
        file_type = "UNKNOWN"
        extra = {}

    info = PreprocessInfo(
        path=str(path),
        file_type=file_type,
        sha256=sha256,
        sha512=sha512,
        pages=extra.get("pages"),
        is_pdf_text=extra.get("is_pdf_text"),
        metadata=extra.get("metadata", {}),
        rendered_images=extra.get("rendered_images", []),
    )
    return info


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Pré-processador de documentos PDF/DOCX para forense.")
    parser.add_argument("arquivo", help="Caminho do documento (PDF ou DOCX)")
    parser.add_argument("--out", help="Diretório de saída para imagens renderizadas (PDF raster)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    info = preprocess(args.arquivo, args.out, args.verbose)
    print(info.to_json())


if __name__ == "__main__":
    _cli()
