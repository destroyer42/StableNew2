import importlib.util

spec = importlib.util.spec_from_file_location("t", "tests/test_config_passthrough.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("loaded OK")
