"""Load the HA-independent modules without importing the HA entry point."""

import sys
from pathlib import Path
from types import ModuleType

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "evakool"
package = ModuleType("evakool_unit")
package.__path__ = [str(PACKAGE)]
sys.modules["evakool_unit"] = package
