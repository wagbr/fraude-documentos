"""analise_visual.py
-----------------------------------------------------
Camada 3: análise visual de PDFs escaneados ou imagens soltas.
Detecta indícios de adulteração via copy‑move, PRNU* e OCR.

(*) PRNU = Photo‑Response Non‑Uniformity. Usa o fork
    https://github.com/ocrim1996/prnu-python (pip install
    git+https://github.com/ocrim1996/prnu-python.git).

CLI:
    python analise_visual.py <arquivo.pdf|png|jpg> --verbose [-o visual.json] [--poppler-path PATH]

Dependências adicionais (além das do projeto):
    pdf2image>=1.17.0
    opencv-python-headless>=4.11.0.86
    scikit-image>=0.25.2
    pytesseract>=0.3.13
    git+https://github.com/ocrim1996/prnu-python.git   # opcional; se ausente, PRNU é ignorado
"""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
from tqdm import tqdm

# ------------------------------ dependências opcionais ---------------------
try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None  # noqa: N816  (mantemos minúsculo p/ marcar ausência)

try:
    from pdf2image import convert_from_path  # type: ignore
except ImportError:  # pragma: no cover
    convert_from_path = None

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover
    pytesseract = None

try:
    import prnu  # type: ignore  # from prnu-python fork
except ImportError:  # pragma: no cover
    prnu = None

# ------------------------------ dataclasses --------------------------------
@dataclass
class VisualReport:
    path: str
    file_type: str  # PDF, IMAGE
    pages: int
    copy_move: bool
    copy_move_boxes: List[List[int]] = field(default_factory=list)  # [x1,y1,x2,y2]
    prnu_inconsistent: Optional[bool] = None
    ocr_ratio: Optional[float] = None
    errors: List[str] = field(default_factory=list)

# ------------------------------ helpers ------------------------------------
ORB_MAX_KP = 3000
MATCH_DIST_THRESHOLD = 30
MIN_CLUSTER = 10
PRNU_CORR_THRESHOLD = 0.7


def _render_pdf(path: Path, poppler_path: Optional[str]):
    if convert_from_path is None:
        raise RuntimeError("pdf2image não está instalado; instale para renderizar PDFs.")
    return convert_from_path(path, dpi=300, fmt="png", poppler_path=poppler_path)


def _detect_copy_move(img):
    if cv2 is None:
        return False, []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=ORB_MAX_KP)
    kp, des = orb.detectAndCompute(gray, None)
    if des is None or len(kp) < 2:
        return False, []
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des, des)
    matches = [m for m in matches if m.distance < MATCH_DIST_THRESHOLD and m.queryIdx != m.trainIdx]
    if len(matches) < MIN_CLUSTER:
        return False, []
    # agrupar por deslocamento aproximado
    boxes = []
    for m in matches[:MIN_CLUSTER]:
        pt1 = kp[m.queryIdx].pt
        pt2 = kp[m.trainIdx].pt
        boxes.append([int(pt1[0]), int(pt1[1]), int(pt2[0]), int(pt2[1])])
    return True, boxes


def _extract_prnu(residuals):
    if prnu is None:
        return None
    # usa a média do ruído das primeiras páginas como referência
    ref = np.mean(residuals[:3], axis=0)
    inconsist = False
    for res in residuals[3:]:
        corr = prnu.corr2d(ref, res)
        if corr < PRNU_CORR_THRESHOLD:
            inconsist = True
            break
    return inconsist


def _ocr_text(pil_img):
    if pytesseract is None:
        return 0.0
    txt = pytesseract.image_to_string(pil_img, lang="por+eng")
    words = txt.split()
    return len(words) / 100  # número arbitrário p/ ratio

# ------------------------------ main analyzer ------------------------------

def analyze(path: str, poppler_path: Optional[str] = None, verbose: bool = False) -> VisualReport:
    p = Path(path)
    errors: List[str] = []

    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        pages = [p]
        file_type = "IMAGE"
    elif p.suffix.lower() == ".pdf":
        try:
            pages = _render_pdf(p, poppler_path)
            file_type = "PDF"
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Falha ao renderizar/abrir: {e}") from e
    else:
        raise RuntimeError("Tipo de arquivo não suportado para análise visual.")

    copy_move = False
    copy_boxes: List[List[int]] = []
    residuals = []
    ocr_words = 0.0

    for idx, pg in enumerate(tqdm(pages, disable=not verbose, desc="Analisando páginas")):
        if isinstance(pg, Path):
            img = cv2.imread(str(pg)) if cv2 else None
            pil_img = pg  # para OCR fallback (string path)
        else:  # PIL.Image
            pil_img = pg
            img = cv2.cvtColor(np.array(pg), cv2.COLOR_RGB2BGR) if cv2 else None

        # copy‑move
        if img is not None and cv2 is not None:
            cm_flag, boxes = _detect_copy_move(img)
            if cm_flag:
                copy_move = True
                copy_boxes.extend([[idx] + b for b in boxes])

        # PRNU residuals
        if prnu is not None:
            residual = prnu.extract_single(np.array(pil_img))
            residuals.append(residual)

        # OCR
        ocr_words += _ocr_text(pil_img)

    prnu_flag: Optional[bool] = None
    if residuals and prnu is not None:
        try:
            prnu_flag = _extract_prnu(residuals)
        except Exception as e:  # pragma: no cover
            errors.append(f"PRNU erro: {e}")

    report = VisualReport(
        path=str(p),
        file_type=file_type,
        pages=len(pages),
        copy_move=copy_move,
        copy_move_boxes=copy_boxes,
        prnu_inconsistent=prnu_flag,
        ocr_ratio=ocr_words / max(len(pages), 1),
        errors=errors,
    )
    return report

# ------------------------------ CLI ----------------------------------------

def _cli():
    ap = argparse.ArgumentParser(description="Análise visual forense (copy‑move, PRNU, OCR)")
    ap.add_argument("arquivo")
    ap.add_argument("-o", "--out", help="salvar JSON neste caminho")
    ap.add_argument("--poppler-path", help="diretório dos binários do Poppler")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    try:
        rep = analyze(args.arquivo, poppler_path=args.poppler_path, verbose=args.verbose)
        rep_json = json.dumps(asdict(rep), ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(rep_json, encoding="utf-8")
            print(f"✔️  Relatório salvo em {args.out}")
        else:
            print(rep_json)
    except Exception as e:
        print(f"[ERRO] {e}")
        raise


if __name__ == "__main__":
    _cli()
