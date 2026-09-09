import json
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

from core.plugin_manager import PluginManager


class FakeApp:
    """测试路由注册时使用的最小 Web 应用替身。"""

    def __init__(self):
        self.routes = []

    def get(self, path, **options):
        return self._register("GET", path, options)

    def post(self, path, **options):
        return self._register("POST", path, options)

    def _register(self, method, path, options):
        def decorator(function):
            self.routes.append((method, path, options, function))
            return function

        return decorator


class PluginManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.plugin_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_plugin(self, directory_name, manifest, source):
        """创建一个遵循目录同名约定的临时插件。"""
        directory = self.plugin_dir / directory_name
        directory.mkdir()
        (directory / f"{directory_name}.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        (directory / f"{directory_name}.py").write_text(
            dedent(source),
            encoding="utf-8",
        )

    def test_discover_infers_entry_and_class_name(self):
        self.create_plugin(
            "sample_plugin",
            {"name": "sample"},
            """
            from core.plugin_base import PluginBase

            class SamplePlugin(PluginBase):
                pass
            """,
        )

        manager = PluginManager(self.plugin_dir)
        definition = manager.discover()["sample"]

        self.assertEqual(
            definition.entry_path,
            self.plugin_dir / "sample_plugin" / "sample_plugin.py",
        )
        self.assertEqual(definition.resolved_class_name, "SamplePlugin")

    def test_dependencies_control_load_and_initialization_order(self):
        self.create_plugin(
            "dependent_plugin",
            {"name": "dependent", "dependencies": ["base"]},
            """
            from core.plugin_base import PluginBase

            class DependentPlugin(PluginBase):
                def initialize(self, context):
                    base = context.get_plugin("base")
                    if not base.ready:
                        raise RuntimeError("base 尚未初始化")
                    super().initialize(context)
                    self.ready = True
            """,
        )
        self.create_plugin(
            "base_plugin",
            {"name": "base"},
            """
            from core.plugin_base import PluginBase

            class BasePlugin(PluginBase):
                def initialize(self, context):
                    super().initialize(context)
                    self.ready = True
            """,
        )

        manager = PluginManager(self.plugin_dir)
        manager.load_all()
        manager.initialize_all()

        self.assertEqual(manager.list_plugins(), ["base", "dependent"])
        self.assertTrue(manager.get_plugin("dependent").ready)

    def test_load_plugin_discovers_and_loads_dependencies(self):
        self.create_plugin(
            "base_plugin",
            {"name": "base"},
            """
            from core.plugin_base import PluginBase

            class BasePlugin(PluginBase):
                pass
            """,
        )
        self.create_plugin(
            "dependent_plugin",
            {"name": "dependent", "dependencies": ["base"]},
            """
            from core.plugin_base import PluginBase

            class DependentPlugin(PluginBase):
                pass
            """,
        )

        manager = PluginManager(self.plugin_dir)
        manager.load_plugin("dependent")

        self.assertEqual(manager.list_plugins(), ["base", "dependent"])

    def test_disabled_plugin_is_skipped(self):
        self.create_plugin(
            "disabled_plugin",
            {"name": "disabled", "enabled": False},
            """
            from core.plugin_base import PluginBase

            class DisabledPlugin(PluginBase):
                pass
            """,
        )

        manager = PluginManager(self.plugin_dir)
        self.assertEqual(manager.load_all(), {})
        with self.assertRaisesRegex(RuntimeError, "插件 disabled 已禁用"):
            manager.load_plugin("disabled")

    def test_missing_dependency_is_rejected(self):
        self.create_plugin(
            "dependent_plugin",
            {"name": "dependent", "dependencies": ["missing"]},
            """
            from core.plugin_base import PluginBase

            class DependentPlugin(PluginBase):
                pass
            """,
        )

        manager = PluginManager(self.plugin_dir)
        with self.assertRaisesRegex(KeyError, "依赖的插件 missing 不存在"):
            manager.load_all()

    def test_loading_unknown_plugin_has_clear_error(self):
        manager = PluginManager(self.plugin_dir)

        with self.assertRaisesRegex(KeyError, "插件 unknown 不存在"):
            manager.load_plugin("unknown")

    def test_circular_dependency_is_rejected(self):
        self.create_plugin(
            "first_plugin",
            {"name": "first", "dependencies": ["second"]},
            """
            from core.plugin_base import PluginBase

            class FirstPlugin(PluginBase):
                pass
            """,
        )
        self.create_plugin(
            "second_plugin",
            {"name": "second", "dependencies": ["first"]},
            """
            from core.plugin_base import PluginBase

            class SecondPlugin(PluginBase):
                pass
            """,
        )

        manager = PluginManager(self.plugin_dir)
        with self.assertRaisesRegex(
            RuntimeError,
            "first -> second -> first",
        ):
            manager.load_all()

    def test_default_and_custom_routes_are_registered(self):
        self.create_plugin(
            "route_plugin",
            {"name": "route"},
            """
            from core.plugin_base import PluginBase, plugin_route

            class RoutePlugin(PluginBase):
                @plugin_route("GET")
                def ping(self):
                    return "pong"

                @plugin_route("POST", "/submit-data")
                def submit(self, data: dict):
                    return data

                def hidden(self):
                    return None
            """,
        )

        manager = PluginManager(self.plugin_dir)
        manager.load_all()
        app = FakeApp()
        manager.register_routes(app)

        registered_routes = {
            (method, path) for method, path, _, _ in app.routes
        }
        self.assertEqual(
            registered_routes,
            {
                ("GET", "/route/ping"),
                ("POST", "/route/submit-data"),
            },
        )

    def test_conflicting_routes_are_rejected(self):
        self.create_plugin(
            "conflict_plugin",
            {"name": "conflict"},
            """
            from core.plugin_base import PluginBase, plugin_route

            class ConflictPlugin(PluginBase):
                @plugin_route("GET", "/same")
                def first(self):
                    pass

                @plugin_route("GET", "/same")
                def second(self):
                    pass
            """,
        )

        manager = PluginManager(self.plugin_dir)
        manager.load_all()
        with self.assertRaisesRegex(ValueError, "路由 GET /conflict/same 存在冲突"):
            manager.register_routes(FakeApp())


if __name__ == "__main__":
    unittest.main()
