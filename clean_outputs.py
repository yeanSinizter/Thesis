from pathlib import Path
import shutil

OUTPUT_ROOT = Path("outputs")
TARGETS = [OUTPUT_ROOT / "artifacts", OUTPUT_ROOT / "reports"]


def clean_output_root(root: Path):
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        return
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
            print(f"Removed directory: {child}")
        else:
            child.unlink()
            print(f"Removed file: {child}")


def main():
    clean_output_root(OUTPUT_ROOT)
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        print(f"Created empty directory: {target}")
    print("Output cleanup completed.")


if __name__ == "__main__":
    main()
