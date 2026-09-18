# Duplicate Red-Team Laboratory (Internal QA)

Ferramenta **interna** de adversarial testing para o sistema de anti-duplicação de mídia.

## Objetivo

Dado um arquivo que **já existe** na plataforma, gerar variantes perceptualmente equivalentes e verificar se o pipeline de detecção continua identificando-as como o mesmo conteúdo.

Falso negativo = variante derivada do original que o detector classifica como `NEW`.

> **Não** é um endpoint público, **não** é ferramenta de bypass, **não** altera thresholds de produção.

## Instalação

```bash
pip install -e ".[duplicate-redteam]"
# ou
pip install Pillow imagehash numpy
# FFmpeg deve estar no PATH
```

## Uso

```bash
# Teste básico (imagem ou vídeo)
python -m tools.duplicate_redteam \
  --input input/sample.mp4 \
  --iterations 50 \
  --seed 42

# Mais agressivo
python -m tools.duplicate_redteam -i original.jpg -n 200 --max-transforms 4 --seed 12345

# Suite de regressão (re-executa falsos negativos salvos)
python -m tools.duplicate_redteam --regression
```

## Estrutura

```
tools/duplicate_redteam/
  cli.py              # entrada
  runner.py           # orquestração
  transforms/
    image.py          # JPEG/WebP, crop, resize, color, geom...
    video.py          # FFmpeg: recompress, fps, trim, letterbox...
    audio.py          # reencode, gain, filters...
  detectors/
    adapter.py        # pipeline de laboratório (Exact, PDQ-like, SSCD-like, TMK-like, Audio)
  reports/
    reporter.py       # métricas + persistência de FN
  results/
    false_negatives/  # fixtures automáticas
```

## Detectores (aproximações de laboratório)

| Nome       | Implementação                          | Nota |
|------------|----------------------------------------|------|
| Exact      | SHA-256                                 | idêntico |
| PDQ-like   | `imagehash.phash` em keyframes         | Hamming |
| SSCD-like  | phash agreement + histograma de cor    | similaridade 0-1 |
| TMK-like   | sequência temporal de phashes          | ordem preservada |
| Audio      | fingerprint espectral simples (FFmpeg) | cosine |

Estes **não** são os detectores de produção (Meta PDQ / SSCD / TMK reais). Servem para exercitar as famílias de transformação e medir robustez relativa.

## Saída

- Relatório JSON completo em `results/report_<id>.json`
- Falsos negativos em `results/false_negatives/<id>/variant_XXXX.{mp4,json}`
- Métricas por detector e por família de transformação

## Segurança

- Modo `dry_run=True` por padrão (não grava em stores de produção)
- Não expõe API
- Não desabilita detectores
- Variantes ficam apenas em diretórios locais de resultados

## Pipeline real (extração + decisão)

Extrai fingerprints e decide NEW/DUPLICATE sem gravar (dry-run):

```bash
python -m tools.duplicate_redteam \
  --input input/sample.mp4 \
  --pipeline-check
```

Com consulta a candidatos no Supabase (ainda dry-run):

```bash
export SUPABASE_URL="https://sgolmmhbufosmtigaakx.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="<service_role>"

python -m tools.duplicate_redteam \
  --input input/sample.mp4 \
  --pipeline-check \
  --with-supabase
```

Persistir fingerprints (produção / job de upload — **cuidado**):

```bash
python -m tools.duplicate_redteam \
  --input ./video.mp4 \
  --pipeline-check \
  --with-supabase \
  --persist \
  --media-id <uuid-luxa-media> \
  
```

### Módulos

| Módulo | Função |
|--------|--------|
| `detectors/adapter.py` | Detectores de laboratório + scoring local |
| `detectors/pipeline.py` | Pipeline completo extract → candidates → policy |
| `detectors/supabase_store.py` | Acesso ao store real (read / upsert controlado) |

Versões atuais dos algoritmos de lab estão em `FingerprintBundle.versions`.
Quando os detectores de produção (PDQ/SSCD/TMK reais) forem plugados, basta trocar as funções de extração e bump de `version`.
