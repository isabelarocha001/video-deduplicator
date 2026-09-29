# Remover duplicidade de vídeo

Processador/normalizador de vídeo em Python que utiliza **FFmpeg** como motor de processamento.

O objetivo deste projeto é oferecer uma ferramenta simples e segura para reprocessar vídeos de conteúdo próprio: remover metadados, reencodar para H.264/AAC, aplicar crop e redimensionamento, e gerar arquivos MP4 otimizados para streaming (`+faststart`).

> **Aviso importante**  
> Este sistema é um processador/normalizador de vídeo para conteúdo próprio.  
> Ele **não** implementa e **não** promete mecanismos destinados a burlar sistemas de detecção, moderação ou enforcement de plataformas.

---

## Requisitos

- Python 3.9 ou superior
- FFmpeg instalado e disponível no `PATH` do sistema

### Instalação do FFmpeg

**Ubuntu / Debian**
```bash
sudo apt update
sudo apt install ffmpeg
```

**Fedora**
```bash
sudo dnf install ffmpeg
```

**macOS (Homebrew)**
```bash
brew install ffmpeg
```

**Windows**  
Baixe o binário em [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) e adicione a pasta ao `PATH`.

Verifique a instalação:
```bash
ffmpeg -version
```

---

## Instalação do projeto

```bash
git clone https://github.com/isabelarocha001/video-deduplicator.git
cd video-deduplicator

# (opcional) ambiente virtual
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
# ou, para desenvolvimento:
pip install -e ".[dev]"
```

---

## Uso (CLI)

O ponto de entrada principal é:

```bash
python -m app.cli process --input <entrada> --output <saída>
```

### Exemplo básico

```bash
python -m app.cli process \
  --input input/video.mp4 \
  --output output/video_processed.mp4
```

### Opções disponíveis

| Opção                  | Descrição                                      | Padrão     |
|------------------------|------------------------------------------------|------------|
| `--input` / `-i`       | Arquivo de vídeo de entrada                    | (obrigatório) |
| `--output` / `-o`      | Arquivo de saída (MP4)                         | (obrigatório) |
| `--remove-metadata`    | Remove metadados (`-map_metadata -1`)          | ativado    |
| `--no-remove-metadata` | Mantém metadados originais                     | –          |
| `--crop`               | Crop no formato `w:h:x:y` (ex.: `1280:720:0:0`) | –        |
| `--width`              | Largura de saída (pixels)                      | –          |
| `--height`             | Altura de saída (pixels)                       | –          |
| `--preserve-aspect`    | Preserva proporção ao redimensionar            | ativado    |
| `--no-preserve-aspect` | Força dimensões exatas                         | –          |
| `--crf`                | Qualidade libx264 (0-51, menor = melhor)       | 23         |
| `--preset`             | Preset de encoding (`ultrafast` … `veryslow`)  | medium     |
| `--subtle`             | Ajustes mínimos (contraste/saturação +1%, crop 1px, volume +1%) | desativado |
| `--trim-start SECS`    | Corta N segundos do início                     | –          |
| `--trim-end SECS`      | Corta N segundos do final (requer ffprobe)     | –          |

### Exemplos avançados

**Republicar conteúdo próprio (metadados + fingerprint sutil):**
```bash
python -m app.cli process \
  --input input/video.mp4 \
  --output output/video_limpo.mp4 \
  --subtle \
  --trim-start 0.5 \
  --trim-end 0.5 \
  --crf 18 \
  --preset slow
```


**Remover metadados + redimensionar para 1280px de largura (mantendo proporção):**
```bash
python -m app.cli process \
  --input input/video.mp4 \
  --output output/video_hd.mp4 \
  --width 1280 \
  --crf 20 \
  --preset slow
```

**Crop + reencode:**
```bash
python -m app.cli process \
  --input input/video.mp4 \
  --output output/video_cropped.mp4 \
  --crop 1280:720:100:50
```

---

## Comportamento do processador

1. Valida se o arquivo de entrada existe e possui extensão suportada.
2. Verifica se o FFmpeg está instalado.
3. Constrói a linha de comando de forma segura (lista de argumentos, sem concatenação insegura de strings).
4. Reencoda vídeo com `libx264` e áudio com `aac`.
5. Remove metadados quando solicitado (`-map_metadata -1`).
6. Aplica crop e/ou scale conforme as opções.
7. Usa `-movflags +faststart` para otimização de streaming.
8. Gera o arquivo final em MP4.

### Formatos de entrada suportados

`.mp4`, `.mkv`, `.avi`, `.mov`, `.webm`, `.flv`, `.wmv`, `.m4v`

---

## Testes

```bash
pip install -r requirements.txt
pytest -v
```

Os testes cobrem:
- Validação de arquivo de entrada (existência, tipo, extensão)
- Detecção de FFmpeg ausente
- Construção correta dos argumentos do FFmpeg
- Opções de crop, resize, CRF e preset

