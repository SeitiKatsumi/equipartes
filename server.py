from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import gettempdir
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from PIL import Image

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "web"
HOST = "127.0.0.1"
PORT = int(os.environ.get("ART_GEN_PORT", "8787"))
HOST = os.environ.get("ART_GEN_HOST", HOST)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ASSET_CACHE = Path(gettempdir()) / "gerador-artes-assets"
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


STYLE_PRESETS: dict[str, str] = {
    "neutro": (
        "Neutral premium editorial style for multiple clients: refined black or light neutral background depending on the references, "
        "brand-agnostic composition, elegant typography, clean infographic hierarchy, tasteful technical lines, subtle accent color from the supplied assets, "
        "no 11RUN-specific ornaments unless the assets clearly request them."
    ),
    "editorial_11run": (
        "Premium editorial 11RUN: black textured paper, elegant high-fashion serif typography, "
        "thin orange technical lines, target ornaments, dotted grid, ruler ticks, flat infographic layout, "
        "warm white and orange accents, minimal glow."
    ),
    "mais_ilustrativo": (
        "More illustrative: editorial composition with custom line-art illustrations, hand-drawn technical icons, "
        "subtle sport-specific visual metaphors, still premium black/orange/white and not cartoonish."
    ),
    "super_minimalista": (
        "Super minimalist: lots of negative space, very few ornaments, one strong serif headline, thin rules, "
        "small table blocks, restrained orange accents, quiet luxury."
    ),
    "flat_infografico": (
        "Flat infographic: structured grids, icon cards, clean tables, thin dividers, no 3D scenes, no photos, "
        "high readability and clear hierarchy."
    ),
    "tecnico_futurista": (
        "Technical futuristic: subtle HUD marks, vector grids, telemetry accents, precise diagrams, dark sport-tech mood, "
        "but still flat and editorial."
    ),
    "cinematico_ilustrado": (
        "Cinematic illustrated: deeper atmosphere, athlete silhouettes or environment hints, controlled depth and glow, "
        "without becoming 3D dashboard or stadium wallpaper."
    ),
}


