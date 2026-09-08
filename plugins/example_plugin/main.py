# plugins/example_plugin/main.py
from core.plugin_base import PluginBase


class ExamplePlugin(PluginBase):
    def setup(self, context):
        # 必须调用父类 setup，以便获得 manager 和 config
        super().setup(context)
        self.data = self.plugin_config.get("default_msg", "Hello")

    def teardown(self):
        print("ExamplePlugin 卸载完成")

    def hello(self, name: str = "world"):
        """功能函数，会被自动注册为 POST /api/plugin/example/hello"""
        return f"{self.data}, {name}"

    def add(self, a: int, b: int) -> int:
        """功能函数，会被自动注册为 POST /api/plugin/example/add"""
        return a + b