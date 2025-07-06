"""verifica_hash_assinatura.py
--------------------------------
Primeira camada do fluxo: calcula hashes e valida assinaturas digitais
(PDF PAdES/LTV, DOCX XML Digital Signature).

• Depende de: pikepdf, pyhanko, cryptography, python-docx.
• Integra‑se ao document_preprocessor.preprocess()

CLI:
    python verifica_hash_assinatura.py <arquivo> [-v]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Import do pré‑processador (opcional)
# ---------------------------------------------------------------------------
try:
    from document_preprocessor import preprocess  # type: ignore
except ImportError:
    preprocess = None  # type: ignore

# ---------------------------------------------------------------------------
# PDF signature validation (pyHanko) – carregamento lazy
# ---------------------------------------------------------------------------
try:
    from pyhanko.pdf_utils.reader import PdfFileReader  # type: ignore
    from pyhanko.sign.validation import validate_pdf_signature  # type: ignore
    from pyhanko_certvalidator import ValidationContext  # type: ignore

    _PYHANKO_OK = True
except ImportError:
    _PYHANKO_OK = False

# ---------------------------------------------------------------------------
# DOCX signature validation (basic – XMLDSig)
# ---------------------------------------------------------------------------
try:
    import zipfile
    from xml.etree import ElementTree as ET
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    from cryptography.hazmat.primitives.asymmetric import padding

    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False

# ---------------------------------------------------------------------------
@dataclass
class SignatureSummary:
    signer_cn: Optional[str]
    signing_time: Optional[str]
    status: str  # VALID / INVALID / ERROR / UNAVAILABLE / PRESENT
    summary: str  # human‑readable


@dataclass
class VerificationReport:
    file_path: str
    sha256: str
    sha512: str
    signatures: List[SignatureSummary]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _calc_hashes(b: bytes) -> tuple[str, str]:
    return hashlib.sha256(b).hexdigest(), hashlib.sha512(b).hexdigest()


# ---------------------------------------------------------------------------
# PDF validation com allow_hybrid_reference_pdfs=True
# ---------------------------------------------------------------------------

def _verify_pdf(path: Path) -> List[SignatureSummary]:
    if not _PYHANKO_OK:
        print("[WARNING] pyHanko não disponível; pulando validação de assinatura PDF.")
        return [SignatureSummary(None, None, "UNAVAILABLE", "pyHanko ausente")]

    results: List[SignatureSummary] = []
    with path.open("rb") as fp:
        reader = PdfFileReader(fp)
        if not reader.embedded_signatures:
            return []  # sem assinatura

        vc = ValidationContext()  # usa trust store do sistema
        for sig in reader.embedded_signatures:
            try:
                status = validate_pdf_signature(sig, vc)
                signer_cn = None
                if sig.signer_cert is not None:
                    subj = sig.signer_cert.subject.native  # type: ignore
                    signer_cn = subj.get("common_name") or subj.get("organization_name")
                status_str = "VALID" if status.trusted and status.intact else "INVALID"  # type: ignore
                results.append(
                    SignatureSummary(
                        signer_cn,
                        str(status.signing_time),  # type: ignore
                        status_str,
                        status.pretty_print_details(),  # type: ignore
                    )
                )
            except Exception as exc:
                msg = str(exc)
                if "hybrid-reference" in msg.lower():
                    # Assinatura existe, mas pyHanko não valida nesse modo.
                    results.append(
                        SignatureSummary(
                            signer_cn=None,
                            signing_time=None,
                            status="UNVERIFIED_HYBRID",
                            summary="PDF em Hybrid-Reference: assinatura não verificada, mas presente",
                        )
                    )
                else:
                    results.append(SignatureSummary(None, None, "ERROR", f"Erro: {exc}"))
    return results


# ---------------------------------------------------------------------------
# DOCX (simplificado)
# ---------------------------------------------------------------------------

def _verify_docx(path: Path) -> List[SignatureSummary]:
    if not _CRYPTO_OK:
        print("[WARNING] cryptography não disponível; pulando validação DOCX.")
        return [SignatureSummary(None, None, "UNAVAILABLE", "cryptography ausente")]

    sigs: List[SignatureSummary] = []
    try:
        with zipfile.ZipFile(path) as zf:
            sig_rel_paths = [p for p in zf.namelist() if p.startswith("_xmlsignatures/") and p.endswith(".sig")]
            if not sig_rel_paths:
                return []
            for rel in sig_rel_paths:
                sigs.append(SignatureSummary(None, None, "PRESENT", f"Assinatura encontrada em {rel} (validação simplificada)"))
    except Exception as exc:
        sigs.append(SignatureSummary(None, None, "ERROR", f"Erro: {exc}"))
    return sigs


# ---------------------------------------------------------------------------
# Verificação principal
# ---------------------------------------------------------------------------

def verify(file_path: str | Path) -> VerificationReport:
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    sha256, sha512 = _calc_hashes(path.read_bytes())

    if preprocess is not None:
        try:
            preprocess(path)
        except Exception as exc:
            print(f"[WARNING] Preprocess falhou: {exc}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        signatures = _verify_pdf(path)
    elif suffix in {".docx", ".doc"}:
        signatures = _verify_docx(path)
    else:
        signatures = []

    return VerificationReport(str(path), sha256, sha512, signatures)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Verifica hashes e assinaturas de um documento.")
    parser.add_argument("arquivo", help="Caminho do PDF ou DOCX")
    parser.add_argument("-v", "--verbose", action="store_true", help="Exibir JSON completo")
    args = parser.parse_args()

    print(f"[INFO] Verificando {args.arquivo} …")
    report = verify(args.arquivo)

    print("\n=== Relatório de Verificação ===")
    print(f"Arquivo : {report.file_path}")
    print(f"SHA‑256 : {report.sha256}")
    print(f"SHA‑512 : {report.sha512}")
    if not report.signatures:
        print("Nenhuma assinatura detectada.")
    else:
        for idx, sig in enumerate(report.signatures, 1):
            print(f"Assinatura {idx}: {sig.status}")
            if sig.signer_cn:
                print(f"  • Signatário : {sig.signer_cn}")
            if sig.signing_time:
                print(f"  • Data/Hora  : {sig.signing_time}")
            if args.verbose:
                print("  -- Detalhes --")
                print(sig.summary)

    json_path = Path(report.file_path).with_suffix(".verif.json")
    json_path.write_text(report.to_json(), encoding="utf-8")
    print(f"[INFO] JSON salvo em {json_path}")


if __name__ == "__main__":  # pragma: no cover
    _cli()
