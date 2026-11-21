"""
Módulo de Normalização de Strings, Extração de Metadados, Deduplicação e Heurística de Provedores.
"""
import re
import unicodedata
from typing import Dict, Optional, Set, Tuple
from config import REGEX_CATEGORIA_FALLBACK, REGEX_CATEGORIA_REJEICAO, REGEX_RUIDOS

_LEAD_LANG_TAG_RE = re.compile(
    r"^\s*[\[(|]?\s*(BR|PT|PTBR|PT-BR|EN|ENG|ES|ESP|LAT|LEG|DUB|SUB)\s*(?:[\])|]\s*[-–|:]?|\s*[-–|:])\s*",
    re.IGNORECASE,
)


def normalizar_titulo(raw_name: str) -> Tuple[str, Optional[int]]:
    """
    Remove ruídos comuns de IPTV (qualidade, áudio, dublagem, tags)
    e extrai o ano de lançamento de 4 dígitos.

    Exemplo:
        'Auto da Compadecida 2 (2024) [4K DUBLADO]' -> ('Auto da Compadecida 2', 2024)
    """
    if not raw_name:
        return "", None

    texto = str(raw_name).strip()
    for _ in range(2):
        m = _LEAD_LANG_TAG_RE.match(texto)
        if not m:
            break
        rest = texto[m.end() :].strip()
        if rest:
            texto = rest
        else:
            break

    # 1. Extração do ano de 4 dígitos (1900-2099)
    ano_match = re.search(r"\b(19\d\d|20\d\d)\b", texto)
    ano = int(ano_match.group(1)) if ano_match else None

    # 2. Remoção de ruídos de tags e resoluções
    limpo = REGEX_RUIDOS.sub(" ", texto)

    # 3. Remoção do ano se tiver ficado solto entre parênteses ou delimitadores
    if ano:
        limpo = re.sub(rf"\b{ano}\b", " ", limpo)

    # 4. Substituição de pontuações de separação por espaços
    limpo = re.sub(r"[\-–—:_|/\\\[\]()]", " ", limpo)

    # 5. Normalização de múltiplos espaços em branco
    limpo = re.sub(r"\s+", " ", limpo).strip()

    return limpo, ano


_ROMAN_PATTERNS = (
    (re.compile(r"\bviii\b", re.IGNORECASE), "8"),
    (re.compile(r"\bvii\b", re.IGNORECASE), "7"),
    (re.compile(r"\bvi\b", re.IGNORECASE), "6"),
    (re.compile(r"\biii\b", re.IGNORECASE), "3"),
    (re.compile(r"\bii\b", re.IGNORECASE), "2"),
    (re.compile(r"\biv\b", re.IGNORECASE), "4"),
    (re.compile(r"\bv\b", re.IGNORECASE), "5"),
    (re.compile(r"\bix\b", re.IGNORECASE), "9"),
    (re.compile(r"\bx\b", re.IGNORECASE), "10"),
)

_LEADING_ARTICLES_RE = re.compile(r"^(?:o|a|os|as|um|uma|uns|umas|the)\s+", re.IGNORECASE)


def _roman_to_decimal(texto: str) -> str:
    res = texto
    for pat, digit in _ROMAN_PATTERNS:
        res = pat.sub(digit, res)
    return res


def chave_match(texto: str) -> str:
    """
    Normaliza título para chave O(1) de cruzamento e deduplicação
    (minúsculas, sem acentos, algarismos romanos convertidos, sem pontuação).
    """
    if not texto:
        return ""
    limpo, _ = normalizar_titulo(texto)
    base = limpo or texto
    sem_acentos = "".join(
        ch for ch in unicodedata.normalize("NFD", base.lower()) if unicodedata.category(ch) != "Mn"
    )
    sem_acentos = _roman_to_decimal(sem_acentos.replace("&", " e ").replace("ß", "ss"))
    return re.sub(r"[^a-z0-9]+", " ", sem_acentos).strip()


def chave_match_sem_artigo(texto: str) -> str:
    """
    Remove artigos iniciais ('o', 'a', 'os', 'as', 'um', 'uma', 'the')
    de uma chave normalizada para elevar taxa de match exato IPTV <-> TMDB.
    """
    base = chave_match(texto)
    if not base:
        return ""
    stripped = _LEADING_ARTICLES_RE.sub("", base).strip()
    return stripped or base


