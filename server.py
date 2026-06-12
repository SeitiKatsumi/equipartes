from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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


STYLE_PRESETS: dict[str, str] = {
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
    return json.loads(raw.decode("utf-8"))


def safe_path(value: str) -> Path:
    if not value or not value.strip():
        raise ValueError("Caminho vazio.")
    return Path(value.strip().strip('"')).expanduser()


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
Voce e um estrategista de conteudo para carrosseis de Instagram da marca 11RUN.
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
    assets_path = safe_path(payload["assetsPath"])
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
    for idx in range(1, slide_count + 1):
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
        im = Image.open(raw_path).convert("RGB")
        left = max(0, (im.width - 1080) // 2)
        top = max(0, (im.height - 1350) // 2)
        im.crop((left, top, left + 1080, top + 1350)).save(final_path, quality=96)
        maybe_apply_real_logo(final_path, logo_path, logo_mode)
        generated.append(str(final_path))

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
        "outputPath": str(output_path),
        "copyPath": str(copy_file) if copy_file.exists() else None,
        "previewPath": str(preview_path) if generated else None,
        "images": generated,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
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
                data = find_assets(safe_path(payload["assetsPath"]))
            elif self.path == "/api/generate-copy":
                data = {"copy": generate_copy(payload)}
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
