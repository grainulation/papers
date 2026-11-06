"""Bundle only a native, validated executable; never infer manylinux compatibility."""
import importlib.util
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        found = [root / 'src/overturn_arbiter/_bin' / n for n in ('overturn', 'overturn.exe')
                 if (root / 'src/overturn_arbiter/_bin' / n).is_file()]
        if not found:
            return
        if len(found) != 1:
            raise ValueError('expected exactly one bundled reducer')
        spec = importlib.util.spec_from_file_location('wheel_platform', root / 'wheel_platform.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        build_data['pure_python'] = False
        build_data['tag'] = 'py3-none-' + module.validate_binary(found[0])

    def finalize(self, version, build_data, artifact_path):
        spec = importlib.util.spec_from_file_location('release_hygiene', Path(self.root) / 'release_hygiene.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            module.check_wheel(artifact_path)
        except Exception:
            # Never leave a failed release artifact available for accidental upload.
            Path(artifact_path).unlink(missing_ok=True)
            raise
