import sys, pathlib
for p in sys.argv[1:]:
    text = pathlib.Path(p).read_text(encoding="utf-8")
    print(f"=== {p} ===")
    print(text)
