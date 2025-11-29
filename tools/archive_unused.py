"""Dead code archiver - detects and archives unused Python files.

This tool analyzes the repository to find Python files that are not imported
or referenced anywhere, then optionally moves them to a timestamped archive
directory with a manifest for tracking and potential restoration.
"""

import argparse
import ast
import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Version info for archive manifest
VERSION = "1.0.0"


class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor to extract import statements."""

    def __init__(self):
        """Initialize analyzer."""
        self.imports: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        """Visit Import node.

        Args:
            node: AST Import node
        """
        for alias in node.names:
            self.imports.add(alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Visit ImportFrom node.

        Args:
            node: AST ImportFrom node
        """
        if node.module:
            self.imports.add(node.module.split(".")[0])


class DeadCodeDetector:
    """Detects unused Python files in repository."""

    def __init__(
        self,
        root_dir: Path,
        exclude_dirs: set[str] | None = None,
        exclude_patterns: set[str] | None = None,
    ):
        """Initialize detector.

        Args:
            root_dir: Repository root directory
            exclude_dirs: Directory names to exclude
            exclude_patterns: File patterns to exclude
        """
        self.root_dir = root_dir
        self.exclude_dirs = exclude_dirs or {
            ".git",
            ".pytest_cache",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            "build",
            "dist",
            "*.egg-info",
            "ARCHIVE",
            "archive",
        }
        self.exclude_patterns = exclude_patterns or {
            "__init__.py",  # Always keep package markers
            "conftest.py",  # Pytest config
            "setup.py",  # Build config
        }

        self.all_files: set[Path] = set()
        self.import_graph: dict[Path, set[str]] = {}
        self.entrypoints: set[Path] = set()

    def find_python_files(self) -> set[Path]:
        """Find all Python files in repository.

        Returns:
            Set of Python file paths
        """
        python_files = set()

        for py_file in self.root_dir.rglob("*.py"):
            # Check if in excluded directory
            if any(excluded in py_file.parts for excluded in self.exclude_dirs):
                continue

            # Check if matches excluded pattern
            if any(pattern in py_file.name for pattern in self.exclude_patterns):
                continue

            python_files.add(py_file)

        logger.info(f"Found {len(python_files)} Python files")
        return python_files

    def build_import_graph(self, files: set[Path]) -> dict[Path, set[str]]:
        """Build graph of imports for each file.

        Args:
            files: Set of Python files to analyze

        Returns:
            Dictionary mapping file to set of imported modules
        """
        import_graph = {}

        for py_file in files:
            try:
                with open(py_file, encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=str(py_file))

                analyzer = ImportAnalyzer()
                analyzer.visit(tree)
                import_graph[py_file] = analyzer.imports

            except SyntaxError:
                logger.warning(f"Syntax error in {py_file}, skipping")
            except Exception as e:
                logger.warning(f"Error analyzing {py_file}: {e}")

        return import_graph

    def find_entrypoints(self, files: set[Path]) -> set[Path]:
        """Find entrypoint files (main, cli, apps).

        Args:
            files: Set of Python files

        Returns:
            Set of entrypoint file paths
        """
        entrypoints = set()

        for py_file in files:
            # Check for main entrypoint patterns
            if py_file.name in {"main.py", "cli.py", "__main__.py", "app.py"}:
                entrypoints.add(py_file)
                continue

            # Check for if __name__ == "__main__"
            try:
                with open(py_file, encoding="utf-8") as f:
                    content = f.read()
                    if '__name__ == "__main__"' in content or "__name__ == '__main__'" in content:
                        entrypoints.add(py_file)
            except Exception:
                pass

        logger.info(f"Found {len(entrypoints)} entrypoint files")
        return entrypoints

    def find_referenced_modules(self, files: set[Path]) -> set[str]:
        """Find all referenced module names.

        Args:
            files: Set of Python files

        Returns:
            Set of referenced module names
        """
        referenced = set()

        for py_file in files:
            # Get module name from file path
            rel_path = py_file.relative_to(self.root_dir)
            parts = list(rel_path.parts[:-1]) + [rel_path.stem]

            # Add all possible import paths
            for i in range(len(parts)):
                module_name = ".".join(parts[: i + 1])
                referenced.add(module_name)

                # Also add individual parts
                referenced.add(parts[i])

        return referenced

    def find_unused_files(self) -> list[Path]:
        """Find files that are not imported or referenced.

        Returns:
            List of unused file paths
        """
        self.all_files = self.find_python_files()
        self.import_graph = self.build_import_graph(self.all_files)
        self.entrypoints = self.find_entrypoints(self.all_files)

        # Collect all imported modules
        all_imports = set()
        for imports in self.import_graph.values():
            all_imports.update(imports)

        # Find referenced module names from file structure
        referenced_modules = self.find_referenced_modules(self.all_files)

        # Find unused files
        unused = []
        for py_file in self.all_files:
            # Skip entrypoints
            if py_file in self.entrypoints:
                continue

            # Skip test files
            if "test" in py_file.parts or py_file.name.startswith("test_"):
                continue

            # Check if this file's module is imported
            rel_path = py_file.relative_to(self.root_dir)
            module_parts = list(rel_path.parts[:-1]) + [rel_path.stem]

            # Check various possible import names
            is_imported = False
            for i in range(len(module_parts)):
                module_name = ".".join(module_parts[i:])
                if module_name in all_imports:
                    is_imported = True
                    break

                # Check individual parts
                if module_parts[i] in all_imports:
                    is_imported = True
                    break

            if not is_imported:
                unused.append(py_file)

        logger.info(f"Found {len(unused)} potentially unused files")
        return unused

    def generate_report(self, unused_files: list[Path]) -> str:
        """Generate report of unused files.

        Args:
            unused_files: List of unused file paths

        Returns:
            Report text
        """
        report = ["=" * 80, "Dead Code Detection Report", "=" * 80, ""]

        if not unused_files:
            report.append("No unused files detected!")
            return "\n".join(report)

        report.append(f"Found {len(unused_files)} potentially unused files:\n")

        for py_file in sorted(unused_files):
            rel_path = py_file.relative_to(self.root_dir)
            size = py_file.stat().st_size
            report.append(f"  - {rel_path} ({size:,} bytes)")

        report.append("\n" + "=" * 80)
        return "\n".join(report)


