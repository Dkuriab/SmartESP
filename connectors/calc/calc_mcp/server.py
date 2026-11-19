"""MCP-сервер calc: точный счёт и кухонные единицы (stdio)."""

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from calc_mcp.expr import CalcError, calculate
from calc_mcp.units import UnitError, convert, split


def build_server() -> MCPServer:
    """Собирает сервер с тремя инструментами."""
    server = MCPServer("calc")

    @server.tool(
        name="calculate",
        description=(
            "Точно считает выражение: + - * / ** % и скобки, функции sqrt, round, abs, min, max. "
            "Дробь пишите запятой или точкой (внутри скобок функций — только точкой). "
            "Пример: «15 / 100 * 800» даёт 120."
        ),
    )
    def calculate_tool(expression: str) -> str:
        try:
            return calculate(expression)
        except CalcError as error:
            raise ToolError(str(error)) from None

    @server.tool(
        name="convert",
        description=(
            "Переводит единицы: масса (мг, г, кг, фунт, унция), объём (мл, л, ч. л., ст. л., стакан "
            "250 мл), температура (°C, °F). Между массой и объёмом нужен продукт: мука, сахар, соль, "
            "рис, гречка, молоко, вода, масло растительное, масло сливочное, мёд, крупа манная. "
            "Пример: 1 стакан муки в граммах."
        ),
    )
    def convert_tool(value: float, from_unit: str, to_unit: str, product: str = "") -> str:
        try:
            return convert(value, from_unit, to_unit, product)
        except UnitError as error:
            raise ToolError(str(error)) from None

    @server.tool(
        name="split",
        description=(
            "Делит количество поровну: сколько на одну часть. Единица необязательна. "
            "Пример: 500 г на 10 порций — по 50 г."
        ),
    )
    def split_tool(total: float, parts: int, unit: str = "") -> str:
        try:
            return split(total, parts, unit)
        except UnitError as error:
            raise ToolError(str(error)) from None

    return server


def main() -> None:
    """Точка входа `calc-mcp`: запуск по stdio. Данных не хранит."""
    build_server().run("stdio")