---

## Limitações

- O projeto depende do FFmpeg instalado no sistema; não inclui binários.
- Não há interface gráfica; apenas CLI.
- O reencode sempre usa H.264 + AAC (não há opção de copy de streams).
- Crop e scale são aplicados via filtros de vídeo; valores inválidos podem fazer o FFmpeg falhar.
- Não há suporte a processamento em lote nativo (um arquivo por execução).
- O sistema **não** implementa e **não** se destina a contornar detecção de conteúdo em plataformas.

---

## Estrutura do repositório

```
video-deduplicator/
├── app/
│   ├── __init__.py
│   ├── cli.py          # Interface de linha de comando
│   └── processor.py    # Lógica de processamento com FFmpeg
├── tests/
│   └── test_processor.py
├── input/              # Coloque vídeos de teste aqui
├── output/             # Arquivos processados
├── README.md
├── requirements.txt
├── pyproject.toml
└── .gitignore
```

---

## Licença

MIT


## Bunny CDN

Upload do arquivo processado para Bunny Storage e URL pública via Pull Zone.

### Variáveis de ambiente

```bash
export BUNNY_STORAGE_ZONE=privsexv5
export BUNNY_STORAGE_API_KEY="***"          # storage password
export BUNNY_STORAGE_HOST=br.storage.bunnycdn.com
export BUNNY_CDN_HOSTNAME=privsexcdnv5.b-cdn.net
```

Veja também `.env.example`.

### Comandos

Validar config (não imprime o secret completo):

```bash
python -m app.cli cdn-config
```

Processar + enviar para CDN:

```bash
python -m app.cli process \
  --input input/video.mp4 \
  --output output/video_limpo.mp4 \
  --subtle \
  --upload-cdn \
  --cdn-prefix uploads
```

Só upload de arquivo já processado:

```bash
python -m app.cli upload-cdn \
  --input output/video_limpo.mp4 \
  --remote-path uploads/video_limpo.mp4
```


### Registrar no Supabase (`vd_media`)

Após o upload CDN, grava `public_url` / `storage_path` em `vd_media` e fingerprint `exact` (SHA-256):

```bash
export SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="***"

python -m app.cli process \
  -i input/video.mp4 \
  -o output/video_limpo.mp4 \
  --subtle \
  --upload-cdn \
  --register-supabase \
  --caption "Meu vídeo"
```


## API HTTP (frontend + Vercel)

O backend FastAPI em `api/index.py` expõe:

| Método | Rota | Função |
|--------|------|--------|
| GET | `/api/health` | Status (ffmpeg, bunny, supabase) |
| GET | `/api/cdn-config` | Config CDN (sem secrets) |
| GET | `/api/media` | Lista `vd_media` (feed) |
| POST | `/api/process` | Processa vídeo (FFmpeg) |
| POST | `/api/upload-cdn` | Upload Bunny (+ opcional Supabase) |
| POST | `/api/process-and-publish` | Processa → CDN → registra |

O frontend (`public/js/app.js`) carrega o feed via `/api/media` e publica pelo botão **＋** chamando `process-and-publish` ou `upload-cdn`.

### Dev local

```bash
export SUPABASE_URL=...
export SUPABASE_SERVICE_ROLE_KEY=...
export BUNNY_STORAGE_ZONE=...
export BUNNY_STORAGE_API_KEY=...
export BUNNY_CDN_HOSTNAME=...

pip install -r requirements.txt
uvicorn api.index:app --reload --port 8000
# abra http://127.0.0.1:8000
```

Na Vercel, configure as mesmas variáveis de ambiente no painel do projeto. **FFmpeg** pode não estar disponível no serverless — nesse caso use `/api/upload-cdn` com arquivo já processado, ou rode o process localmente via CLI.



## Rendi.dev (FFmpeg na nuvem)

Quando não há FFmpeg local (ex.: Vercel), use [Rendi](https://www.rendi.dev/docs/introduction):

```bash
export RENDI_API_KEY=***
# Bunny ainda é usado para URL pública de entrada + CDN final
export BUNNY_STORAGE_ZONE=...
export BUNNY_STORAGE_API_KEY=...
export BUNNY_CDN_HOSTNAME=...

python -m app.cli process \
  -i video.mp4 -o out.mp4 \
  --rendi --subtle \
  --upload-cdn --register-supabase
```

Fluxo `--rendi`:
1. Sobe o original para Bunny (URL pública)
2. `POST /v1/run-ffmpeg-command` no Rendi
3. Poll até `SUCCESS`
4. Baixa o resultado e (opcional) reenvia ao CDN + `vd_media`

`POST /api/process-and-publish` usa Rendi automaticamente se `RENDI_API_KEY` estiver setado e FFmpeg local ausente (ou `FORCE_RENDI=1`).
