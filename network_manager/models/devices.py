"""
Device model classes for routers, switches, and core switches
"""


class DeviceModel:
    def __init__(self, name: str):
        self.name = name
        self.templates: dict[str, str] = {}

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

