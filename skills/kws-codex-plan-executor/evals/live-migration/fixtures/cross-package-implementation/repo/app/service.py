from packages.math_core import subtotal


def invoice_total(values: list[int], fee: int) -> int:
    return subtotal(values)
