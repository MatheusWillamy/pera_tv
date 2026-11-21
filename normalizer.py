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


def chave_match(texto: str) -> str:
    """
    Normaliza título para chave O(1) de cruzamento e deduplicação
    (minúsculas, sem acentos, sem pontuação).
    """
    if not texto:
        return ""
    limpo, _ = normalizar_titulo(texto)
    base = limpo or texto
    sem_acentos = "".join(
        ch for ch in unicodedata.normalize("NFD", base.lower()) if unicodedata.category(ch) != "Mn"
    )
    sem_acentos = sem_acentos.replace("&", " e ").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", sem_acentos).strip()


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
