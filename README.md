# Gerador de Artes

Interface local para gerar carrosseis 4:5 usando assets, briefing, presets de estilo e OpenAI API.

## Recursos

- Layout Neutro para usar com diferentes clientes.
- Presets editoriais e ilustrativos para direcionar a geracao.
- Geracao assincrona com barra de progresso e thumbs das artes geradas/finalizadas.
- Assets por pasta local, URL direta de imagem ou pasta publica do Google Drive.
- Copy do carrossel gerada junto do briefing.

## Como rodar

```powershell
$env:OPENAI_API_KEY="sua-chave"
python server.py
```

Depois abra:

```text
http://127.0.0.1:8787
```

## Assets

No campo `Assets`, use uma destas opcoes:

```text
D:\caminho\para\Assets
```

ou uma URL direta de imagem:

```text
https://site.com/referencia.png
```

ou uma pasta publica do Google Drive:

```text
https://drive.google.com/drive/folders/ID_DA_PASTA
```

Para varias URLs, coloque uma por linha. Pastas privadas do Google Drive precisam estar compartilhadas publicamente para o app conseguir baixar as imagens sem OAuth.

Se o `python` global nao estiver disponivel, use o Python empacotado do Codex:

```powershell
& "C:\Users\User-PC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" server.py
```

## Docker / CapRover

O projeto inclui `Dockerfile` e `captain-definition`.

No CapRover:

1. Crie um app novo.
2. Configure a variavel de ambiente `OPENAI_API_KEY`.
3. Faca deploy pelo GitHub ou via tar/CLI.

O container escuta na porta `80` usando:

```text
ART_GEN_HOST=0.0.0.0
ART_GEN_PORT=80
```

Para testar localmente com Docker:

```powershell
docker build -t gerador-artes .
docker run --rm -p 8787:80 -e OPENAI_API_KEY="sua-chave" gerador-artes
```
