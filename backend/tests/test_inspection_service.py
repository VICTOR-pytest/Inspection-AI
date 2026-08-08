"""
Testes unitários para a lógica de validação.
Rodam inteiramente em memória — sem banco de dados.
"""
from unittest.mock import MagicMock

from app.services.inspection_service import validate_product


def _make_product(expected_weight: float = 1.0, tolerance: float = 0.05) -> MagicMock:
    product = MagicMock()
    product.name = "Produto Teste A"
    product.expected_weight = expected_weight
    product.tolerance = tolerance
    return product


# ---------------------------------------------------------------------------
# barcode não encontrado
# ---------------------------------------------------------------------------

def test_barcode_not_found():
    result = validate_product(product=None, weight=1.0)
    assert result.barcode_ok is False
    assert result.weight_ok is False
    assert result.valid is False
    assert result.product_name is None
    assert result.reason is not None


# ---------------------------------------------------------------------------
# peso válido
# ---------------------------------------------------------------------------

def test_valid_weight_exact():
    result = validate_product(_make_product(), weight=1.0)
    assert result.barcode_ok is True
    assert result.weight_ok is True
    assert result.valid is True
    assert result.reason is None


def test_valid_weight_lower_boundary():
    result = validate_product(_make_product(1.0, 0.05), weight=0.950)
    assert result.weight_ok is True


def test_valid_weight_upper_boundary():
    result = validate_product(_make_product(1.0, 0.05), weight=1.050)
    assert result.weight_ok is True


# ---------------------------------------------------------------------------
# peso inválido
# ---------------------------------------------------------------------------

def test_weight_too_low():
    result = validate_product(_make_product(1.0, 0.05), weight=0.900)
    assert result.barcode_ok is True
    assert result.weight_ok is False
    assert result.valid is False
    assert "abaixo" in result.reason.lower()


def test_weight_too_high():
    result = validate_product(_make_product(1.0, 0.05), weight=1.200)
    assert result.barcode_ok is True
    assert result.weight_ok is False
    assert result.valid is False
    assert "acima" in result.reason.lower()


# ---------------------------------------------------------------------------
# cenário da especificação do Sprint 2
# ---------------------------------------------------------------------------

def test_conveyor_spec_scenario():
    """Cenário exato da spec: barcode 789123456, peso 1.02 → válido"""
    product = _make_product(expected_weight=1.0, tolerance=0.05)
    product.name = "Produto Teste A"
    result = validate_product(product, weight=1.02)
    assert result.valid is True
    assert result.product_name == "Produto Teste A"


def test_product_name_on_success():
    product = _make_product()
    assert validate_product(product, weight=1.0).product_name == product.name


def test_product_name_on_failure():
    product = _make_product()
    assert validate_product(product, weight=9.99).product_name == product.name
