def extract_name_prefix(name: str, base: str) -> str:
    """
    Generate a filename prefix from a name and a base string.
    Both are sanitized for safe filenames.
    """
    import re

    def safe(s):
        # Remove or replace invalid filename characters
        s = re.sub(r'[<>:"\\/|?*]', "_", s)
        s = s.strip(" .")
        return s

    return f"{safe(name)}_{safe(base)}"
