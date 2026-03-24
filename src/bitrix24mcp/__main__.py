"""Entry point – ``python -m bitrix24mcp`` or ``bitrix24mcp`` CLI."""
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
)


def main() -> None:
    from bitrix24mcp.server import run
    asyncio.run(run())


if __name__ == "__main__":
    main()
