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

### Exemplos avançados

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
