"""analise_texto.py
---------------------------------------------------------
Camada 4: análise textual / semântica de documentos.
Detecta:
    • termos suspeitos (lista personalizável)
    • inconsistências de autoria/estilo entre páginas
    • múltiplos idiomas (sinal de cópia/cola)

Requer:
    pip install langdetect nltk textstat scikit-learn python-docx pdfplumber

Uso CLI:
    python analise_texto.py <arquivo> --verbose [-o out.json]

O script integra‑se ao document_preprocessor.preprocess().
Se OCR já foi executado na camada visual, passe o dicionário
ocr_text para evitar retrabalho.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean, stdev
from typing import List, Dict

# ============ dependências externas ============
try:
    from langdetect import detect as lang_detect, DetectorFactory
    import nltk
    from nltk.tokenize import word_tokenize, sent_tokenize, PunktSentenceTokenizer
    from nltk.corpus import stopwords
    import textstat
except ImportError as e:  # pragma: no cover
    missing = str(e).split("No module named ")[-1].strip("'\"")
    print(f"[ERROR] Biblioteca ausente: {missing}. Instale conforme header.")
    sys.exit(1)

# estilometria básica – nenhuma lib pesada além do textstat

DetectorFactory.seed = 42  # reproducibilidade para langdetect

# baixar corpora essenciais do NLTK em runtime, se necessário
for res in ["punkt", "stopwords"]:
    try:
        nltk.data.find(f"tokenizers/{res}" if res == "punkt" else f"corpora/{res}")
    except LookupError:  # pragma: no cover
        nltk.download(res, quiet=True)

# ============ parâmetros configuráveis ============
SUSPECT_TERMS = {
    "rasura", "alterado", "alteração", "em branco", "cópia", "copiar", "recortar",
    "colar", "fotomontagem", "adobe", "photoshop", "gimp", "paint",
}
MIN_PAGE_CHARS = 300   # ignora páginas muito curtas para estatística
STYLE_STD_Z = 1.2      # z‑score para marcar página fora do padrão de estilo

stop_words_pt = set(stopwords.words("portuguese"))

# ============ dataclasses de saída ============
@dataclass
class StylometryStats:
    avg_sentence_len: float
    avg_word_len: float
    lexical_diversity: float
    readability_fk: float  # Flesch‑Kincaid grade level

@dataclass
class TextReport:
    path: str
    file_type: str
    languages: List[str]
    suspicious_terms: List[str]
    style_inconsistent_pages: List[int]
    stylometry_by_page: Dict[int, StylometryStats] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

# ============ utilitários ============

def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _split_pages(text: str) -> List[str]:
    """Divide texto bruto em páginas usando form‑feed (\f) inserido pelo pdfplumber / OCR."""
    return text.split("\f")


def _calc_stylometry(text: str) -> StylometryStats:
    """Calcula métricas simples de estilometria para um bloco de texto."""
    # usar fallback neutro se punkt específico faltar
    try:
        sentences = sent_tokenize(text)
    except LookupError:  # caso punkt não exista
        tokenizer = PunktSentenceTokenizer()
        sentences = tokenizer.tokenize(text)

    if not sentences:
        sentences = [text]

    words = word_tokenize(text, language="portuguese")
    words_no_stop = [w for w in words if w.lower() not in stop_words_pt and w.isalpha()]

    if not words_no_stop:
        return StylometryStats(0, 0, 0, 0)

    avg_sentence_len = mean(len(word_tokenize(s)) for s in sentences)
    avg_word_len = mean(len(w) for w in words_no_stop)
    lexical_diversity = len(set(words_no_stop)) / len(words_no_stop)
    readability_fk = textstat.flesch_kincaid_grade(text) if text else 0.0

    return StylometryStats(avg_sentence_len, avg_word_len, lexical_diversity, readability_fk)


def _detect_language_sample(text: str) -> str:
    sample = text[:1000] if len(text) > 1000 else text
    try:
        return lang_detect(sample)
    except Exception:  # pragma: no cover
        return "unknown"

# ============ extração de texto ============

def extract_text(path: str, ocr_dict: Dict[int, str] | None = None) -> str:
    """Extrai texto de PDF ou DOCX.
    – Se `ocr_dict` fornecido (da camada visual), usa‑o.
    – Para DOCX, usa python‑docx.
    – Para PDF textual, usa pdfplumber.
    """
    p = Path(path)

    if ocr_dict:
        return "\f".join(ocr_dict[k] for k in sorted(ocr_dict))

    if p.suffix.lower() == ".docx":
        try:
            import docx
        except ImportError as e:
            raise RuntimeError("python-docx ausente") from e
        doc = docx.Document(path)
        return "\n".join(par.text for par in doc.paragraphs)

    if p.suffix.lower() == ".pdf":
        try:
            import pdfplumber
        except ImportError as e:
            raise RuntimeError("pdfplumber ausente, instale para extrair texto") from e
        texts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                texts.append(page.extract_text() or "")
        return "\f".join(texts)

    raise RuntimeError("Formato não suportado para extração de texto")

# ============ análise principal ============

def analyze_text(path: str, *, ocr_dict: Dict[int, str] | None = None) -> TextReport:
    report = TextReport(path=path, file_type=Path(path).suffix.upper().lstrip("."),
                        languages=[], suspicious_terms=[], style_inconsistent_pages=[])

    try:
        raw_text = extract_text(path, ocr_dict)
    except Exception as exc:
        report.errors.append(f"Falha na extração de texto: {exc}")
        return report

    pages = _split_pages(raw_text)

    # ---------- detecção de idioma ----------
    langs_counter = Counter(_detect_language_sample(t) for t in pages if t.strip())
    report.languages = list(langs_counter)
    if len(langs_counter) > 1:
        report.errors.append("Vários idiomas detectados: " + ", ".join(langs_counter))

    # ---------- termos suspeitos ----------
    lower_text = raw_text.lower()
    report.suspicious_terms = sorted({t for t in SUSPECT_TERMS if t in lower_text})

    # ---------- estilometria por página ----------
    stylistic_values = []  # (idx, readability)
    for idx, page_txt in enumerate(pages, 1):
        cleaned = _clean_text(page_txt)
        if len(cleaned) < MIN_PAGE_CHARS:
            continue
        stats = _calc_stylometry(cleaned)
        report.stylometry_by_page[idx] = stats
        stylistic_values.append((idx, stats.readability_fk))

    # identificar páginas fora do padrão
    if stylistic_values:
        vals = [v for _, v in stylistic_values]
        mu = mean(vals)
        sigma = stdev(vals) if len(vals) > 1 else 0
        for idx, v in stylistic_values:
            if sigma and abs(v - mu) / sigma > STYLE_STD_Z:
                report.style_inconsistent_pages.append(idx)

    return report

# ============ CLI ============

def _cli():  # pragma: no cover
    ap = argparse.ArgumentParser(description="Camada 4 – análise textual de documentos")
    ap.add_argument("arquivo", help="PDF ou DOCX a analisar")
    ap.add_argument("--verbose", "-v", action="store_true", help="Exibir detalhes no console")
    ap.add_argument("--out", "-o", default=None, help="Arquivo JSON de saída")
    args = ap.parse_args()

    rep = analyze_text(args.arquivo)

    if args.verbose:
        print(json.dumps(asdict(rep), indent=2, ensure_ascii=False))

    if args.out:
        Path(args.out).write_text(json.dumps(asdict(rep), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✔️  Relatório textual salvo em {args.out}")

if __name__ == "__main__":  # pragma: no cover
    _cli()