def set_job(job_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(updates)
        job["updatedAt"] = time.time()


def get_job(job_id: str) -> dict[str, Any] | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return json.loads(text)


def safe_path(value: str) -> Path:
    if not value or not value.strip():
        raise ValueError("Caminho vazio.")
    return Path(value.strip().strip('"')).expanduser()


def is_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


def http_get(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 GeradorDeArtes/1.0"})
    with urlopen(request, timeout=45) as response:
        return response.read()


def extension_from_url_or_type(url: str, content_type: str | None = None) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return suffix
    guessed = mimetypes.guess_extension(content_type or "") if content_type else None
    return guessed if guessed in IMAGE_EXTS else ".png"


def google_drive_file_id(url: str) -> str | None:
    parsed = urlparse(url)
    if "drive.google.com" not in parsed.netloc:
        return None
    match = re.search(r"/file/d/([A-Za-z0-9_-]+)", parsed.path)
    if match:
        return match.group(1)
    query_id = parse_qs(parsed.query).get("id", [None])[0]
    return query_id


def google_drive_folder_id(url: str) -> str | None:
    parsed = urlparse(url)
    if "drive.google.com" not in parsed.netloc:
        return None
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
    return match.group(1) if match else None


def download_drive_file(file_id: str, target_dir: Path, index: int) -> Path | None:
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 GeradorDeArtes/1.0"})
    with urlopen(request, timeout=60) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type.lower():
        text = data.decode("utf-8", errors="ignore")
        token_match = re.search(r"confirm=([0-9A-Za-z_]+)", text)
        if token_match:
            data = http_get(f"{url}&confirm={token_match.group(1)}")
        else:
            return None
    ext = extension_from_url_or_type(url, content_type)
    path = target_dir / f"drive-{index:02d}{ext}"
    path.write_bytes(data)
    return path if path.stat().st_size > 0 else None


def extract_drive_folder_file_ids(folder_url: str) -> list[str]:
    folder_id = google_drive_folder_id(folder_url)
    if not folder_id:
        return []
    page = http_get(f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing").decode("utf-8", errors="ignore")
    ids: set[str] = set()
    for pattern in [
        r"/file/d/([A-Za-z0-9_-]+)",
        r'data-id="([A-Za-z0-9_-]+)"',
        r'\["([A-Za-z0-9_-]{20,})","[^"]+\.(?:png|jpg|jpeg|webp)"',
    ]:
        ids.update(re.findall(pattern, page, flags=re.I))
    return list(ids)[:40]


def download_url_asset(url: str, target_dir: Path, index: int) -> Path | None:
    file_id = google_drive_file_id(url)
    if file_id:
        return download_drive_file(file_id, target_dir, index)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 GeradorDeArtes/1.0"})
    with urlopen(request, timeout=60) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")
    if not (content_type.lower().startswith("image/") or Path(urlparse(url).path).suffix.lower() in IMAGE_EXTS):
        return None
    path = target_dir / f"url-{index:02d}{extension_from_url_or_type(url, content_type)}"
    path.write_bytes(data)
    return path


def resolve_assets_source(value: str, job_id: str | None = None) -> Path:
    raw = value.strip().strip('"')
    if not raw:
        raise ValueError("Informe uma pasta local, URL de imagem ou pasta publica do Google Drive.")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) == 1 and not is_url(lines[0]):
        return safe_path(lines[0])

    cache_id = job_id or uuid.uuid4().hex
    target_dir = ASSET_CACHE / cache_id
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    for index, line in enumerate(lines, start=1):
        if google_drive_folder_id(line):
            file_ids = extract_drive_folder_file_ids(line)
            for offset, file_id in enumerate(file_ids, start=len(downloaded) + 1):
                path = download_drive_file(file_id, target_dir, offset)
                if path:
                    downloaded.append(path)
            continue
        if is_url(line):
            path = download_url_asset(line, target_dir, index)
            if path:
                downloaded.append(path)

    if not downloaded:
        raise ValueError("Nenhuma imagem publica foi baixada. Verifique se a pasta/arquivo do Google Drive esta compartilhado.")
    return target_dir


def find_assets(assets_path: Path) -> dict[str, list[str]]:
    if not assets_path.exists():
        raise FileNotFoundError(f"Pasta de assets nao encontrada: {assets_path}")
    files = [
        p
        for p in assets_path.rglob("*")
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTS
        and "contact-sheet" not in p.name.lower()
        and "logos-on-dark" not in p.name.lower()
    ]
    logos = [p for p in files if "logo" in str(p).lower() or "branding" in str(p).lower() or "logotipia" in str(p).lower()]
    refs = [p for p in files if p not in logos]
    return {
        "logos": [str(p) for p in logos[:20]],
        "references": [str(p) for p in refs[:40]],
    }


def selected_asset_files(asset_scan: dict[str, list[str]], max_refs: int = 4) -> list[Path]:
    files: list[Path] = []
    if asset_scan["references"]:
        refs = sorted(
            (Path(p) for p in asset_scan["references"]),
            key=lambda p: (
                0 if "8 de jun" in p.name.lower() else 1,
                0 if "4 de jun" in p.name.lower() else 1,
                p.name.lower(),
            ),
        )
        files.extend(refs[:max_refs])
    if asset_scan["logos"]:
        files.append(Path(asset_scan["logos"][0]))
    return files


def split_slide_specs(brief: str, slide_count: int) -> list[str]:
    # Keeps explicit numbered slide structure when the user writes one.
    chunks = re.split(r"(?m)^\s*(?:slide\s*)?0?(\d{1,2})[\).\-\s]+", brief, flags=re.I)
    if len(chunks) > 2:
        pairs = []
        for i in range(1, len(chunks), 2):
            num = chunks[i]
            body = chunks[i + 1].strip() if i + 1 < len(chunks) else ""
            if body:
                pairs.append((int(num), body))
        pairs = sorted(pairs)[:slide_count]
        if pairs:
            return [body for _, body in pairs] + [""] * max(0, slide_count - len(pairs))
    return [brief.strip()] * slide_count


def image_prompt(
    *,
    briefing: str,
    slide_spec: str,
    style_id: str,
    slide_index: int,
    slide_count: int,
    logo_mode: str,
    copy_text: str,
) -> str:
    preset = STYLE_PRESETS.get(style_id, STYLE_PRESETS["editorial_11run"])
    logo_instruction = {
        "prompt": (
            "Use the attached logo image as a visual reference and integrate a small subtle brand mark in a strategic footer position, "
            "around 9-12 percent of the slide width. Do not make it large."
        ),
        "reserve": (
            "Reserve a clean strategic footer area for the real logo to be applied later. Do not render a fake logo or invented logo."
        ),
        "none": "Do not include a logo.",
    }.get(logo_mode, "Reserve a clean strategic footer area for the real logo to be applied later.")

    return f"""
Create one finished 4:5 Instagram carousel slide.

STYLE PRESET:
{preset}

GLOBAL BRIEFING:
{briefing}

SLIDE:
{slide_index} DE {slide_count}

SLIDE SPEC:
{slide_spec}

COPY GUIDANCE:
{copy_text}

LOGO:
{logo_instruction}

CRITICAL REQUIREMENTS:
- The image must look generated directly by ChatGPT/Image API, not like a rigid local template.
- Keep the layout polished, editorial, premium, and balanced.
- Use Portuguese text from the brief where possible.
- Make tables and numeric content legible.
- Avoid extra brands, watermarks, random logos, malformed UI screenshots, heavy 3D stadium scenes, and app dashboards unless explicitly requested.
- If exact small text is too dense, simplify the layout instead of making it unreadable.
""".strip()


def open_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("SDK openai nao instalado. Rode: python -m pip install openai")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY nao configurada no ambiente.")
    return OpenAI()


def generate_copy(payload: dict[str, Any]) -> str:
    client = open_client()
    style_id = payload.get("styleId", "editorial_11run")
    slide_count = int(payload.get("slideCount", 10))
    briefing = payload.get("briefing", "")
    model = payload.get("textModel") or os.environ.get("OPENAI_TEXT_MODEL", "gpt-5.1")
    prompt = f"""
Voce e um estrategista de conteudo para carrosseis de Instagram. Use a marca e o tom do cliente apenas quando estiverem claros no briefing ou nos assets.
Crie uma copy completa para o carrossel e uma estrutura slide a slide.

Estilo visual selecionado: {style_id} - {STYLE_PRESETS.get(style_id, "")}
Quantidade de slides: {slide_count}

Briefing:
{briefing}

Entregue em portugues:
1. Legenda do post, com hook forte e CTA.
2. Texto sugerido por slide, numerado de 01 a {slide_count:02d}.
3. Observacoes de design para manter clareza.
""".strip()
    try:
        response = client.responses.create(
            model=model,
            input=prompt,
        )
    except Exception:
        response = client.responses.create(
            model="gpt-4.1",
            input=prompt,
        )
    return response.output_text


def generate_briefing(payload: dict[str, Any]) -> dict[str, str]:
    client = open_client()
    topic = payload.get("topic", "").strip()
    if not topic:
        raise ValueError("Informe um tema para criar o roteiro.")
    client_name = payload.get("clientName", "").strip() or "cliente"
    audience = payload.get("audience", "").strip() or "público do Instagram"
    objective = payload.get("objective", "").strip() or "educar, gerar salvamentos e iniciar conversa"
    notes = payload.get("researchNotes", "").strip()
    style_id = payload.get("styleId", "neutro")
    slide_count = int(payload.get("slideCount", 10))
    model = payload.get("textModel") or os.environ.get("OPENAI_TEXT_MODEL", "gpt-5.1")

    prompt = f"""
Você é estrategista de conteúdo, pesquisador e roteirista de carrosséis para Instagram.
Crie um briefing completo para gerar artes 4:5 depois.

Tema: {topic}
Cliente/marca: {client_name}
Público: {audience}
Objetivo: {objective}
Quantidade de slides: {slide_count}
Estilo visual: {style_id} - {STYLE_PRESETS.get(style_id, "")}
Observações e fontes fornecidas pelo usuário:
{notes or "Nenhuma."}

Regras:
- Pesquise e organize o tema com cuidado quando houver ferramenta de busca disponível.
- Se algum dado parecer incerto ou temporal, sinalize no próprio roteiro como ponto a verificar.
- Entregue em português do Brasil.
- O roteiro deve estar pronto para colar no campo de briefing e gerar imagens.
- Use estrutura numerada 01 até {slide_count:02d}.
- Cada slide deve ter: título principal, texto curto de apoio, dados/exemplos quando úteis, direção visual.
- Inclua uma copy do post ao final, com hook, corpo, CTA e aviso se o tema exigir cuidado.
- Não invente promessas, números ou fontes específicas se não houver segurança.

Formato obrigatório:
BRIEFING PARA ARTES
01
TÍTULO:
TEXTO:
VISUAL:

...

COPY DO CARROSSEL
...
""".strip()

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            tools=[{"type": "web_search_preview"}],
        )
    except Exception:
        try:
            response = client.responses.create(model=model, input=prompt)
        except Exception:
            response = client.responses.create(model="gpt-4.1", input=prompt)

    text = response.output_text
    copy_marker = "COPY DO CARROSSEL"
    if copy_marker in text:
        briefing, copy = text.split(copy_marker, 1)
        copy = f"{copy_marker}{copy}".strip()
    else:
        briefing, copy = text, ""
    return {"briefing": briefing.strip(), "copy": copy.strip(), "full": text.strip()}


def maybe_apply_real_logo(image_path: Path, logo_path: Path | None, mode: str) -> None:
    if mode != "apply_real" or logo_path is None or not logo_path.exists():
        return
    im = Image.open(image_path).convert("RGBA")
    logo = Image.open(logo_path).convert("RGBA")
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    target_w = int(im.width * 0.12)
    logo.thumbnail((target_w, int(im.height * 0.07)), Image.Resampling.LANCZOS)
    x = (im.width - logo.width) // 2
    y = im.height - logo.height - int(im.height * 0.035)
    im.alpha_composite(logo, (x, y))
    im.convert("RGB").save(image_path, quality=96)


def generate_carousel(payload: dict[str, Any]) -> dict[str, Any]:
    client = open_client()
    job_id = payload.get("jobId")
    assets_path = resolve_assets_source(payload["assetsPath"], job_id=job_id)
    output_path = safe_path(payload["outputPath"])
    output_path.mkdir(parents=True, exist_ok=True)

    slide_count = int(payload.get("slideCount", 10))
    style_id = payload.get("styleId", "editorial_11run")
    briefing = payload.get("briefing", "")
    copy_text = payload.get("copyText", "")
    logo_mode = payload.get("logoMode", "reserve")
    image_model = payload.get("imageModel") or os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
    quality = payload.get("quality", "high")

    asset_scan = find_assets(assets_path)
    asset_files = selected_asset_files(asset_scan)
    logo_path = Path(asset_scan["logos"][0]) if asset_scan["logos"] else None
    slide_specs = split_slide_specs(briefing, slide_count)

    copy_file = output_path / "copy-carrossel.md"
    if copy_text:
        copy_file.write_text(copy_text, encoding="utf-8")

    raw_dir = output_path / "raw_1088x1360"
    final_dir = output_path / "final_1080x1350"
    raw_dir.mkdir(exist_ok=True)
    final_dir.mkdir(exist_ok=True)

    generated: list[str] = []
    raw_generated: list[str] = []
    for idx in range(1, slide_count + 1):
        if job_id:
            set_job(
                job_id,
                status="running",
                stage=f"Gerando slide {idx:02d}/{slide_count}",
                current=idx,
                total=slide_count,
            )
        prompt = image_prompt(
            briefing=briefing,
            slide_spec=slide_specs[idx - 1],
            style_id=style_id,
            slide_index=idx,
            slide_count=slide_count,
            logo_mode="prompt" if logo_mode == "prompt" else "reserve",
            copy_text=copy_text,
        )
        files = [open(p, "rb") for p in asset_files if p.exists()]
        try:
            result = client.images.edit(
                model=image_model,
                image=files,
                prompt=prompt,
                size="1088x1360",
                quality=quality,
            )
        finally:
            for file in files:
                file.close()

        raw_path = raw_dir / f"{idx:02d}-arte.png"
        final_path = final_dir / f"{idx:02d}-arte.png"
        raw_path.write_bytes(base64.b64decode(result.data[0].b64_json))
        raw_generated.append(str(raw_path))
        if job_id:
            set_job(
                job_id,
                stage=f"Finalizando slide {idx:02d}/{slide_count}",
                rawImages=raw_generated.copy(),
                images=generated.copy(),
            )
        im = Image.open(raw_path).convert("RGB")
        left = max(0, (im.width - 1080) // 2)
        top = max(0, (im.height - 1350) // 2)
        im.crop((left, top, left + 1080, top + 1350)).save(final_path, quality=96)
        maybe_apply_real_logo(final_path, logo_path, logo_mode)
        generated.append(str(final_path))
        if job_id:
            set_job(
                job_id,
                stage=f"Slide {idx:02d}/{slide_count} salvo",
                rawImages=raw_generated.copy(),
                images=generated.copy(),
            )

    preview_path = output_path / "preview-contact-sheet.jpg"
    if generated:
        thumbs = []
        for image in generated:
            im = Image.open(image).convert("RGB")
            im.thumbnail((216, 270), Image.Resampling.LANCZOS)
            thumbs.append(im.copy())
        cols = min(5, len(thumbs))
        rows = (len(thumbs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 216, rows * 270), (12, 12, 12))
        for idx, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((idx % cols) * 216, (idx // cols) * 270))
        sheet.save(preview_path, quality=92)

    return {
        "jobId": job_id,
        "outputPath": str(output_path),
        "copyPath": str(copy_file) if copy_file.exists() else None,
        "previewPath": str(preview_path) if generated else None,
        "images": generated,
    }


def start_carousel_job(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    set_job(
        job_id,
        id=job_id,
        status="queued",
        stage="Na fila",
        current=0,
        total=int(payload.get("slideCount", 10)),
        images=[],
        rawImages=[],
        result=None,
        error=None,
        createdAt=time.time(),
    )

    def runner() -> None:
        try:
            set_job(job_id, status="running", stage="Preparando assets")
            job_payload = dict(payload)
            job_payload["jobId"] = job_id
            result = generate_carousel(job_payload)
            set_job(
                job_id,
                status="done",
                stage="Concluido",
                current=int(payload.get("slideCount", 10)),
                result=result,
                images=result.get("images", []),
            )
        except Exception as exc:
            set_job(job_id, status="error", stage="Erro", error=str(exc))

    threading.Thread(target=runner, daemon=True).start()
    return {"jobId": job_id}


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    images = job.get("images", [])
    raw_images = job.get("rawImages", [])
    return {
        "id": job.get("id"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "current": job.get("current", 0),
        "total": job.get("total", 0),
        "error": job.get("error"),
        "result": job.get("result"),
        "images": [
            {"index": idx + 1, "url": f"/api/job-image?jobId={job.get('id')}&kind=final&index={idx}"}
            for idx, _ in enumerate(images)
        ],
        "rawImages": [
            {"index": idx + 1, "url": f"/api/job-image?jobId={job.get('id')}&kind=raw&index={idx}"}
            for idx, _ in enumerate(raw_images)
        ],
        "updatedAt": job.get("updatedAt"),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        query = parse_qs(urlparse(self.path).query)
        if path == "/api/job-status":
            job_id = query.get("jobId", [""])[0]
            job = get_job(job_id)
            if not job:
                json_response(self, {"error": "Job nao encontrado."}, 404)
                return
            json_response(self, public_job(job))
            return
        if path == "/api/job-image":
            job_id = query.get("jobId", [""])[0]
            kind = query.get("kind", ["final"])[0]
            try:
                index = int(query.get("index", ["0"])[0])
            except ValueError:
                index = -1
            job = get_job(job_id)
            if not job:
                json_response(self, {"error": "Job nao encontrado."}, 404)
                return
            key = "rawImages" if kind == "raw" else "images"
            images = job.get(key, [])
            if index < 0 or index >= len(images):
                json_response(self, {"error": "Imagem nao encontrada."}, 404)
                return
            image_path = Path(images[index])
            if not image_path.exists():
                json_response(self, {"error": "Arquivo nao encontrado."}, 404)
                return
            data = image_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(image_path))[0] or "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/":
            path = "/index.html"
        file_path = (PUBLIC / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(PUBLIC.resolve())) or not file_path.exists():
            json_response(self, {"error": "Not found"}, 404)
            return
        data = file_path.read_bytes()
        mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        try:
            payload = read_json(self)
            if self.path == "/api/health":
                data = {
                    "ok": True,
                    "openaiKey": bool(os.environ.get("OPENAI_API_KEY")),
                    "styles": list(STYLE_PRESETS.keys()),
                }
            elif self.path == "/api/scan-assets":
                data = find_assets(resolve_assets_source(payload["assetsPath"]))
            elif self.path == "/api/generate-briefing":
                data = generate_briefing(payload)
            elif self.path == "/api/generate-copy":
                data = {"copy": generate_copy(payload)}
            elif self.path == "/api/start-carousel":
                data = start_carousel_job(payload)
            elif self.path == "/api/generate-carousel":
                data = generate_carousel(payload)
            else:
                json_response(self, {"error": "Endpoint nao encontrado."}, 404)
                return
            json_response(self, data)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Gerador de Artes rodando em http://{HOST}:{PORT}")
    print("Pressione Ctrl+C para parar.")
    server.serve_forever()


if __name__ == "__main__":
    main()
