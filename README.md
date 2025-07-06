# Fraude Documental

![Pipeline banner](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge) ![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

> **Verifique, explique e durma tranquilo** – um pipeline modular em Python que
> valida **integração criptográfica**, estrutura interna, conteúdo visual e
> textual de documentos PDF/DOCX.

---
__Introdução__

A transformação digital trouxe agilidade e praticidade para o mundo jurídico, contábil, educacional e administrativo. No entanto, também abriu novas portas para fraudes cada vez mais sofisticadas em documentos eletrônicos. Se antes falsificações exigiam habilidades gráficas e impressoras especializadas, hoje basta um editor de PDF, uma cópia escaneada ou uma assinatura digital mal utilizada para produzir documentos aparentemente legítimos — mas falsos.

As fraudes documentais digitais ocorrem em diversas camadas, e este projeto foi construído para desmascará-las, **camada por camada**:

> Exemplos comuns de fraude:

> * **Assinaturas digitais inválidas ou ausentes** disfarçadas em PDFs visualmente perfeitos.
> * **Documentos escaneados com colagens** ou manipulações visuais sutis (copy-move).
> * **Arquivos PDF com metadados ou estruturas que indicam alterações posteriores** não visíveis no conteúdo.
> * **Textos modificados com termos adicionados como “retificado”, “substitui-se”, “conforme anexo”, etc.**
> * **Arquivos Office com “control changes” ligados ou macros embutadas**, usados para reverter alterações.

Esses ataques são difíceis de detectar a olho nu. Mas, com análise automatizada e cruzamento de evidências, é possível levantar indícios objetivos de fraude.

---

__Por que esse código detecta fraudes?__

Este projeto utiliza um **pipeline forense digital modular**, com ferramentas avançadas de verificação e extração, que operam em quatro frentes:

1. **Assinatura Digital e Hashes (Camada 1)**
   Detecta presença, validade e integridade de assinaturas PAdES ou XML-DSig. Calcula e registra os hashes do arquivo para comparação e auditoria.

2. **Estrutura Interna (Camada 2)**
   Analisa se o documento sofreu alterações estruturais suspeitas, como múltiplos updates incrementais, uso de JavaScript, objetos órfãos, data de modificação posterior à criação, entre outros.

3. **Análise Visual (Camada 3)**
   Renderiza páginas como imagens e aplica detecção de manipulações por cópia e colagem (copy-move), além de identificar se as páginas vieram de dispositivos diferentes (PRNU) e avaliar a presença ou ausência de texto via OCR.

4. **Análise Textual e Semântica (Camada 4)**
   Extrai o conteúdo textual, identifica idiomas misturados, estilo divergente entre páginas (sinal de múltiplos autores) e termos-chave associados a edições ilegítimas.

O sistema é projetado para funcionar com **evidência negativa e positiva**: ele não apenas denuncia anomalias, mas também confirma a normalidade de documentos autênticos.

---

__Resultado__

Com isso, o código não só **detecta fraudes sofisticadas**, mas também oferece **transparência técnica** para subsidiar decisões administrativas, judiciais ou auditoriais. Ele pode ser usado por:

* Auditores e órgãos de controle;
* Servidores públicos;
* Empresas que recebem documentos de terceiros;
* Profissionais do Direito;
* Peritos judiciais e extrajudiciais.

---

## Visão Geral

A fraude documental evoluiu; nossa resposta também. Este projeto consolida **4
camadas forenses** em código aberto:

| Camada | Módulo                        | O que faz                                                 | Tecnologias                                            |
| ------ | ----------------------------- | --------------------------------------------------------- | ------------------------------------------------------ |
| 0      | `document_preprocessor.py`    | Hash + metadados + render                                 | `pikepdf`, `pdfplumber`, `pdf2image`                   |
| 1      | `verifica_hash_assinatura.py` | Verifica PAdES/LTV (ICP‑Brasil, eIDAS) e XMLDSig          | `pyHanko`, `cryptography`                              |
| 2      | `analise_estrutura.py`        | Detecta incremental updates suspeitos, macros, JavaScript | `pikepdf`, `lxml`                                      |
| 3      | `analise_visual.py`           | Copy‑move, PRNU\* (opcional), OCR                         | `opencv‑python‑headless`, `prnu-python`, `pytesseract` |
| 4      | `analise_texto.py`            | Termos suspeitos, multi‑idioma, estilometria              | `langdetect`, `nltk`, `textstat`                       |
| ✔      | `verificador_documental.py`   | Orquestra tudo e gera relatório JSON                      | —                                                      |

\*PRNU: fingerprint de sensor para identificar páginas escaneadas de scanners
ou câmeras diferentes.

---

## Arquitetura

```mermaid
graph TD;
    A[Preprocess] --> B[Hash & Assinatura];
    B --> C[Estrutura];
    C --> D{PDF Raster?};
    D -- Sim --> E[Visual];
    D -- Não --> F[Texto];
    E --> F[Texto];
    F --> G[Relatório único + Veredicto];
```

Cada camada roda **independente**, grava seu JSON e repassa artefatos (texto
OCR, metadados, etc.) para a próxima – favorecendo paralelização futura.

---

## Instalação Rápida

```bash
# 1. clone
$ git clone https://github.com/wagbr/fraude-documentos.git
$ cd fraude-documentos

# 2. virtualenv
$ python -m venv .venv && source .venv/bin/activate

# 3. dependências
$ pip install -r requirements.txt

# 4. instale poppler & tesseract (Windows)
#    choco install poppler tesseract
```

> **Poppler** é obrigatório para renderizar PDFs rasterizados.

---

## Uso

```bash
# pipeline completo (JSON consolidado)
python verificador_documental.py CONTRATO.pdf --verbose -o contrato_full.json

# módulos isolados
python analise_visual.py contrato_scan.pdf -v -o visual.json
python analise_estrutura.py contrato.pdf -v -o estrutura.json
```

Saída típica:

```json
{
  "verdict": "OK",
  "assinatura_hash": { "signatures": [{ "status": "VALID" }] },
  ...
}
```

---

## 🔒 Heurística de “Suspeito”

```python
sig_ok   = status in {"VALID", "UNVERIFIED_HYBRID"}
structok = not (incr_updates and javascript)
visualok = not copy_move
texto_ok = not suspicious_terms

verdict = "SUSPEITO" if not all([sig_ok, structok, visualok, texto_ok]) else "OK"
```

A lógica está em `verificador_documental.py` – ajuste à sua política.

---

## 📚 Referências Acadêmicas

* **Colette et al. (2025)** – *TransCMFD: Transformer‑based Copy‑Move Forgery Detection* (CVPR’25)
* **Gurumurthy & Fried (2024)** – *DiffForensics: Leveraging Diffusion Models for Image Tamper Localization* (CVPR’24)
* **NIST SAT‑ML Part II** (2024) – Dataset governamental de manipulação multi‑câmera
* **Riva et al. (2023)** – *PRNU Analysis for Multi‑Page PDF Authentication* (Forensic Sci. Int.)
* **ICP‑Brasil DOC‑ICP‑15 v5** (2023) – Política de Assinatura PAdES

> Lista ampliada no arquivo `docs/REFERENCES.md`.

---

> *“Dados confiáveis geram decisões confiáveis.”* – todo(a) auditor feliz