class FileArchiver:
    """Archives unused files with manifest."""

    def __init__(self, root_dir: Path, version: str = VERSION):
        """Initialize archiver.

        Args:
            root_dir: Repository root directory
            version: Current repository version
        """
        self.root_dir = root_dir
        self.version = version

    def create_archive_dir(self) -> Path:
        """Create timestamped archive directory.

        Returns:
            Path to archive directory
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"ARCHIVE/_{timestamp}_v{self.version}"
        archive_dir = self.root_dir / archive_name

        archive_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created archive directory: {archive_dir}")
        return archive_dir

    def compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file.

        Args:
            file_path: Path to file

        Returns:
            Hex digest of file hash
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def archive_files(self, files: list[Path], dry_run: bool = False) -> dict[str, any]:
        """Archive files and create manifest.

        Args:
            files: List of files to archive
            dry_run: If True, don't actually move files

        Returns:
            Archive manifest dictionary
        """
        if not files:
            logger.info("No files to archive")
            return {}

        if dry_run:
            logger.info(f"DRY RUN: Would archive {len(files)} files")
            return {"dry_run": True, "file_count": len(files)}

        archive_dir = self.create_archive_dir()

        manifest = {
            "version": self.version,
            "timestamp": datetime.now().isoformat(),
            "archived_files": [],
        }

        for file_path in files:
            try:
                # Compute hash before moving
                file_hash = self.compute_file_hash(file_path)

                # Get relative path
                rel_path = file_path.relative_to(self.root_dir)

                # Create archive path preserving structure
                archive_path = archive_dir / rel_path
                archive_path.parent.mkdir(parents=True, exist_ok=True)

                # Move file
                shutil.move(str(file_path), str(archive_path))

                # Add to manifest
                manifest["archived_files"].append(
                    {
                        "original_path": str(rel_path),
                        "archive_path": str(archive_path.relative_to(self.root_dir)),
                        "size": archive_path.stat().st_size,
                        "hash": file_hash,
                        "reason": "unused - not imported or referenced",
                    }
                )

                logger.info(f"Archived: {rel_path}")

            except Exception as e:
                logger.error(f"Error archiving {file_path}: {e}")

        # Write manifest
        manifest_path = archive_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        logger.info(f"Wrote manifest: {manifest_path}")
        logger.info(f"Archived {len(manifest['archived_files'])} files")

        return manifest

    def undo_archive(self, manifest_path: Path) -> bool:
        """Restore files from archive using manifest.

        Args:
            manifest_path: Path to manifest.json

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

            archive_dir = manifest_path.parent

            for file_info in manifest["archived_files"]:
                archive_path = self.root_dir / file_info["archive_path"]
                original_path = self.root_dir / file_info["original_path"]

                # Create parent directory
                original_path.parent.mkdir(parents=True, exist_ok=True)

                # Move file back
                shutil.move(str(archive_path), str(original_path))
                logger.info(f"Restored: {file_info['original_path']}")

            logger.info(f"Restored {len(manifest['archived_files'])} files")
            return True

        except Exception as e:
            logger.error(f"Error restoring from archive: {e}")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Detect and archive unused Python files")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root directory (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be archived without moving files",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Only consider files changed since git tag/sha (best-effort via git diff)",
    )
    parser.add_argument(
        "--undo",
        type=Path,
        metavar="MANIFEST",
        help="Restore files from archive using manifest.json",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=VERSION,
        help=f"Version string for archive (default: {VERSION})",
    )

    args = parser.parse_args()

    # Handle undo
    if args.undo:
        archiver = FileArchiver(args.root, args.version)
        success = archiver.undo_archive(args.undo)
        return 0 if success else 1

    # Detect unused files
    detector = DeadCodeDetector(args.root)
    unused_files = detector.find_unused_files()

    # Filter by --since if provided
    if args.since and unused_files:
        try:
            # Get list of changed files since the specified ref
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{args.since}...HEAD"],
                cwd=args.root,
                capture_output=True,
                text=True,
                check=True,
            )

            changed_files = {
                (args.root / line.strip()).resolve()
                for line in result.stdout.splitlines()
                if line.strip().endswith(".py")
            }

            # Only keep unused files that have changed
            original_count = len(unused_files)
            unused_files = [f for f in unused_files if f.resolve() in changed_files]

            if unused_files:
                logger.info(
                    f"Filtered to {len(unused_files)} unused files (from {original_count}) "
                    f"changed since {args.since}"
                )
            else:
                logger.info(
                    f"No unused files found that changed since {args.since} "
                    f"(had {original_count} total unused)"
                )

        except subprocess.CalledProcessError as e:
            logger.warning(f"Could not run git diff: {e}. Showing all unused files.")
        except Exception as e:
            logger.warning(f"Error filtering by --since: {e}. Showing all unused files.")

    # Generate and print report
    report = detector.generate_report(unused_files)
    print(report)

    # Archive if requested
    if unused_files and not args.dry_run:
        response = input("\nArchive these files? [y/N]: ")
        if response.lower() != "y":
            print("Cancelled")
            return 0

    if unused_files:
        archiver = FileArchiver(args.root, args.version)
        manifest = archiver.archive_files(unused_files, dry_run=args.dry_run)

        if manifest and not args.dry_run:
            print("\nArchive created successfully")
            print("To undo: python -m tools.archive_unused --undo ARCHIVE/.../manifest.json")

    return 0


if __name__ == "__main__":
    exit(main())
