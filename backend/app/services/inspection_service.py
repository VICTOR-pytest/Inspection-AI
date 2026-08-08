from dataclasses import dataclass

from app.models.product import Product


@dataclass(frozen=True)
class ValidationResult:
    barcode_ok: bool
    weight_ok: bool
    valid: bool
    product_name: str | None
    reason: str | None


def validate_product(product: Product | None, weight: float) -> ValidationResult:
    """
    Lógica central de validação da esteira de inspeção.

    Regras:
    - barcode_ok  → produto existe no BD e está ativo
    - weight_ok   → peso medido está dentro da faixa de tolerância
    - valid       → ambas as condições são verdadeiras

    Args:
        product: instância ORM se barcode foi encontrado, caso contrário None.
        weight:  peso medido na mesma unidade de Product.expected_weight.

    Returns:
        ValidationResult com todos os flags e motivo legível.
    """
    if product is None:
        return ValidationResult(
            barcode_ok=False,
            weight_ok=False,
            valid=False,
            product_name=None,
            reason="Barcode não encontrado no banco de dados.",
        )

    barcode_ok = True

    weight_min = product.expected_weight * (1 - product.tolerance)
    weight_max = product.expected_weight * (1 + product.tolerance)
    weight_ok = weight_min <= weight <= weight_max

    if weight_ok:
        reason = None
        valid = True
    else:
        direction = "abaixo" if weight < weight_min else "acima"
        reason = (
            f"Peso {weight:.3f} está {direction} do intervalo aceitável "
            f"[{weight_min:.3f} – {weight_max:.3f}] "
            f"para o produto '{product.name}'."
        )
        valid = False

    return ValidationResult(
        barcode_ok=barcode_ok,
        weight_ok=weight_ok,
        valid=valid,
        product_name=product.name,
        reason=reason,
    )
