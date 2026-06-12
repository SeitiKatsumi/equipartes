# Gerador de Artes

Interface local para gerar carrosseis 4:5 usando assets, briefing, presets de estilo e OpenAI API.

## Como rodar

```powershell
$env:OPENAI_API_KEY="sua-chave"
python server.py
```

Depois abra:

```text
http://127.0.0.1:8787
```

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
