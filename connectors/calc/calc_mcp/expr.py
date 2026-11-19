"""Безопасное вычисление арифметических выражений (без eval)."""

import ast
import math
import operator
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from typing import Any

MAX_LENGTH = 200
MAX_EXPONENT = 100
MAX_DIGITS = 300
MAX_BITS = 1000
DECIMALS = 4


class CalcError(ValueError):
    """Понятная ошибка вычисления; текст пригоден для озвучки."""


def _to_fraction(value: Any) -> Fraction:
    """Точное значение: float берётся по его короткой десятичной записи (0.1 -> 1/10)."""
    if isinstance(value, float):
        return Fraction(repr(value))
    return Fraction(value)


def format_number(value: float | int | Fraction) -> str:
    """Число по-русски: до 4 знаков после запятой (школьное округление), без хвостовых нулей.

    Целые и дроби выводятся точно, без перехода через float.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise CalcError("Не понял число.")
    exact = _to_fraction(value)
    if exact.denominator == 1:
        return str(exact.numerator)
    with localcontext() as context:
        context.prec = 800
        number = Decimal(exact.numerator) / Decimal(exact.denominator)
        text = format(number.quantize(Decimal(1).scaleb(-DECIMALS), rounding=ROUND_HALF_UP), "f")
    text = text.rstrip("0").rstrip(".")
    if text in ("", "-0"):
        return "0"
    return text.replace(".", ",")


def _normalize(expression: str) -> str:
    """Заменяет русские знаки и десятичную запятую (вне скобок функций)."""
    text = expression.replace("×", "*").replace("÷", "/").replace("^", "**")
    result: list[str] = []
    stack: list[bool] = []  # True — скобка вызова функции
    for index, char in enumerate(text):
        if char == "(":
            before = text[:index].rstrip()
            stack.append(bool(before) and (before[-1].isalnum() or before[-1] == "_"))
        elif char == ")" and stack:
            stack.pop()
        elif char == "," and not (stack and stack[-1]):
            prev_digit = index > 0 and text[index - 1].isdigit()
            next_digit = index + 1 < len(text) and text[index + 1].isdigit()
            if prev_digit and next_digit:
                char = "."
        result.append(char)
    return "".join(result)


def _simplify(value: Any) -> Any:
    """Дробь со знаменателем 1 становится целым."""
    if isinstance(value, Fraction) and value.denominator == 1:
        return value.numerator
    return value


def _check_size(value: Any) -> Any:
    """Отсекает слишком большие и нечисловые результаты."""
    if isinstance(value, bool) or not isinstance(value, int | float | Fraction):
        raise CalcError("Не понял выражение.")
    value = _simplify(value)
    if isinstance(value, int):
        too_big = value.bit_length() > MAX_BITS
    elif isinstance(value, Fraction):
        too_big = max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS
    else:
        too_big = not math.isfinite(value)
    if too_big:
        raise CalcError("Слишком большое число.")
    return value


def _is_exact(value: Any) -> bool:
    return not isinstance(value, float)


def _power(base: Any, exponent: Any) -> Any:
    """Степень с защитой от гигантских результатов; целая степень точная."""
    if abs(exponent) > MAX_EXPONENT:
        raise CalcError("Слишком большая степень.")
    if base not in (0, 1, -1) and exponent * math.log10(abs(float(base))) > MAX_DIGITS:
        raise CalcError("Слишком большое число.")
    try:
        if _is_exact(base) and _is_exact(exponent) and Fraction(exponent).denominator == 1:
            return Fraction(base) ** int(exponent)
        result = float(base) ** float(exponent)
    except ZeroDivisionError:
        raise CalcError("На ноль делить нельзя.") from None
    except OverflowError:
        raise CalcError("Слишком большое число.") from None
    if isinstance(result, complex):
        raise CalcError("Не понял выражение: корень из отрицательного числа.")
    return result


def _divide(left: Any, right: Any, op: Callable[[Any, Any], Any]) -> Any:
    if right == 0:
        raise CalcError("На ноль делить нельзя.")
    if _is_exact(left) and _is_exact(right):
        return op(Fraction(left), Fraction(right))
    return op(float(left), float(right))


BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda a, b: _divide(a, b, operator.truediv),
    ast.Mod: lambda a, b: _divide(a, b, operator.mod),
    ast.Pow: _power,
}


def _sqrt(x: Any) -> Any:
    if x < 0:
        raise CalcError("Корень из отрицательного числа не извлечь.")
    if isinstance(x, int):
        root = math.isqrt(x)
        if root * root == x:
            return root
    return math.sqrt(x)


def _round(x: Any, digits: Any = 0) -> Any:
    """Школьное округление: половина — от нуля (2,5 даёт 3)."""
    if isinstance(digits, float) or Fraction(digits).denominator != 1 or not 0 <= digits <= 10:
        raise CalcError("Неверный аргумент у round: знаков должно быть целое от 0 до 10.")
    if isinstance(x, float):
        x = Fraction(repr(x))
    scale = 10 ** int(digits)
    scaled = abs(Fraction(x)) * scale
    rounded = int(scaled + Fraction(1, 2))  # int() отбрасывает дробную часть
    return Fraction(rounded if x >= 0 else -rounded, scale)


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sqrt": _sqrt,
    "round": _round,
    "abs": abs,
    "min": min,
    "max": max,
}


def _call(node: ast.Call) -> Any:
    if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
        raise CalcError("Не понял выражение: такой функции нет.")
    args = [_eval(arg) for arg in node.args]
    try:
        return FUNCTIONS[node.func.id](*args)
    except TypeError:
        raise CalcError(
            f"Неверное число аргументов у {node.func.id}. Дробь внутри скобок пишите точкой, не запятой."
        ) from None


def _eval(node: ast.AST) -> Any:
    """Вычисляет узел дерева; допустимы только узлы из белого списка."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, float) and math.isfinite(value):
            value = Fraction(repr(value))
        return _check_size(value)
    if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
        return _check_size(BIN_OPS[type(node.op)](_eval(node.left), _eval(node.right)))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        value = _eval(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Call):
        return _check_size(_call(node))
    raise CalcError("Не понял выражение.")


def calculate(expression: str) -> str:
    """Считает выражение и возвращает ответ по-русски; ошибка — CalcError."""
    if len(expression) > MAX_LENGTH:
        raise CalcError("Выражение слишком длинное.")
    if not expression.strip():
        raise CalcError("Выражение пустое.")
    try:
        tree = ast.parse(_normalize(expression).strip(), mode="eval")
        value = _eval(tree.body)
    except CalcError:
        raise
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise CalcError("Не понял выражение.") from None
    except OverflowError:
        raise CalcError("Слишком большое число.") from None
    return format_number(value)
