"""Allow ``python -m frozen_test_v2 <command>``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
