#!/usr/bin/env python3
"""Find PDFs for publication entries and save representative figure thumbnails.

The script intentionally keeps downloaded PDFs outside the repository and only
commits the cropped PNG figures plus publication front matter updates.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import fitz  # PyMuPDF


ROOT = Path(__file__).resolve().parents[1]
PUBLICATIONS = ROOT / "_publications"
IMAGE_DIR = ROOT / "images" / "publication-figures"
CACHE_DIR = Path(os.environ.get("PUBLICATION_PDF_CACHE", "/private/tmp/academic_publication_pdfs"))
SOURCES_JSON = IMAGE_DIR / "sources.json"

UA = "Mozilla/5.0 (compatible; AcademicHomepageFigureBot/1.0)"
SLEEP_SECONDS = 0.35

PDF_OVERRIDES: dict[str, str] = {
    "Domain adaptation with invariant representation learning: What transformations to learn?": (
        "https://proceedings.neurips.cc/paper/2021/file/"
        "cfc5d9422f0c8f8ad796711102dbe32b-Paper.pdf"
    ),
}

FIGURE_KEYWORDS = (
    "overview",
    "framework",
    "architecture",
    "model",
    "method",
    "pipeline",
    "proposed",
    "generative",
    "generation",
    "data generating",
    "data generation",
    "mechanism",
    "causal graph",
    "causal structure",
    "latent",
    "transition",
    "representation",
    "identifiability",
)


@dataclass
class Publication:
    path: Path
    slug: str
    title: str
    venue: str
    paperurl: str


def request_url(url: str, *, accept: str | None = None, timeout: int = 30) -> bytes:
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def normalize_title(value: str) -> str:
    value = value.lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def title_ratio(left: str, right: str) -> float:
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def read_front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.S)
    if not match:
        return {}
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        data[key.strip()] = value
    return data


def write_front_matter_value(path: Path, key: str, value: str) -> bool:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.S)
    if not match:
        return False

    fm = match.group(1)
    line = f'{key}: "{value}"'
    if re.search(rf"^{re.escape(key)}\s*:", fm, flags=re.M):
        updated_fm = re.sub(rf"^{re.escape(key)}\s*:.*$", line, fm, flags=re.M)
    else:
        updated_fm = fm.rstrip() + "\n" + line

    updated = "---\n" + updated_fm + "\n---\n" + text[match.end():]
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def load_publications() -> list[Publication]:
    pubs: list[Publication] = []
    for path in sorted(PUBLICATIONS.glob("20*.md")):
        data = read_front_matter(path)
        title = data.get("title", "").strip()
        if not title or "Paper Title Number" in title:
            continue
        pubs.append(
            Publication(
                path=path,
                slug=path.stem,
                title=title,
                venue=data.get("venue", ""),
                paperurl=data.get("paperurl", ""),
            )
        )
    return pubs


def candidate_from_arxiv_id(pub: Publication) -> list[str]:
    match = re.search(r"arXiv:([0-9]{4}\.[0-9]{4,5})(v[0-9]+)?", pub.venue, flags=re.I)
    if not match:
        return []
    arxiv_id = match.group(1)
    return [f"https://arxiv.org/pdf/{arxiv_id}.pdf", f"https://arxiv.org/pdf/{arxiv_id}"]


def search_semantic_scholar(pub: Publication) -> list[str]:
    query = urllib.parse.urlencode(
        {
            "query": pub.title,
            "limit": "8",
            "fields": "title,year,venue,openAccessPdf,externalIds,url,isOpenAccess",
        }
    )
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{query}"
    try:
        payload = json.loads(request_url(url, accept="application/json").decode("utf-8"))
    except Exception as exc:
        print(f"  semantic scholar failed: {exc}")
        return []

    urls: list[str] = []
    for item in payload.get("data", []):
        if title_ratio(pub.title, item.get("title", "")) < 0.76:
            continue
        pdf = item.get("openAccessPdf") or {}
        if pdf.get("url"):
            urls.append(pdf["url"])
        arxiv_id = (item.get("externalIds") or {}).get("ArXiv")
        if arxiv_id:
            urls.append(f"https://arxiv.org/pdf/{arxiv_id}.pdf")
            urls.append(f"https://arxiv.org/pdf/{arxiv_id}")
    return dedupe(urls)


def search_openalex(pub: Publication) -> list[str]:
    query = urllib.parse.urlencode({"search": pub.title, "per-page": "8"})
    url = f"https://api.openalex.org/works?{query}"
    try:
        payload = json.loads(request_url(url, accept="application/json").decode("utf-8"))
    except Exception as exc:
        print(f"  openalex failed: {exc}")
        return []

    urls: list[str] = []
    for work in payload.get("results", []):
        if title_ratio(pub.title, work.get("display_name", "")) < 0.76:
            continue
        for location in [work.get("best_oa_location"), work.get("primary_location")]:
            if location and location.get("pdf_url"):
                urls.append(location["pdf_url"])
        for location in work.get("locations") or []:
            if location and location.get("pdf_url"):
                urls.append(location["pdf_url"])
        oa_url = (work.get("open_access") or {}).get("oa_url")
        if oa_url and oa_url.lower().endswith(".pdf"):
            urls.append(oa_url)
    return dedupe(urls)


def search_arxiv(pub: Publication) -> list[str]:
    query = urllib.parse.urlencode({"search_query": f'ti:"{pub.title}"', "start": "0", "max_results": "5"})
    url = f"https://export.arxiv.org/api/query?{query}"
    try:
        root = ET.fromstring(request_url(url, accept="application/atom+xml"))
    except Exception as exc:
        print(f"  arxiv failed: {exc}")
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    urls: list[str] = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        id_el = entry.find("atom:id", ns)
        if title_el is None or id_el is None:
            continue
        if title_ratio(pub.title, title_el.text or "") < 0.76:
            continue
        urls.append(id_el.text.replace("/abs/", "/pdf/") + ".pdf")
    return dedupe(urls)


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def find_pdf_candidates(pub: Publication) -> list[str]:
    if pub.paperurl:
        return [pub.paperurl]
    if pub.title in PDF_OVERRIDES:
        return [PDF_OVERRIDES[pub.title]]
    candidates: list[str] = []
    candidates.extend(candidate_from_arxiv_id(pub))
    candidates.extend(search_semantic_scholar(pub))
    time.sleep(SLEEP_SECONDS)
    candidates.extend(search_openalex(pub))
    time.sleep(SLEEP_SECONDS)
    candidates.extend(search_arxiv(pub))
    return dedupe(candidates)


def download_pdf(pub: Publication, candidates: list[str]) -> tuple[Path | None, str | None]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = CACHE_DIR / f"{pub.slug}.pdf"
    if pdf_path.exists() and pdf_path.stat().st_size > 1024:
        return pdf_path, None

    for url in candidates:
        try:
            data = request_url(url, accept="application/pdf", timeout=45)
        except urllib.error.HTTPError as exc:
            print(f"  download rejected {exc.code}: {url}")
            continue
        except Exception as exc:
            print(f"  download failed: {url} ({exc})")
            continue

        if not data.startswith(b"%PDF"):
            print(f"  not a PDF: {url}")
            continue

        pdf_path.write_bytes(data)
        return pdf_path, url
    return None, None


def page_caption_blocks(page: fitz.Page) -> list[tuple[float, fitz.Rect, str]]:
    blocks = page.get_text("dict").get("blocks", [])
    results: list[tuple[float, fitz.Rect, str]] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_text_parts: list[str] = []
            line_rect: fitz.Rect | None = None
            for span in line.get("spans", []):
                text = span.get("text", "")
                if text:
                    line_text_parts.append(text)
                span_rect = fitz.Rect(span.get("bbox", [0, 0, 0, 0]))
                line_rect = span_rect if line_rect is None else line_rect | span_rect

            line_text = " ".join(line_text_parts).strip()
            if not line_text or line_rect is None:
                continue
            lower = line_text.lower()
            match = re.match(r"^\s*(fig(?:ure)?\.?)\s*([0-9]+)", lower)
            if not match:
                continue
            figure_no = int(match.group(2))
            score = 100 + max(0, 20 - figure_no * 3)
            score += sum(3 for keyword in FIGURE_KEYWORDS if keyword in lower)
            if "table" in lower[:20]:
                score -= 20
            results.append((float(score), line_rect, line_text))

    if results:
        return results

    # Fallback for PDFs whose text extraction merges captions with paragraphs.
    for block in blocks:
        if block.get("type") != 0:
            continue
        text_parts: list[str] = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text_parts.append(span.get("text", ""))
        text = " ".join(text_parts).strip()
        if not text:
            continue
        lower = text.lower()
        match = re.search(r"\b(fig(?:ure)?\.?)\s*([0-9]+)", lower)
        if not match:
            continue
        figure_no = int(match.group(2))
        score = max(0, 12 - figure_no * 2)
        score += sum(2 for keyword in FIGURE_KEYWORDS if keyword in lower)
        if "table" in lower[:20]:
            score -= 6
        results.append((float(score), fitz.Rect(block["bbox"]), text))
    return results


def overlap_width(left: fitz.Rect, right: fitz.Rect) -> float:
    return max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))


def visual_rects(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing.get("rect", [0, 0, 0, 0]))
        if rect.width < 4 or rect.height < 4 or rect.width * rect.height < 32:
            continue
        rects.append(rect)

    try:
        images = page.get_image_info(xrefs=False)
    except Exception:
        images = []
    for image in images:
        rect = fitz.Rect(image.get("bbox", [0, 0, 0, 0]))
        if rect.width < 12 or rect.height < 12:
            continue
        rects.append(rect)
    return rects


def visual_crop_near_caption(page: fitz.Page, caption_rect: fitz.Rect) -> fitz.Rect | None:
    page_rect = page.rect
    width = page_rect.width
    height = page_rect.height
    margin = 18

    # Most paper figures sit above the caption, but some ICLR-style examples put
    # the caption beside or just below the drawing. Search a compact band around
    # the detected caption line and union nearby vector/image objects.
    top = max(margin, caption_rect.y0 - height * 0.38)
    bottom = min(height - margin, caption_rect.y1 + height * 0.12)

    if caption_rect.width > width * 0.45:
        column = fitz.Rect(margin, top, width - margin, bottom)
    elif (caption_rect.x0 + caption_rect.x1) / 2 < width / 2:
        column = fitz.Rect(margin, top, width / 2 + 20, bottom)
    else:
        column = fitz.Rect(width / 2 - 20, top, width - margin, bottom)

    candidates: list[fitz.Rect] = []
    for rect in visual_rects(page):
        if rect.y1 < top or rect.y0 > bottom:
            continue
        if overlap_width(rect, column) <= 0:
            continue
        candidates.append(rect)

    if not candidates:
        # Retry without a column assumption for full-width figures with short
        # captions that begin at the left edge.
        all_band = fitz.Rect(margin, top, width - margin, bottom)
        for rect in visual_rects(page):
            if rect.y1 < top or rect.y0 > bottom:
                continue
            if overlap_width(rect, all_band) <= 0:
                continue
            candidates.append(rect)

    if not candidates:
        return None

    union = candidates[0]
    for rect in candidates[1:]:
        union |= rect

    if union.width < 24 or union.height < 24:
        return None

    x0 = max(margin, union.x0 - 12)
    y0 = max(margin, union.y0 - 12)
    x1 = min(width - margin, union.x1 + 12)
    y1 = min(height - margin, max(union.y1, caption_rect.y1) + 18)

    if caption_rect.y0 > union.y1 - 4:
        y1 = min(height - margin, caption_rect.y1 + 18)
    return fitz.Rect(x0, y0, x1, y1)


def choose_figure_region(doc: fitz.Document) -> tuple[int, fitz.Rect, str]:
    best: tuple[float, int, fitz.Rect, str] | None = None
    max_pages = min(len(doc), 10)

    for page_index in range(max_pages):
        page = doc[page_index]
        page_text = page.get_text("text").lower()
        page_bonus = max(0, 8 - page_index)
        for score, rect, caption in page_caption_blocks(page):
            combined_score = score + page_bonus
            combined_score += sum(1 for keyword in FIGURE_KEYWORDS if keyword in page_text)
            if best is None or combined_score > best[0]:
                best = (combined_score, page_index, rect, caption)

    if best is None:
        page = doc[min(1, len(doc) - 1)]
        rect = page.rect
        crop = fitz.Rect(rect.x0 + 24, rect.y0 + 48, rect.x1 - 24, rect.y0 + rect.height * 0.52)
        return min(1, len(doc) - 1), crop, "Auto-selected upper page region"

    _, page_index, caption_rect, caption = best
    page = doc[page_index]
    visual_crop = visual_crop_near_caption(page, caption_rect)
    if visual_crop is not None:
        return page_index, visual_crop, caption

    page_rect = page.rect
    width = page_rect.width
    height = page_rect.height

    caption_width = caption_rect.width
    margin = 24
    if caption_width > width * 0.58:
        x0, x1 = margin, width - margin
    elif (caption_rect.x0 + caption_rect.x1) / 2 < width / 2:
        x0, x1 = margin, width / 2 - 8
    else:
        x0, x1 = width / 2 + 8, width - margin

    figure_height = min(caption_rect.y0 - margin, height * 0.46)
    y0 = max(margin, caption_rect.y0 - figure_height)
    y1 = min(height - margin, caption_rect.y1 + 14)

    # If the figure is very close to the top, use the whole top band.
    if caption_rect.y0 < height * 0.32:
        y0 = margin

    crop = fitz.Rect(x0, y0, x1, y1)
    return page_index, crop, caption


def render_figure(pub: Publication, pdf_path: Path) -> tuple[Path | None, str]:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    image_path = IMAGE_DIR / f"{pub.slug}.png"

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return None, f"could not open PDF: {exc}"

    try:
        page_index, crop, caption = choose_figure_region(doc)
        page = doc[page_index]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2.4, 2.4), clip=crop, alpha=False)
        pixmap.save(image_path)
        return image_path, f"page {page_index + 1}: {caption[:160]}"
    except Exception as exc:
        return None, f"render failed: {exc}"
    finally:
        doc.close()


def main() -> int:
    pubs = load_publications()
    print(f"found {len(pubs)} retained publications")

    sources: dict[str, dict[str, str]] = {}
    if SOURCES_JSON.exists():
        try:
            sources = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sources = {}

    missing: list[str] = []
    for index, pub in enumerate(pubs, 1):
        print(f"[{index}/{len(pubs)}] {pub.title}")
        candidates = find_pdf_candidates(pub)
        if not candidates:
            print("  no PDF candidates")
            missing.append(pub.title)
            continue

        pdf_path, pdf_url = download_pdf(pub, candidates)
        if not pdf_path:
            print("  could not download a usable PDF")
            missing.append(pub.title)
            continue

        image_path, note = render_figure(pub, pdf_path)
        if not image_path:
            print(f"  {note}")
            missing.append(pub.title)
            continue

        rel_image = image_path.relative_to(ROOT / "images").as_posix()
        write_front_matter_value(pub.path, "thumbnail", rel_image)
        if pdf_url:
            write_front_matter_value(pub.path, "paperurl", pdf_url)

        data = read_front_matter(pub.path)
        sources[pub.slug] = {
            "title": pub.title,
            "pdf_url": data.get("paperurl", pdf_url or ""),
            "image": rel_image,
            "selection": note,
        }
        print(f"  saved {rel_image} ({note})")

    SOURCES_JSON.write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if missing:
        print("\nmissing:")
        for title in missing:
            print(f"  - {title}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
