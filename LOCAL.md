# Uso 100% local (sem Supabase / sem nuvem)

Tudo roda no seu PC. Arquivos saem na pasta `output/`.

## Requisitos

```bash
pip install -r requirements.txt
# Para vídeo também precisa do FFmpeg no PATH:
ffmpeg -version
```

## Fotos

### Uma foto

```bash
python -m vd.cli process-image -i minha_foto.jpg
# → output/minha_foto_clean.jpg
```

Com modo mais forte:

```bash
python -m vd.cli process-image -i foto.jpg -o output/foto_limpa.jpg --mode medium
```

### Várias fotos (lote)

Coloque as fotos numa pasta (ex: `input/`) e rode:

```bash
python -m vd.cli process-images -i input/ -o output/ --mode light
```

Opções úteis:

```bash
# 2 variações por foto, modo médio
python -m vd.cli process-images -i input/ -o output/ --mode medium --variations 2

# crop um pouco maior
python -m vd.cli process-images -i input/ -o output/ --mode light --crop-percent 3
```

Cada foto gera arquivo(s) em `output/`:
- `nome_v1.jpg`
- `nome_v2.jpg` (se variations > 1)

**O que acontece em cada foto:**
1. Cópia só de pixels (joga metadados fora)
2. Microedições (crop, rotação leve, cor…)
3. Duplo re-encode JPEG limpo
4. Salva em `output/`

## Vídeo

```bash
python -m vd.cli process -i input/video.mp4 -o output/video_limpo.mp4 --mode light
```

Com microedições mais fortes:

```bash
python -m vd.cli process -i input/video.mp4 -o output/video_limpo.mp4 --mode strong --subtle
```

## Fluxo prático no dia a dia

```
1. Joga fotos originais em input/
2. Roda:
   python -m vd.cli process-images -i input/ -o output/ --mode light
3. Pega os arquivos de output/ e posta onde quiser
```

Sem conta, sem Supabase, sem CDN. Só disco local.
