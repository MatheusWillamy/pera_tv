"""
Módulo de Normalização de Strings, Extração de Metadados e Heurística de Provedores.
"""
from typing import Optional, Set, Tuple
import re
from config import REGEX_RUIDOS, REGEX_CATEGORIA_FALLBACK


def normalizar_titulo(raw_name: str) -> Tuple[str, Optional[int]]:
    """
    Remove ruídos comuns de IPTV (qualidade, áudio, dublagem, tags)
    e extrai o ano de lançamento de 4 dígitos.
    
    Exemplo:
        'Auto da Compadecida 2 (2024) [4K DUBLADO]' -> ('Auto da Compadecida 2', 2024)
    """
    if not raw_name:
        return "", None

    # 1. Extração do ano de 4 dígitos (1900-2099)
    ano_match = re.search(r"\b(19\d\d|20\d\d)\b", raw_name)
    ano = int(ano_match.group(1)) if ano_match else None

    # 2. Remoção de ruídos de tags e resoluções
    limpo = REGEX_RUIDOS.sub(" ", raw_name)

    # 3. Remoção do ano se tiver ficado solto entre parênteses ou delimitadores
    if ano:
        limpo = re.sub(rf"\b{ano}\b", " ", limpo)

    # 4. Substituição de pontuações de separação por espaços
    limpo = re.sub(r"[\-–—:_|/\\\[\]()]", " ", limpo)

    # 5. Normalização de múltiplos espaços em branco
    limpo = re.sub(r"\s+", " ", limpo).strip()

    return limpo, ano


def detectar_provedores_heuristica(nome: str, categoria: str = "") -> Set[str]:
    """
    Identifica fornecedores de streaming usando heurística regex sobre
    o nome do stream e o nome da categoria vinda do IPTV.
    """
    matched: Set[str] = set()
    alvo = f"{categoria} {nome}"

    for prov_slug, regex in REGEX_CATEGORIA_FALLBACK.items():
        if regex.search(alvo):
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
