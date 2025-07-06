"""analise_estrutura.py
-------------------------------------------
Camada 2 do pipeline forense: analisa a estrutura interna
de PDFs e DOCX em busca de indícios de edição posterior ou
manipulação anômala (incremental updates quebrados, objetos
soltos, discrepâncias de metadados, macros inesperadas etc.).

Uso CLI::

    python analise_estrutura.py <arquivo> [-o relat.json] [--verbose]

Dependências principais (além das já listadas no projeto):
    pikepdf>=9.3.0        # parsing de PDF
    lxml>=5.2.1           # leitura rápida de XML do DOCX
    rich>=13.7.1          # saída colorida opcional

Todas são opcionais: o script faz *graceful degradation* se
faltarem.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------- utils -----------------------------

def _count_eof_markers(pdf_bytes: bytes) -> int:
    """Conta quantas vezes a tag '%%EOF' aparece no binário;\n    >1 indica incremental updates possíveis."""
    return len(re.findall(br"%%EOF", pdf_bytes))


def _detect_javascript(pdf) -> bool:  # type: ignore[valid-type]
    """Procura objetos /JavaScript ou /JS (possível cargo de malware)."""
    try:
        for obj in pdf.trailer.root.iter_objects():  # pikepdf ige
            if isinstance(obj, dict):
                if "/JavaScript" in obj or b"/JavaScript" in obj:
                    return True
                if "/JS" in obj or b"/JS" in obj:
                    return True
    except Exception:  # pragma: no cover – melhor retornar False do que quebrar
        return False
    return False


# ---------------------- Data classes ----------------------

@dataclass
class PDFStructureFindings:
    incremental_updates: bool
    eof_markers: int
    creation_date: Optional[str]
    mod_date: Optional[str]
    mod_after_creation: Optional[bool]
    javascript_detected: bool
    suspicious_objects: List[str] = field(default_factory=list)


@dataclass
class DOCXStructureFindings:
    has_track_changes: bool
    has_macros: bool
    creation_date: Optional[str]
    mod_date: Optional[str]
    mod_after_creation: Optional[bool]


@dataclass
class StructureReport:
    path: str
    file_type: str  # "PDF" | "DOCX" | "UNKNOWN"
    pdf_findings: Optional[PDFStructureFindings] = None
    docx_findings: Optional[DOCXStructureFindings] = None


# ---------------------- PDF analysis ----------------------

def _analyze_pdf(path: Path, verbose: bool = False) -> PDFStructureFindings:
    try:
        import pikepdf  # local import to allow fallback
    except ImportError:
        raise RuntimeError("pikepdf não instalado – instale para análise estrutural de PDFs")

    pdf_bytes = path.read_bytes()
    eof_markers = _count_eof_markers(pdf_bytes)
    incremental_updates = eof_markers > 1

    creation_date = None
    mod_date = None
    mod_after_creation: Optional[bool] = None
    javascript = False
    suspicious: List[str] = []

    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        info = pdf.docinfo  # tipo pikepdf.Dictionary
        creation_date = str(info.get("/CreationDate")) if info else None
        mod_date = str(info.get("/ModDate")) if info else None
        if creation_date and mod_date:
            # simples comparação lexicográfica serve na maioria;
            # datas PDF são tipo D:YYYYMMDDhhmmss
            mod_after_creation = mod_date > creation_date
        javascript = _detect_javascript(pdf)
        if javascript:
            suspicious.append("JavaScript_embutido")

        # Exemplo de objeto solto: stream sem referência no xref
        # pikepdf mantém Set[int] pdf.trailer.xref_sections[0].obj_free
        try:
            free_objs = pdf.xref_free_objects  # type: ignore[attr-defined]
            if free_objs:
                suspicious.append(f"Objetos_free:{len(free_objs)}")
        except Exception:
            pass

    return PDFStructureFindings(
        incremental_updates=incremental_updates,
        eof_markers=eof_markers,
        creation_date=creation_date,
        mod_date=mod_date,
        mod_after_creation=mod_after_creation,
        javascript_detected=javascript,
        suspicious_objects=suspicious,
    )


# ---------------------- DOCX analysis ---------------------

def _analyze_docx(path: Path, verbose: bool = False) -> DOCXStructureFindings:
    try:
        from lxml import etree
    except ImportError:
        raise RuntimeError("lxml não instalado – instale para análise estrutural de DOCX")

    with zipfile.ZipFile(path) as zf:
        # Macros ficam em vbaProject.bin
        has_macros = any(p.name.lower().endswith("vbaProject.bin".lower()) for p in zf.infolist())

        # Core properties (ISO 29500)
        try:
            core_xml = zf.read("docProps/core.xml")
            core_root = etree.fromstring(core_xml)  # type: ignore
            ns = {"cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                  "dc": "http://purl.org/dc/elements/1.1/",
                  "dcterms": "http://purl.org/dc/terms/"}
            creation_el = core_root.find("dcterms:created", ns)
            mod_el = core_root.find("dcterms:modified", ns)
            creation_date = creation_el.text if creation_el is not None else None
            mod_date = mod_el.text if mod_el is not None else None
            mod_after_creation = None
            if creation_date and mod_date:
                mod_after_creation = mod_date > creation_date
        except KeyError:
            creation_date = mod_date = mod_after_creation = None

        # Detectar TrackChanges no settings.xml
        try:
            settings_xml = zf.read("word/settings.xml")
            settings_root = etree.fromstring(settings_xml)  # type: ignore
            has_track_changes = settings_root.find(".//w:trackRevisions", namespaces={
                "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}) is not None
        except KeyError:
            has_track_changes = False

    return DOCXStructureFindings(
        has_track_changes=has_track_changes,
        has_macros=has_macros,
        creation_date=creation_date,
        mod_date=mod_date,
        mod_after_creation=mod_after_creation,
    )


# ---------------------- High-level API --------------------

def analyze_structure(path: str | Path, verbose: bool = False) -> StructureReport:
    """Detecta anomalias estruturais no documento indicado."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    if p.suffix.lower() == ".pdf":
        pdf_findings = _analyze_pdf(p, verbose)
        return StructureReport(path=str(p), file_type="PDF", pdf_findings=pdf_findings)
    elif p.suffix.lower() in {".docx", ".docm"}:
        docx_findings = _analyze_docx(p, verbose)
        return StructureReport(path=str(p), file_type="DOCX", docx_findings=docx_findings)
    else:
        return StructureReport(path=str(p), file_type="UNKNOWN")


# ---------------------- CLI -------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Análise estrutural de PDFs e DOCX.")
    parser.add_argument("arquivo", help="Caminho do arquivo a analisar")
    parser.add_argument("-o", "--out", help="Salvar relatório JSON em arquivo")
    parser.add_argument("--verbose", "-v", action="store_true", help="Saída detalhada")
    args = parser.parse_args()

    try:
        report = analyze_structure(args.arquivo, verbose=args.verbose)
    except Exception as exc:
        print(f"[ERROR] Falha na análise: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        Path(args.out).write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False))
        if args.verbose:
            print(f"[INFO] Relatório salvo em {args.out}")
    else:
        from pprint import pprint
        pprint(asdict(report), sort_dicts=False)


if __name__ == "__main__":
    _cli()
