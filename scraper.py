import re
import logging
from html import unescape
from typing import List, Dict, Any, Optional
from urllib.parse import quote, urljoin
from curl_cffi.requests import AsyncSession

from config import GP_BASE_URL, SUMMONS_FULL_URL

logger = logging.getLogger(__name__)


class GPScraper:
    def __init__(self):
        self.impersonate = "chrome124"

    async def _fetch_html(self, url: str) -> Optional[str]:
        try:
            async with AsyncSession(impersonate=self.impersonate, timeout=20) as session:
                response = await session.get(url)
                if response.status_code == 200:
                    return response.text
                else:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status_code}")
                    return f"HTTP_ERROR_{response.status_code}: {response.text[:200]}"
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return f"EXCEPTION_{type(e).__name__}: {str(e)}"



    def _parse_summons_list(self, html: str) -> List[Dict[str, Any]]:
        """Parses summons items from category or search HTML page."""
        items = []
        if not html or html.startswith("HTTP_ERROR_") or html.startswith("EXCEPTION_"):
            return items


        # News item pattern
        item_pattern = r'<div class="news-item">.*?<div class="news_title">\s*<a href="([^"]+)">(.*?)</a>.*?<a[^>]*class="news_date">(.*?)</a>'
        matches = re.finditer(item_pattern, html, re.DOTALL)
        for m in matches:
            url = m.group(1).strip()
            raw_title = m.group(2)
            raw_date = m.group(3)

            # Clean title
            title = re.sub(r'<[^>]+>', '', raw_title).strip()
            title = unescape(title)

            # Clean date
            date = re.sub(r'<[^>]+>', '', raw_date).strip()

            # Ensure absolute URL
            if not url.startswith("http"):
                url = urljoin(GP_BASE_URL, url)

            # Skip general navigation links if any
            if not title or "pamyatka-pro-prava" in url:
                continue

            items.append({
                "title": title,
                "url": url,
                "date": date
            })

        return items

    async def get_latest_summons(self, page: int = 1) -> List[Dict[str, Any]]:
        """Retrieves latest summons publications from page N."""
        url = SUMMONS_FULL_URL
        if page > 1:
            url = f"{url}?page={page}"
        html = await self._fetch_html(url)
        return self._parse_summons_list(html)

    async def search_summons(self, search_term: str, page: int = 1) -> List[Dict[str, Any]]:
        """Performs a search query on the summons category."""
        encoded_term = quote(search_term.strip())
        url = f"{SUMMONS_FULL_URL}?search={encoded_term}"
        if page > 1:
            url = f"{url}&page={page}"
        html = await self._fetch_html(url)
        return self._parse_summons_list(html)

    async def get_post_details(self, post_url: str) -> Dict[str, Any]:
        """
        Fetches detailed information and document attachments from a specific summons post.
        """
        html = await self._fetch_html(post_url)
        details = {
            "url": post_url,
            "title": "",
            "date": "",
            "body": "",
            "document_url": None,
            "document_name": None,
            "case_number": None
        }
        if not html:
            return details

        # 1. Title
        title_match = re.search(r'<div class="page-title-block">(.*?)</div>', html, re.DOTALL)
        if title_match:
            details["title"] = unescape(re.sub(r'<[^>]+>', '', title_match.group(1)).strip())
        else:
            og_title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if og_title:
                details["title"] = unescape(og_title.group(1).strip())

        # 2. Date
        date_match = re.search(r'<div class="content-date">(.*?)</div>', html, re.DOTALL)
        if date_match:
            details["date"] = unescape(re.sub(r'<[^>]+>', '', date_match.group(1)).strip())

        # 3. Document attachment link
        # Look for download link like documents.html?_m=fslib or .pdf
        doc_matches = re.finditer(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
        for dm in doc_matches:
            href = dm.group(1).strip()
            link_text = unescape(re.sub(r'<[^>]+>', '', dm.group(2)).strip())
            href_lower = href.lower()
            if "_m=fslib" in href_lower or "download" in href_lower or href_lower.endswith((".pdf", ".doc", ".docx")):
                if not href.startswith("http"):
                    href = urljoin(GP_BASE_URL, href)
                details["document_url"] = href
                details["document_name"] = link_text or "Завантажити офіційний документ"
                break

        # 4. Case number (кримінальне провадження № ...)
        case_match = re.search(r'(?:кримінальн\w+\s+провадженн\w+\s+№?\s*|КП\s*№?\s*)(\d{8,})', html, re.IGNORECASE)
        if case_match:
            details["case_number"] = case_match.group(1)

        # 5. Body preview
        content_match = re.search(r'<div class="news-block content-block full-width">(.*?)</div>\s*</div>', html, re.DOTALL)
        if content_match:
            clean_body = re.sub(r'<[^>]+>', ' ', content_match.group(1))
            clean_body = unescape(re.sub(r'\s+', ' ', clean_body).strip())
            details["body"] = clean_body[:500]

        return details

scraper = GPScraper()
