"""Container/runtime validation for demo and production roles."""

from services.runtime_configuration import validate_runtime_configuration
from services.runtime_secrets import materialize_runtime_secrets


def main() -> None:
    materialize_runtime_secrets()
    validate_runtime_configuration()


if __name__ == "__main__":
    main()
