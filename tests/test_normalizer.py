"""
Testes unitários para o módulo normalizer.py.
"""
from normalizer import (
    calcular_rating_5based,
    chave_match,
    chave_match_sem_artigo,
    chaves_match_alternativas,
    detectar_provedores_heuristica,
    extrair_qualidade_audio,
    normalizar_titulo,
    titulos_equivalentes,
)


def test_normalizar_titulo_com_ano_e_ruido():
    titulo_raw = "Auto da Compadecida 2 (2024) [4K DUBLADO 1080p FHD]"
    limpo, ano = normalizar_titulo(titulo_raw)
    assert ano == 2024
    assert "4K" not in limpo
    assert "DUBLADO" not in limpo
    assert "Auto da Compadecida 2" in limpo


def test_normalizar_titulo_sem_ano():
    titulo_raw = "Matrix Reloaded [Dublado / Dual Audio] HEVC x264"
    limpo, ano = normalizar_titulo(titulo_raw)
    assert ano is None
    assert "Matrix Reloaded" in limpo
    assert "HEVC" not in limpo
    assert "Dublado" not in limpo


def test_normalizar_titulo_vazio():
    limpo, ano = normalizar_titulo("")
    assert limpo == ""
    assert ano is None


def test_detectar_provedores_heuristica_globoplay():
    providers = detectar_provedores_heuristica("Novela Renascer", "Novelas Globoplay")
    assert "globoplay" in providers


def test_detectar_provedores_heuristica_multiplos():
    providers_netflix = detectar_provedores_heuristica("Stranger Things", "Séries Netflix")
    assert "netflix" in providers_netflix

    providers_hbo = detectar_provedores_heuristica("House of the Dragon", "HBO Max")
    assert "hbo" in providers_hbo

    providers_disney = detectar_provedores_heuristica("Loki", "Disney+ Originais")
    assert "disney" in providers_disney

    providers_prime = detectar_provedores_heuristica("The Boys", "Prime Video")
    assert "prime" in providers_prime

    providers_apple = detectar_provedores_heuristica("Ted Lasso", "Apple TV+")
    assert "apple" in providers_apple

    providers_telecine = detectar_provedores_heuristica("Filme Ação", "Telecine Pipoca")
    assert "telecine" in providers_telecine

    providers_paramount = detectar_provedores_heuristica("Yellowstone", "Paramount+")
    assert "paramount" in providers_paramount

    providers_mubi = detectar_provedores_heuristica("Filme Indie", "Mubi Clássicos")
    assert "mubi" in providers_mubi


def test_calcular_rating_5based():
    assert calcular_rating_5based("8.4") == 4.2
    assert calcular_rating_5based(10.0) == 5.0
    assert calcular_rating_5based("7.5") == 3.8
    assert calcular_rating_5based(None) == 0.0
    assert calcular_rating_5based("invalido") == 0.0


def test_anti_falso_positivo_hbo_kurt_warner():
    providers = detectar_provedores_heuristica(
        "American Underdog: A História de Kurt Warner (2021) [FHD]",
        "FILMES | DRAMA",
    )
    assert "hbo" not in providers


def test_anti_falso_positivo_mad_max_e_optimus_prime():
    assert "hbo" not in detectar_provedores_heuristica("Mad Max: Estrada da Fúria (2015)", "FILMES | AÇÃO")
    assert "prime" not in detectar_provedores_heuristica("Optimus Prime: A Origem", "FILMES | AÇÃO")
    assert "disney" not in detectar_provedores_heuristica("Battle Star Wars (2020) [HD]", "FILMES | FICÇÃO")


def test_chave_match_romanos_artigos_e_fuzzy_trava_numerica():
    assert chave_match("Velozes e Furiosos X (2023)") == chave_match("Velozes e Furiosos 10")
    assert chave_match_sem_artigo("Os Vingadores") == chave_match_sem_artigo("Vingadores")
    assert titulos_equivalentes(chave_match("Vingadores Ultimato"), chave_match("Vingadores: Ultimato"))
    # Trava numérica impede casar Resgate 1 com Resgate 2
    assert not titulos_equivalentes(chave_match("Resgate 1"), chave_match("Resgate 2"))


def test_extrair_qualidade_audio_legendado_e_dublado():
    leg = extrair_qualidade_audio("Vingadores (2019) [FHD] [LEG]")
    assert leg["quality"] == "FHD"
    assert leg["is_legendado"] is True
    assert leg["audio"] == "LEGENDADO"

    leg_short = extrair_qualidade_audio("Interestelar (2014) [L]")
    assert leg_short["is_legendado"] is True

    dub = extrair_qualidade_audio("Duna (2021) [4K DUBLADO]")
    assert dub["quality"] == "4K"
    assert dub["is_legendado"] is False
    assert dub["audio"] == "DUBLADO"


def test_prefixos_regionais_e_variantes_e_comercial():
    limpo, ano = normalizar_titulo("PT | [4K] BR - Interestelar (2014)")
    assert limpo == "Interestelar"
    assert ano == 2014
    alts = chaves_match_alternativas("Velozes & Furiosos")
    assert chave_match("Velozes e Furiosos") in alts
    assert chave_match("Velozes and Furiosos") in alts
