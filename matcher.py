import re
import unicodedata
from typing import List, Set, Tuple, Optional, Dict, Any
import pymorphy3

morph = pymorphy3.MorphAnalyzer(lang='uk')

def normalize_text(text: str) -> str:
    """Normalizes whitespace and unicode quotes/dashes."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r'[\u2019\u2018\u02BC`]', "'", text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_name_components(raw_name: str) -> Dict[str, Any]:
    """
    Parses user input into surname, first_name, patronymic, and initials.
    Examples:
    - "Гавриленко Володимир Анатолійович" -> surname="Гавриленко", first_name="Володимир", patronymic="Анатолійович", initials=("В", "А")
    - "Подольська Д.М." -> surname="Подольська", initials=("Д", "М")
    - "Коваль Петро" -> surname="Коваль", first_name="Петро", initials=("П",)
    - "Шевченко" -> surname="Шевченко"
    """
    clean = normalize_text(raw_name)
    parts = clean.split()
    if not parts:
        return {"raw": raw_name, "surname": "", "stem": "", "forms": set()}

    surname = parts[0]
    first_name = None
    patronymic = None
    initials = []

    if len(parts) > 1:
        rest = " ".join(parts[1:])
        # Check for initials like "В.А.", "В. А.", "В."
        init_matches = re.findall(r'([А-ЯІЇЄҐA-Z])\.', rest)
        if init_matches:
            initials = [i.upper() for i in init_matches]
        else:
            first_name = parts[1]
            initials.append(first_name[0].upper())
            if len(parts) > 2:
                patronymic = parts[2]
                initials.append(patronymic[0].upper())

    # Generate grammatical forms of the surname
    forms = get_all_surname_forms(surname)
    stem = get_search_stem(surname)

    return {
        "raw": clean,
        "surname": surname,
        "first_name": first_name,
        "patronymic": patronymic,
        "initials": tuple(initials),
        "forms": forms,
        "stem": stem
    }

def get_search_stem(surname: str) -> str:
    """
    Computes a robust stem suitable for website GET ?search= query.
    For example:
    - Гавриленко -> Гавриленк (matches Гавриленка, Гавриленко, Гавриленком)
    - Подольська -> Подольськ (matches Подольської, Подольська, Подольській)
    - Шевченко -> Шевченк (matches Шевченка, Шевченку)
    - Коваль -> Ковал (matches Коваля, Ковалю, Коваль)
    - Карпенко -> Карпенк
    - Ненич -> Ненич (or Ненич / Ненича)
    """
    s = surname.strip()
    if len(s) <= 4:
        return s

    lower = s.lower()
    # Common Ukrainian adjective/surname endings
    if lower.endswith(("ський", "ського", "ському", "ським")):
        return s[:-4]
    if lower.endswith(("ська", "ської", "ській", "ською")):
        return s[:-4]
    if lower.endswith(("цький", "цького", "цькому", "цьким")):
        return s[:-4]
    if lower.endswith(("цька", "цької", "цькій", "цькою")):
        return s[:-4]
    if lower.endswith(("ий", "ого", "ому", "им", "их", "ій", "ої")):
        return s[:-2]
    if lower.endswith(("ко", "ка", "ку", "ком")):
        return s[:-2] if lower.endswith(("ком",)) else s[:-1]
    if lower.endswith(("ов", "єв", "єва", "ова", "ову", "єву")):
        return s[:-1] if lower.endswith(("ва", "ву")) else s
    if lower.endswith(("я", "ю", "ем")):
        # e.g. Коваля -> Ковал
        return s[:-1] if lower.endswith(("я", "ю")) else s[:-2]

    # Default: if longer than 5 chars, return up to last character if ending in vowel
    if len(s) > 4 and lower[-1] in "аеєиіїоуюя":
        return s[:-1]
    return s

def get_all_surname_forms(surname: str) -> Set[str]:
    """
    Uses pymorphy3 to generate Ukrainian inflections of the surname.
    """
    forms = {surname.lower()}
    parsed_variants = morph.parse(surname)
    for p in parsed_variants:
        for case in ['nomn', 'gent', 'datv', 'accs', 'ablt', 'loct']:
            try:
                inflected = p.inflect({case})
                if inflected and inflected.word:
                    forms.add(inflected.word.lower())
            except Exception:
                pass

    # Also add standard Ukrainian manual patronymic/surname declensions if not already present
    lower = surname.lower()
    if lower.endswith("ко"):
        forms.add(lower[:-1] + "ка")  # Гавриленка
        forms.add(lower[:-1] + "ку")  # Гавриленку
    elif lower.endswith("ка"):
        forms.add(lower[:-1] + "кої") # Подольської
        forms.add(lower[:-1] + "ку")
    elif lower.endswith("ський"):
        forms.add(lower[:-2] + "ого") # Потопальського
    elif lower.endswith("ська"):
        forms.add(lower[:-2] + "ої")  # Подольської

    return forms

def match_summons_title(title: str, person_data: Dict[str, Any]) -> Tuple[bool, float, str]:
    """
    Checks if a post title refers to the tracked person.
    Returns: (is_match, confidence, reason)
    confidence: 1.0 (Full match with initials/names), 0.85 (Strong surname+initial match), 0.6 (Surname only)
    """
    norm_title = normalize_text(title)
    norm_title_lower = norm_title.lower()

    surname = person_data.get("surname", "")
    forms = person_data.get("forms", set())
    stem = person_data.get("stem", "").lower()
    initials = person_data.get("initials", ())
    first_name = person_data.get("first_name")
    patronymic = person_data.get("patronymic")

    # Step 1: Check if surname or any of its forms appears as a word/stem in the title
    surname_matched = False
    matched_word = ""

    # Check known morphological forms with word boundaries
    for form in forms:
        pattern = r'(?:\b|[^\wа-яіїєґ])' + re.escape(form) + r'(?:\b|[^\wа-яіїєґ])'
        if re.search(pattern, norm_title_lower):
            surname_matched = True
            matched_word = form
            break

    # If not found via exact form, check stem
    if not surname_matched and stem and len(stem) >= 4:
        pattern = r'(?:\b|[^\wа-яіїєґ])' + re.escape(stem) + r'[а-яіїєґ]*(?:\b|[^\wа-яіїєґ])'
        match = re.search(pattern, norm_title_lower)
        if match:
            surname_matched = True
            matched_word = match.group(0).strip()

    if not surname_matched:
        return False, 0.0, "Прізвище не знайдено"

    # Step 2: Surname matched. Now check first name / patronymic / initials
    # If the user only gave a surname without first name or initials:
    if not initials and not first_name:
        return True, 0.7, f"Збіг за прізвищем ({matched_word})"

    # Check if first name is in title
    fn_matched = False
    if first_name:
        fn_forms = {first_name.lower()}
        for p in morph.parse(first_name):
            for c in ['nomn', 'gent', 'datv', 'accs']:
                inf = p.inflect({c})
                if inf:
                    fn_forms.add(inf.word.lower())
        for fn in fn_forms:
            if re.search(r'(?:\b|[^\wа-яіїєґ])' + re.escape(fn) + r'(?:\b|[^\wа-яіїєґ])', norm_title_lower):
                fn_matched = True
                break

    # Check if patronymic is in title
    patr_matched = False
    if patronymic:
        patr_forms = {patronymic.lower()}
        for p in morph.parse(patronymic):
            for c in ['nomn', 'gent']:
                inf = p.inflect({c})
                if inf:
                    patr_forms.add(inf.word.lower())
        for pt in patr_forms:
            if re.search(r'(?:\b|[^\wа-яіїєґ])' + re.escape(pt) + r'(?:\b|[^\wа-яіїєґ])', norm_title_lower):
                patr_matched = True
                break

    if fn_matched and patr_matched:
        return True, 1.0, f"Повний збіг ПІБ ({person_data.get('raw')})"

    if fn_matched and not patronymic:
        return True, 0.95, f"Збіг прізвища та імені ({surname} {first_name})"

    # Check initials in title (e.g. "В.А.", "В. А.", "В. М.", "Д.М.")
    if initials:
        first_init = initials[0]
        second_init = initials[1] if len(initials) > 1 else None

        if second_init:
            # Pattern like "В.А." or "В. А." or "В.А"
            init_pattern = re.escape(first_init) + r'\.\s*' + re.escape(second_init) + r'\.?'
            if re.search(init_pattern, norm_title, re.IGNORECASE):
                return True, 0.95, f"Збіг прізвища та ініціалів ({surname} {first_init}.{second_init}.)"
        else:
            # Single initial pattern
            init_pattern = re.escape(first_init) + r'\.'
            if re.search(init_pattern, norm_title, re.IGNORECASE):
                return True, 0.85, f"Збіг прізвища та ініціалу ({surname} {first_init}.)"

    # If first name or initials were requested but the title had DIFFERENT initials/names, return false
    # Let's check if title has explicit other initials near the surname
    # Example: user searches "Гавриленко Володимир", but title says "Гавриленко В.М." (if user gave initials and they differ)
    return False, 0.0, "Прізвище збіглося, але ініціали чи ім'я відрізняються"