def similaridade_dice(a: str, b: str) -> float:
    """
    Calcula coeficiente de Sorensen-Dice por bigramas de caracteres.
    """
    s1 = re.sub(r"\s+", "", str(a or "").lower())
    s2 = re.sub(r"\s+", "", str(b or "").lower())
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    if len(s1) < 2 or len(s2) < 2:
        return 0.0

    bigrams1: Dict[str, int] = {}
    for i in range(len(s1) - 1):
        bg = s1[i : i + 2]
        bigrams1[bg] = bigrams1.get(bg, 0) + 1

    intersection = 0
    for i in range(len(s2) - 1):
        bg = s2[i : i + 2]
        cnt = bigrams1.get(bg, 0)
        if cnt > 0:
            intersection += 1
            bigrams1[bg] = cnt - 1

    return (2.0 * intersection) / ((len(s1) - 1) + (len(s2) - 1))


def titulos_equivalentes(local_key: str, tmdb_key: str) -> bool:
    """
    Valida equivalência aproximada com trava estrita de números (evita casar
    sequências como 'Resgate 1' com 'Resgate 2').
    """
    k1 = str(local_key or "").strip()
    k2 = str(tmdb_key or "").strip()
    if not k1 or not k2:
        return False
    if k1 == k2:
        return True

    nums1 = re.findall(r"\d+", k1)
    nums2 = re.findall(r"\d+", k2)
    if (nums1 or nums2) and "".join(nums1) != "".join(nums2):
        return False

    if similaridade_dice(k1, k2) >= 0.85:
        return True

    if k1 in k2 or k2 in k1:
        ratio = min(len(k1), len(k2)) / max(len(k1), len(k2))
        if ratio >= 0.80:
            return True

    return False


def extrair_qualidade_audio(raw_name: str) -> Dict[str, object]:
    """
    Extrai qualidade de vídeo (4K/FHD/HD) e idioma (DUBLADO/LEGENDADO) de um nome IPTV.
    """
    txt = str(raw_name or "")
    is_4k = bool(re.search(r"\b(4k|uhd|2160p)\b", txt, re.I))
    is_fhd = bool(re.search(r"\b(fhd|1080p)\b", txt, re.I))
    is_cam = bool(re.search(r"\b(cam|ts|hdcam)\b", txt, re.I))
    is_leg = bool(re.search(r"\b(legendado|leg|sub)\b|\[l\]|\(l\)", txt, re.I))
    is_dub = bool(re.search(r"\b(dublado|dub|nacional|dual\s*audio)\b", txt, re.I))

    if is_4k:
        quality = "4K"
        quality_rank = 3
    elif is_cam:
        quality = "CAM"
        quality_rank = 0
    elif is_fhd:
        quality = "FHD"
        quality_rank = 2
    else:
        quality = "HD"
        quality_rank = 1

    audio = "LEGENDADO" if (is_leg and not is_dub) else ("DUBLADO" if is_dub else "")
    return {
        "quality": quality,
        "quality_rank": quality_rank,
        "is_legendado": is_leg and not is_dub,
        "audio": audio,
    }


def detectar_provedores_heuristica(nome: str, categoria: str = "") -> Set[str]:
    """
    Identifica fornecedores de streaming usando heurística regex sobre
    a categoria e o nome vindos do IPTV, aplicando rejeição negativa
    para evitar falsos positivos (ex.: 'Kurt Warner' não é HBO Max).
    """
    matched: Set[str] = set()
    cat_txt = str(categoria or "")
    name_txt = str(nome or "")

    for prov_slug, regex in REGEX_CATEGORIA_FALLBACK.items():
        reject = REGEX_CATEGORIA_REJEICAO.get(prov_slug)

        # 1. Categoria tem prioridade (se não bater rejeição na própria categoria)
        if cat_txt and regex.search(cat_txt):
            if not reject or not reject.search(cat_txt):
                matched.add(prov_slug)
                continue

        # 2. Fallback pelo nome do título (exigindo passar na rejeição negativa)
        if name_txt and regex.search(name_txt):
            if not reject or not reject.search(name_txt):
                matched.add(prov_slug)

    return matched


def calcular_rating_5based(rating: Optional[object]) -> float:
    """
    Converte nota de escala 0-10 para escala 0-5 com 1 casa decimal.
    Ex: 8.4 -> 4.2
    """
    if rating is None:
        return 0.0
    try:
        val = float(str(rating).strip().replace(",", "."))
        return round(val / 2.0, 1)
    except (ValueError, TypeError):
        return 0.0
