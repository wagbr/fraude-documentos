Excelente pergunta. O **Fluxo prático de verificação em camadas empilhadas** é uma arquitetura modular por natureza, e essa modularidade deve ser **preservada no código** para facilitar manutenção, testes e reuso.

### ✅ **Recomendado: dividir em módulos/scripts separados**

Isso segue o espírito das camadas:

| Camada                   | Responsabilidade                                                     | Módulo sugerido               |
| ------------------------ | -------------------------------------------------------------------- | ----------------------------- |
| 1️⃣ Hash & assinatura    | Verifica integridade e assinatura digital (PAdES, CAdES, RFC 3161)   | `verifica_hash_assinatura.py` |
| 2️⃣ Estrutura PDF/Office | Detecta edição fora da cadeia normal (xref, modDate, objetos soltos) | `analise_estrutura.py`        |
| 3️⃣ Conteúdo visual      | Analisa visualmente PDFs-escaneados (copy-move, PRNU, OCR)           | `analise_visual.py`           |
| 4️⃣ Texto & NLP          | Verifica termos suspeitos, inconsistências entre versões ou autores  | `analise_texto.py`            |
| 5️⃣ Orquestrador         | Coordena tudo e agrega resultado final                               | `verificador_documental.py`   |

---

### Vantagens do modelo fatiado:

1. **Reusabilidade**: pode aplicar só a camada 2 ou 3 conforme o tipo do arquivo (PDF escaneado não precisa NLP).
2. **Testes unitários**: você pode testar `analise_estrutura.py` com mocks de PDF sem depender do restante.
3. **Paralelização futura**: dá pra rodar cada camada em worker separado, se quiser escalar.
4. **Auditoria**: logar por camada permite saber em qual ponto um documento foi considerado suspeito.

---

### Organização prática do projeto

```bash
fraude_docs/
│
├── main.py                      # CLI principal
├── document_preprocessor.py     # Já pronto no canvas
├── verifica_hash_assinatura.py
├── analise_estrutura.py
├── analise_visual.py
├── analise_texto.py
├── models/                      # Modelos ML ou transformers, se houver
│   ├── copy_move.pt
│   └── nlp_check/
├── utils/                       # Funções auxiliares
│   ├── pdf_utils.py
│   ├── image_tools.py
│   └── metadata_tools.py
├── tests/
│   └── test_analise_visual.py
└── requirements.txt
```

---

### Pode ter uma CLI unificada?

Sim! O `main.py` ou `verificador_documental.py` pode importar os módulos e orquestrar tudo assim:

```python
from document_preprocessor import preprocess
from verifica_hash_assinatura import verificar_assinatura
from analise_estrutura import analisar_estrutura_pdf
from analise_visual import analisar_imagens
from analise_texto import analisar_texto_extraido
```

E o resultado final pode ser um JSON com flags:

```json
{
  "assinatura_valida": false,
  "estrutura_suspeita": true,
  "conteudo_visual_suspeito": false,
  "texto_inconsistente": true
}
```

---

Se quiser, posso te ajudar agora a montar a estrutura de pastas, gerar os arquivos de esqueleto, ou começar pela camada que você preferir.
