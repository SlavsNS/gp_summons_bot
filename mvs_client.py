import logging
from datetime import date
from typing import List, Dict, Any, Optional
from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

MVS_SEARCH_URL = "https://services.mvs.gov.ua/api/v1/user-requests/WNT02/search"

class MVSClient:
    def __init__(self):
        self.impersonate = "chrome110"
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://services.mvs.gov.ua",
            "Referer": "https://services.mvs.gov.ua/wnt/services/wanted-person-search",
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    async def search_wanted(
        self,
        last_name: str,
        first_name: str,
        middle_name: Optional[str] = None,
        birthday_from: str = "1900-01-01",
        birthday_to: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Queries MVS Wanted Persons database (services.mvs.gov.ua).
        Uses a wide birth date range (e.g. 1900 to present) by default.
        """
        if not birthday_to:
            birthday_to = date.today().isoformat()

        payload = {
            "lastName": last_name.strip(),
            "firstName": first_name.strip(),
            "birthdayFrom": birthday_from,
            "birthdayTo": birthday_to
        }
        if middle_name and middle_name.strip():
            payload["middlename"] = middle_name.strip()

        try:
            async with AsyncSession(impersonate=self.impersonate, timeout=25) as session:
                response = await session.post(MVS_SEARCH_URL, headers=self.headers, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        return data.get("data", [])
                    return []
                elif response.status_code == 422:
                    logger.warning(f"MVS validation error: {response.text}")
                    return []
                else:
                    logger.error(f"MVS search failed with status {response.status_code}: {response.text[:200]}")
                    return []
        except Exception as e:
            logger.error(f"Error during MVS search: {e}")
            raise e

mvs_client = MVSClient()
