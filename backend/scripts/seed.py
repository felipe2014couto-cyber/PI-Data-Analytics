"""Idempotent seed for PI Analytics Data."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Tuple

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.logging import configure_logging, logger  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag
from app.models.section import Section
from app.models.variable_type import VariableType
from app.models.cep_variable import CepVariable

PI_SERVER = "PIMS"

EQUIPMENTS: List[dict] = [
    {
        "code": "RB3",
        "name": "Equipamento RB3",
        "description": "Equipamento de referencia cadastrado pelo seed.",
        "active": True,
    },
    {
        "code": "RB1",
        "name": "Equipamento RB1",
        "description": "Linha de lamina fria RB1.",
        "active": True,
    },
]

RB3_SECTIONS: List[dict] = [
    {"code": "ENTRADA", "name": "Entrada"},
    {"code": "FORNO", "name": "Forno"},
    {"code": "PROCESSO", "name": "Processo"},
    {"code": "SAIDA", "name": "Saida"},
]

RB1_SECTIONS: List[dict] = [
    {"code": "DECAPAGEM_ELETROLITICA", "name": "Decapagem Eletrolitica"},
    {"code": "DECAPAGEM_QUIMICA", "name": "Decapagem Quimica"},
    {"code": "FORNO", "name": "Forno"},
]

VARIABLE_TYPES: List[dict] = [
    {
        "code": "TEMPERATURE",
        "name": "Temperatura",
        "description": "Medicao de temperatura.",
        "default_unit": "C",
    },
    {
        "code": "SPEED",
        "name": "Velocidade",
        "description": "Velocidade linear de processo.",
        "default_unit": "m/min",
    },
    {
        "code": "PRESSURE",
        "name": "Pressao",
        "description": "Pressao de processo.",
        "default_unit": "bar",
    },
    {
        "code": "FLOW",
        "name": "Vazao",
        "description": "Vazao de fluido ou gas.",
        "default_unit": None,
    },
    {
        "code": "CURRENT",
        "name": "Corrente",
        "description": "Corrente eletrica.",
        "default_unit": "A",
    },
    {
        "code": "TORQUE",
        "name": "Torque",
        "description": "Torque mecanico.",
        "default_unit": "%",
    },
    {
        "code": "IRON_CONTENT",
        "name": "Teor de Ferro",
        "description": "Teor de ferro no processo.",
        "default_unit": None,
    },
    {
        "code": "OXYGEN",
        "name": "Oxigenio",
        "description": "Percentual de oxigenio.",
        "default_unit": "%",
    },
]

# ---------------------------------------------------------------------------
# RB1 PI Tag manifest — 73 tags (24 leitura + 24 lim.inf + 24 lim.sup + 1 alvo)
# Extracao direta do RB1.xml (PI AF export)
# ---------------------------------------------------------------------------

_RB1_TAGS: List[dict] = [
    # ======================================================================
    # Decapagem Eletrolitica — 11 variaveis (33 tags de leitura/limites)
    # ======================================================================
    # Escova 01 — Corrente
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_COR_ESC1",
     "display": "Escova 01", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA01_LIM_INF",
     "display": "Escova 01 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA01_LIM_SUP",
     "display": "Escova 01 - Limite Superior", "role": "Limite superior"},
    # Escova 02 — Corrente
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_COR_ESC2",
     "display": "Escova 02", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA02_LIM_INF",
     "display": "Escova 02 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA02_LIM_SUP",
     "display": "Escova 02 - Limite Superior", "role": "Limite superior"},
    # Escova 03 — Corrente
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_COR_ESC3",
     "display": "Escova 03", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA03_LIM_INF",
     "display": "Escova 03 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA03_LIM_SUP",
     "display": "Escova 03 - Limite Superior", "role": "Limite superior"},
    # Escova 04 — Corrente
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_COR_ESC4",
     "display": "Escova 04", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA04_LIM_INF",
     "display": "Escova 04 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA04_LIM_SUP",
     "display": "Escova 04 - Limite Superior", "role": "Limite superior"},
    # Retificador 01 — Corrente
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_COR_RETF1",
     "display": "Retificador 01", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET01_LIM_INF",
     "display": "Retificador 01 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET01_LIM_SUP",
     "display": "Retificador 01 - Limite Superior", "role": "Limite superior"},
    # Retificador 02 — Corrente
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_COR_RETF2",
     "display": "Retificador 02", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET02_LIM_INF",
     "display": "Retificador 02 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET02_LIM_SUP",
     "display": "Retificador 02 - Limite Superior", "role": "Limite superior"},
    # Retificador 03 — Corrente
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_COR_RETF3",
     "display": "Retificador 03", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET03_LIM_INF",
     "display": "Retificador 03 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET03_LIM_SUP",
     "display": "Retificador 03 - Limite Superior", "role": "Limite superior"},
    # Retificador 04 — Corrente
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_COR_RETF4",
     "display": "Retificador 04", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET04_LIM_INF",
     "display": "Retificador 04 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET04_LIM_SUP",
     "display": "Retificador 04 - Limite Superior", "role": "Limite superior"},
    # Tanque 01 — Temperatura
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TPR_TANQ1",
     "display": "Tanque 01", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEMP_TANQUE01_LIM_INF",
     "display": "Tanque 01 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEMP_TANQUE01_LIM_SUP",
     "display": "Tanque 01 - Limite Superior", "role": "Limite superior"},
    # Tanque 02 — Temperatura
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TPR_TANQ2",
     "display": "Tanque 02", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEMP_TANQUE02_LIM_INF",
     "display": "Tanque 02 - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEMP_TANQUE02_LIM_SUP",
     "display": "Tanque 02 - Limite Superior", "role": "Limite superior"},
    # Teor Fe — Teor de Ferro
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "IRON_CONTENT", "tag": "LFI_RB1_DE_TF_REAL",
     "display": "Teor Fe", "role": "Leitura"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "IRON_CONTENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEOR_FERRO_LIM_INF",
     "display": "Teor Fe - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "IRON_CONTENT", "tag": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEOR_FERRO_LIM_SUP",
     "display": "Teor Fe - Limite Superior", "role": "Limite superior"},
    # ======================================================================
    # Decapagem Quimica — 1 variavel (3 tags)
    # ======================================================================
    # Temperatura — Temperatura
    {"section": "DECAPAGEM_QUIMICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TPR_BAN",
     "display": "Temperatura", "role": "Leitura"},
    {"section": "DECAPAGEM_QUIMICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_DECAPAGEM_QUIMICA_TEMP_LIM_INF",
     "display": "Temperatura - Limite Inferior", "role": "Limite inferior"},
    {"section": "DECAPAGEM_QUIMICA", "vtype": "TEMPERATURE", "tag": "LFI_RB1_DECAPAGEM_QUIMICA_TEMP_LIM_SUP",
     "display": "Temperatura - Limite Superior", "role": "Limite superior"},
    # ======================================================================
    # Forno — 12 variaveis (37 tags: 36 + 1 alvo)
    # ======================================================================
    # Oxigenio — Oxigenio
    {"section": "FORNO", "vtype": "OXYGEN", "tag": "LFI_RB1_PERC_OXIG_REAL",
     "display": "Oxigenio", "role": "Leitura"},
    {"section": "FORNO", "vtype": "OXYGEN", "tag": "LFI_RB1_FRN_OXIGENIO_LIM_INF",
     "display": "Oxigenio - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "OXYGEN", "tag": "LFI_RB1_FRN_OXIGENIO_LIM_SUP",
     "display": "Oxigenio - Limite Superior", "role": "Limite superior"},
    # PCI — PCI
    {"section": "FORNO", "vtype": "PRESSURE", "tag": "LFI_RB1_PCI_MISTURA_REAL",
     "display": "PCI", "role": "Leitura"},
    {"section": "FORNO", "vtype": "PRESSURE", "tag": "LFI_RB1_FRN_PCI_LIM_INF",
     "display": "PCI - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "PRESSURE", "tag": "LFI_RB1_FRN_PCI_LIM_SUP",
     "display": "PCI - Limite Superior", "role": "Limite superior"},
    # Pirometro 01 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TEMP_PRMT1",
     "display": "Pirometro 01", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_TIRAP1_LIM_INF",
     "display": "Pirometro 01 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_TIRAP1_LIM_SUP",
     "display": "Pirometro 01 - Limite Superior", "role": "Limite superior"},
    # Velocidade — Velocidade (inclui tag de alvo)
    {"section": "FORNO", "vtype": "SPEED", "tag": "LFI_RB1_VEL_PROC_PV",
     "display": "Velocidade", "role": "Leitura"},
    {"section": "FORNO", "vtype": "SPEED", "tag": "LFI_RB1_FRN_VELOCIDADE_LIM_INF",
     "display": "Velocidade - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "SPEED", "tag": "LFI_RB1_FRN_VELOCIDADE_LIM_SUP",
     "display": "Velocidade - Limite Superior", "role": "Limite superior"},
    {"section": "FORNO", "vtype": "SPEED", "tag": "LFI_RB1_FRN_VELOCIDADE_LIM_OBJ",
     "display": "Velocidade - Valor Objetivo", "role": "Valor objetivo"},
    # Zona 01 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TIC1_PV",
     "display": "Zona 01", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA1_LIM_INF",
     "display": "Zona 01 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA1_LIM_SUP",
     "display": "Zona 01 - Limite Superior", "role": "Limite superior"},
    # Zona 02 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TIC2_PV",
     "display": "Zona 02", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA2_LIM_INF",
     "display": "Zona 02 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA2_LIM_SUP",
     "display": "Zona 02 - Limite Superior", "role": "Limite superior"},
    # Zona 03 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TIC3_PV",
     "display": "Zona 03", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA3_LIM_INF",
     "display": "Zona 03 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA3_LIM_SUP",
     "display": "Zona 03 - Limite Superior", "role": "Limite superior"},
    # Zona 04 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TIC4_PV",
     "display": "Zona 04", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA4_LIM_INF",
     "display": "Zona 04 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA4_LIM_SUP",
     "display": "Zona 04 - Limite Superior", "role": "Limite superior"},
    # Zona 05 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TIC5_PV",
     "display": "Zona 05", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA5_LIM_INF",
     "display": "Zona 05 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA5_LIM_SUP",
     "display": "Zona 05 - Limite Superior", "role": "Limite superior"},
    # Zona 06 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TIC6_PV",
     "display": "Zona 06", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA6_LIM_INF",
     "display": "Zona 06 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA6_LIM_SUP",
     "display": "Zona 06 - Limite Superior", "role": "Limite superior"},
    # Zona 07 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TIC7_PV",
     "display": "Zona 07", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA7_LIM_INF",
     "display": "Zona 07 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA7_LIM_SUP",
     "display": "Zona 07 - Limite Superior", "role": "Limite superior"},
    # Zona 08 — Temperatura
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_TIC8_PV",
     "display": "Zona 08", "role": "Leitura"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA8_LIM_INF",
     "display": "Zona 08 - Limite Inferior", "role": "Limite inferior"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "tag": "LFI_RB1_FRN_TEMP_ZONA8_LIM_SUP",
     "display": "Zona 08 - Limite Superior", "role": "Limite superior"},
]

assert len(_RB1_TAGS) == 73, f"Manifesto RB1 deve ter 73 tags, encontrado {len(_RB1_TAGS)}"

# ---------------------------------------------------------------------------
# CEP Variables — 24 monitored variables (11 + 1 + 12)
# Each maps a reading tag + lower limit + upper limit + optional target
# ---------------------------------------------------------------------------

_CEP_VARIABLES: List[dict] = [
    # Decapagem Eletrolitica — 11 variables
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "code": "ESC_01", "name": "Escova 01",
     "reading": "LFI_RB1_COR_ESC1", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA01_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA01_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "code": "ESC_02", "name": "Escova 02",
     "reading": "LFI_RB1_COR_ESC2", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA02_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA02_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "code": "ESC_03", "name": "Escova 03",
     "reading": "LFI_RB1_COR_ESC3", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA03_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA03_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "code": "ESC_04", "name": "Escova 04",
     "reading": "LFI_RB1_COR_ESC4", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA04_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_ESCOVA04_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "code": "RET_01", "name": "Retificador 01",
     "reading": "LFI_RB1_COR_RETF1", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET01_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET01_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "code": "RET_02", "name": "Retificador 02",
     "reading": "LFI_RB1_COR_RETF2", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET02_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET02_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "code": "RET_03", "name": "Retificador 03",
     "reading": "LFI_RB1_COR_RETF3", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET03_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET03_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "CURRENT", "code": "RET_04", "name": "Retificador 04",
     "reading": "LFI_RB1_COR_RETF4", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET04_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_COR_RET04_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "TEMPERATURE", "code": "TAN_01", "name": "Tanque 01",
     "reading": "LFI_RB1_TPR_TANQ1", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEMP_TANQUE01_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEMP_TANQUE01_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "TEMPERATURE", "code": "TAN_02", "name": "Tanque 02",
     "reading": "LFI_RB1_TPR_TANQ2", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEMP_TANQUE02_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEMP_TANQUE02_LIM_SUP"},
    {"section": "DECAPAGEM_ELETROLITICA", "vtype": "IRON_CONTENT", "code": "TEOR_FE", "name": "Teor Fe",
     "reading": "LFI_RB1_DE_TF_REAL", "lower": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEOR_FERRO_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_ELETROLITICA_TEOR_FERRO_LIM_SUP"},
    # Decapagem Quimica — 1 variable
    {"section": "DECAPAGEM_QUIMICA", "vtype": "TEMPERATURE", "code": "TEMP_DQ", "name": "Temperatura",
     "reading": "LFI_RB1_TPR_BAN", "lower": "LFI_RB1_DECAPAGEM_QUIMICA_TEMP_LIM_INF",
     "upper": "LFI_RB1_DECAPAGEM_QUIMICA_TEMP_LIM_SUP"},
    # Forno — 12 variables
    {"section": "FORNO", "vtype": "OXYGEN", "code": "OXIG", "name": "Oxigenio",
     "reading": "LFI_RB1_PERC_OXIG_REAL", "lower": "LFI_RB1_FRN_OXIGENIO_LIM_INF",
     "upper": "LFI_RB1_FRN_OXIGENIO_LIM_SUP"},
    {"section": "FORNO", "vtype": "PRESSURE", "code": "PCI", "name": "PCI",
     "reading": "LFI_RB1_PCI_MISTURA_REAL", "lower": "LFI_RB1_FRN_PCI_LIM_INF",
     "upper": "LFI_RB1_FRN_PCI_LIM_SUP"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "PIR_01", "name": "Pirometro 01",
     "reading": "LFI_RB1_TEMP_PRMT1", "lower": "LFI_RB1_FRN_TEMP_TIRAP1_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_TIRAP1_LIM_SUP"},
    {"section": "FORNO", "vtype": "SPEED", "code": "VEL", "name": "Velocidade",
     "reading": "LFI_RB1_VEL_PROC_PV", "lower": "LFI_RB1_FRN_VELOCIDADE_LIM_INF",
     "upper": "LFI_RB1_FRN_VELOCIDADE_LIM_SUP",
     "target": "LFI_RB1_FRN_VELOCIDADE_LIM_OBJ"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "ZN_01", "name": "Zona 01",
     "reading": "LFI_RB1_TIC1_PV", "lower": "LFI_RB1_FRN_TEMP_ZONA1_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_ZONA1_LIM_SUP"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "ZN_02", "name": "Zona 02",
     "reading": "LFI_RB1_TIC2_PV", "lower": "LFI_RB1_FRN_TEMP_ZONA2_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_ZONA2_LIM_SUP"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "ZN_03", "name": "Zona 03",
     "reading": "LFI_RB1_TIC3_PV", "lower": "LFI_RB1_FRN_TEMP_ZONA3_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_ZONA3_LIM_SUP"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "ZN_04", "name": "Zona 04",
     "reading": "LFI_RB1_TIC4_PV", "lower": "LFI_RB1_FRN_TEMP_ZONA4_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_ZONA4_LIM_SUP"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "ZN_05", "name": "Zona 05",
     "reading": "LFI_RB1_TIC5_PV", "lower": "LFI_RB1_FRN_TEMP_ZONA5_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_ZONA5_LIM_SUP"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "ZN_06", "name": "Zona 06",
     "reading": "LFI_RB1_TIC6_PV", "lower": "LFI_RB1_FRN_TEMP_ZONA6_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_ZONA6_LIM_SUP"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "ZN_07", "name": "Zona 07",
     "reading": "LFI_RB1_TIC7_PV", "lower": "LFI_RB1_FRN_TEMP_ZONA7_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_ZONA7_LIM_SUP"},
    {"section": "FORNO", "vtype": "TEMPERATURE", "code": "ZN_08", "name": "Zona 08",
     "reading": "LFI_RB1_TIC8_PV", "lower": "LFI_RB1_FRN_TEMP_ZONA8_LIM_INF",
     "upper": "LFI_RB1_FRN_TEMP_ZONA8_LIM_SUP"},
]

assert len(_CEP_VARIABLES) == 24, f"Manifesto CEP deve ter 24 variaveis, encontrado {len(_CEP_VARIABLES)}"


def upsert_equipments(db: Session) -> Tuple[int, int]:
    created = 0
    updated = 0
    for data in EQUIPMENTS:
        existing = db.query(Equipment).filter(Equipment.code == data["code"]).one_or_none()
        if existing is None:
            db.add(Equipment(**data))
            created += 1
        else:
            existing.name = data["name"]
            existing.description = data["description"]
            existing.active = data["active"]
            updated += 1
    db.flush()
    return created, updated


def upsert_sections(db: Session) -> Tuple[int, int]:
    created = 0
    updated = 0
    for equip_code, sections in [("RB3", RB3_SECTIONS), ("RB1", RB1_SECTIONS)]:
        equipment = db.query(Equipment).filter(Equipment.code == equip_code).one()
        for data in sections:
            existing = (
                db.query(Section)
                .filter(Section.equipment_id == equipment.id, Section.code == data["code"])
                .one_or_none()
            )
            if existing is None:
                db.add(Section(equipment_id=equipment.id, active=True, **data))
                created += 1
            else:
                existing.name = data["name"]
                updated += 1
    db.flush()
    return created, updated


def upsert_variable_types(db: Session) -> Tuple[int, int]:
    created = 0
    updated = 0
    for data in VARIABLE_TYPES:
        existing = (
            db.query(VariableType)
            .filter(VariableType.code == data["code"])
            .one_or_none()
        )
        if existing is None:
            db.add(VariableType(active=True, **data))
            created += 1
        else:
            existing.name = data["name"]
            existing.description = data["description"]
            existing.default_unit = data["default_unit"]
            existing.active = True
            updated += 1
    db.flush()
    return created, updated


def upsert_pi_tags(db: Session) -> Tuple[int, int]:
    equipment = db.query(Equipment).filter(Equipment.code == "RB1").one()
    sections = {
        s.code: s.id
        for s in db.query(Section).filter(Section.equipment_id == equipment.id).all()
    }
    vtypes = {
        vt.code: vt.id
        for vt in db.query(VariableType).filter(VariableType.code.in_([
            "TEMPERATURE", "SPEED", "CURRENT", "IRON_CONTENT", "OXYGEN", "PRESSURE",
        ])).all()
    }
    created = 0
    updated = 0
    for tag_data in _RB1_TAGS:
        section_id = sections[tag_data["section"]]
        variable_type_id = vtypes[tag_data["vtype"]]
        pi_tag_name = tag_data["tag"]
        existing = (
            db.query(PiTag)
            .filter(PiTag.pi_server == PI_SERVER, PiTag.pi_tag_name == pi_tag_name)
            .one_or_none()
        )
        if existing is None:
            db.add(PiTag(
                equipment_id=equipment.id,
                section_id=section_id,
                variable_type_id=variable_type_id,
                pi_server=PI_SERVER,
                pi_tag_name=pi_tag_name,
                display_name=tag_data["display"],
                description=tag_data["role"],
                data_type="NUMERIC",
                validation_status="PENDING",
                active=True,
            ))
            created += 1
        else:
            existing.equipment_id = equipment.id
            existing.section_id = section_id
            existing.variable_type_id = variable_type_id
            existing.display_name = tag_data["display"]
            existing.description = tag_data["role"]
            updated += 1
    db.flush()
    return created, updated


def upsert_cep_variables(db: Session) -> Tuple[int, int]:
    """Seed 24 CEP variables linking PI tags by role."""
    equipment = db.query(Equipment).filter(Equipment.code == "RB1").one()
    sections = {
        s.code: s.id
        for s in db.query(Section).filter(Section.equipment_id == equipment.id).all()
    }
    vtypes = {
        vt.code: vt.id
        for vt in db.query(VariableType).filter(VariableType.code.in_([
            "TEMPERATURE", "SPEED", "CURRENT", "IRON_CONTENT", "OXYGEN", "PRESSURE",
        ])).all()
    }

    # Build a lookup of pi_tag_name -> PiTag for all RB1 tags
    all_tags = (
        db.query(PiTag)
        .filter(PiTag.equipment_id == equipment.id)
        .all()
    )
    tag_by_name = {t.pi_tag_name: t for t in all_tags}

    created = 0
    updated = 0
    for var_data in _CEP_VARIABLES:
        section_id = sections[var_data["section"]]
        variable_type_id = vtypes[var_data["vtype"]]

        reading_tag = tag_by_name.get(var_data["reading"])
        lower_tag = tag_by_name.get(var_data["lower"])
        upper_tag = tag_by_name.get(var_data["upper"])
        target_tag_name = var_data.get("target")
        target_tag = tag_by_name.get(target_tag_name) if target_tag_name else None

        if reading_tag is None:
            raise ValueError(f"Tag de leitura nao encontrada: {var_data['reading']}")
        if lower_tag is None:
            raise ValueError(f"Tag de limite inferior nao encontrada: {var_data['lower']}")
        if upper_tag is None:
            raise ValueError(f"Tag de limite superior nao encontrada: {var_data['upper']}")

        existing = (
            db.query(CepVariable)
            .filter(CepVariable.equipment_id == equipment.id, CepVariable.code == var_data["code"])
            .one_or_none()
        )
        if existing is None:
            db.add(CepVariable(
                equipment_id=equipment.id,
                section_id=section_id,
                variable_type_id=variable_type_id,
                reading_tag_id=reading_tag.id,
                lower_limit_tag_id=lower_tag.id,
                upper_limit_tag_id=upper_tag.id,
                target_tag_id=target_tag.id if target_tag else None,
                code=var_data["code"],
                name=var_data["name"],
                active=True,
            ))
            created += 1
        else:
            existing.section_id = section_id
            existing.variable_type_id = variable_type_id
            existing.reading_tag_id = reading_tag.id
            existing.lower_limit_tag_id = lower_tag.id
            existing.upper_limit_tag_id = upper_tag.id
            existing.target_tag_id = target_tag.id if target_tag else None
            existing.name = var_data["name"]
            existing.active = True
            updated += 1
    db.flush()
    return created, updated


def run_seed() -> dict:
    configure_logging()
    db = SessionLocal()
    try:
        equipment_stats = upsert_equipments(db)
        section_stats = upsert_sections(db)
        variable_type_stats = upsert_variable_types(db)
        pi_tag_stats = upsert_pi_tags(db)
        cep_var_stats = upsert_cep_variables(db)
        db.commit()
        result = {
            "equipments": {"created": equipment_stats[0], "updated": equipment_stats[1]},
            "sections": {"created": section_stats[0], "updated": section_stats[1]},
            "variable_types": {"created": variable_type_stats[0], "updated": variable_type_stats[1]},
            "pi_tags": {"created": pi_tag_stats[0], "updated": pi_tag_stats[1]},
            "cep_variables": {"created": cep_var_stats[0], "updated": cep_var_stats[1]},
        }
        logger.info("Seed finished: %s", result)
        return result
    except Exception:
        db.rollback()
        logger.exception("Seed failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    summary = run_seed()
    print(summary)
