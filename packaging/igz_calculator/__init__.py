"""
Plugin de Calculadora para IngeTrazo
"""
#
# Ponto de entrada da extensão: o IngeTrazo importa este pacote e procura uma
# função `setup(app)` de nível de módulo. Definimos `setup` aqui (uma fina
# camada sobre a implementação em `igz_calculator.py`) e reexportamos os
# demais símbolos públicos.
from .igz_calculator import (
    CalculatorDialog,
    CalculatorPanel,
    create_toolbar,
    run,
    register,
    init,
    load,
    on_load,
    setup as _setup,
)


def setup(app=None):
    """Chamado uma vez pelo IngeTrazo (Extensions API) ao construir a janela."""
    return _setup(app)


__all__ = [
    "CalculatorDialog",
    "CalculatorPanel",
    "create_toolbar",
    "run",
    "setup",
    "register",
    "init",
    "load",
    "on_load",
]