"""Container entrypoint validation for demo and production roles."""

from services.runtime_configuration import validate_runtime_configuration


def main() -> None:
    validate_runtime_configuration()


if __name__ == "__main__":
    main()
