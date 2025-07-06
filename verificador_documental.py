"""verificador_documental.py
====================================================
Pipeline completo de verificação documental (4 camadas)
-----------------------------------------------------

Camadas:
 0. Pré‑processamento             (document_preprocessor)
 1. Hash & Assinatura             (verifica_hash_assinatura)
 2. Estrutura                     (analise_estrutura)
 3. Visual (opcional se raster)   (analise_visual)
 4. Texto                         (analise_texto)

Uso CLI:
    python verificador_documental.py <arquivo> [-v] [-o out.json]
         [--poppler-path "C:\Poppler\bin"]

Saída JSON:
{
  "preprocess": {...},
  "assinatura_hash": {...},
  "estrutura": {...},
  "visual": {...},   # ausente p/ PDF‑texto
  "texto": {...},
  "verdict": "OK" | "SUSPEITO"
}
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from document_preprocessor import preprocess
import verifica_hash_assinatura as vhash
import analise_estrutura as estr
import analise_visual as vis
import analise_texto as txt

# -----------------------------------------------------------

def run_pipeline(path: str, *, poppler_path: str | None = None, verbose: bool = False) -> Dict[str, Any]:
    # -------- camada 0: preprocess --------
    pinfo = preprocess(path)
    pages = getattr(pinfo, "num_pages", "?")
    if verbose:
        print(f"[0] Preprocess ok – {pinfo.file_type} {pages}p")

    # -------- camada 1: hash & assinatura --------
    hrep = vhash.verify(path)
    hdict = asdict(hrep)
    sig_status = hdict.get("signatures", [{}])[0].get("status")
    if verbose:
        print("[1] Assinatura:", sig_status)

    # -------- camada 2: estrutura --------
    erep = estr.analyze_structure(path, verbose=verbose)
    edict = asdict(erep)
    if verbose and erep.pdf_findings:
        print("[2] Estrutura PDF – incr.updates:", erep.pdf_findings.incremental_updates)

    # -------- camada 3: visual (apenas se raster) --------
    vdict: Dict[str, Any] | None = None
    if getattr(pinfo, "is_pdf_text", False) is False:
        vrep = vis.analyze(path, poppler_path=poppler_path, verbose=verbose)
        vdict = asdict(vrep)
        if verbose:
            print("[3] Visual – copy_move:", vdict.get("copy_move"))

    # -------- camada 4: texto --------
    ocr_dict = vdict.get("ocr_text") if vdict else None  # type: ignore
    trep = txt.analyze_text(path, ocr_dict=ocr_dict)
    tdict = asdict(trep)
    if verbose and trep.suspicious_terms:
        print("[4] Texto – termos suspeitos:", trep.suspicious_terms)

    # -------- verdict simples --------
    suspicious = (
        sig_status not in {"VALID", "UNVERIFIED_HYBRID"} or
        (erep.pdf_findings and erep.pdf_findings.incremental_updates and erep.pdf_findings.javascript_detected) or
        (vdict and vdict.get("copy_move")) or
        trep.suspicious_terms
    )

    verdict = "SUSPEITO" if suspicious else "OK"

    return {
        "preprocess": asdict(pinfo),
        "assinatura_hash": hdict,
        "estrutura": edict,
        "visual": vdict,
        "texto": tdict,
        "verdict": verdict,
    }

# -----------------------------------------------------------

def _cli() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Pipeline completo de verificação documental")
    parser.add_argument("arquivo", help="PDF ou DOCX a analisar")
    parser.add_argument("--poppler-path", help="Caminho do pdftoppm (Poppler) se não estiver no PATH", default=None)
    parser.add_argument("--verbose", "-v", action="store_true", help="Logs detalhados")
    parser.add_argument("--out", "-o", help="Arquivo JSON de saída")
    args = parser.parse_args()

    try:
        rep = run_pipeline(args.arquivo, poppler_path=args.poppler_path, verbose=args.verbose)
    except Exception as exc:
        print(f"[FATAL] Falha no pipeline: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        if args.verbose:
            print(f"Relatório salvo em {args.out}")
    else:
        print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    _cli()
