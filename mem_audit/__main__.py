"""Enable `python -m mem_audit ...` as a fallback for when the installed
`mem-audit` console script isn't on PATH (common on Windows, where pip drops
it in a Scripts dir that isn't always in PATH)."""
from mem_audit.cli import main

if __name__ == "__main__":
    main()
