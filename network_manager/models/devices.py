"""
Device model classes for routers, switches, and core switches
"""
import copy


class DeviceModel:
    def __init__(self, name: str):
        self.name = name
        self.templates: dict[str, str] = {}
        self.snapshots: list[dict[str, str]] = []

    def get_template_names(self):
        return list(self.templates.keys())

    def get_template(self, name):
        return self.templates.get(name, "")

    def set_template(self, name, text):
        self.templates[name] = text

    def build_full_config(self):
        out = []
        for k in self.get_template_names():
            out.append(f"! ===== {k} =====")
            out.append(self.get_template(k))
        return "\n".join(out)

    def snapshot_templates(self):
        """Save a deep copy of current templates (max 5 snapshots)."""
        if self.templates:
            self.snapshots.append(copy.deepcopy(self.templates))
            if len(self.snapshots) > 5:
                self.snapshots.pop(0)

    def restore_snapshot(self) -> bool:
        """Restore the most recent snapshot. Returns True if successful."""
        if not self.snapshots:
            return False
        self.templates = self.snapshots.pop()
        return True

    def has_snapshots(self) -> bool:
        return bool(self.snapshots)


class RouterModel(DeviceModel):
    def __init__(self, name="router1"):
        super().__init__(name)
        self.templates = {}


class SwitchModel(DeviceModel):
    def __init__(self, name="switch1"):
        super().__init__(name)
        self.templates = {}


class CoreSwitchModel(DeviceModel):
    def __init__(self, name="core-sw1"):
        super().__init__(name)
        self.templates = {}

