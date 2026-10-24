"""
Testes unitários para o módulo normalizer.py.
"""
from normalizer import (
    calcular_rating_5based,
    detectar_provedores_heuristica,
    normalizar_titulo,
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
