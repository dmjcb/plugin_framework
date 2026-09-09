import importlib.util
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self, plugin_dir: str):
        self.plugin_dir = Path(plugin_dir)
        self.plugins    = {}
        self._manifests = {}

        self.context    = self

    def discover(self):
        """
        自动发现配置文件名与所在目录同名的插件
        例如:calc_plugin/calc_plugin.json
        """
        if not self.plugin_dir.exists():
            raise FileNotFoundError(f"插件目录不存在: {self.plugin_dir}")

        for manifest_path in self.plugin_dir.rglob("*.json"):
            if manifest_path.stem != manifest_path.parent.name:
                continue

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                name = manifest.get("name")
                if not name:
                    logger.warning("忽略缺少 name 的配置文件: %s", manifest_path)
                    continue

                manifest["_dir"] = str(manifest_path.parent)
                self._manifests[name] = manifest
                logger.info("发现插件: %s (%s)", name, manifest_path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("读取插件配置失败 %s: %s", manifest_path, exc)

        return self._manifests

    def load_all(self):
        """加载所有已发现插件"""
        if not self._manifests:
            self.discover()

        for name in self._manifests:
            self.load_plugin(name)

        return self.plugins

    def load_plugin(self, name: str):
        if name not in self._manifests:
            raise KeyError(f"插件 {name} 不存在")

        manifest      = self._manifests[name]
        plugin_path   = Path(manifest["_dir"])
        default_entry = f"{plugin_path.name}.py"
        entry         = plugin_path / manifest.get("entry", default_entry)
        class_name    = manifest.get("class")

        if not entry.exists():
            raise FileNotFoundError(f"插件入口文件不存在: {entry}")
        if not class_name:
            raise RuntimeError(f"插件 {name} 未配置 class 字段")

        safe_name = re.sub(r"\W", "_", name)
        module_name = f"plugin_{safe_name}"

        spec = importlib.util.spec_from_file_location(module_name, entry)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载插件模块: {entry}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plugin_cls = getattr(module, class_name)
        plugin = plugin_cls()

        plugin.name = name
        self.plugins[name] = plugin

        logger.info("成功加载插件: %s", name)
        return plugin

    def initialize_all(self):
        """
        为所有插件注入 context, 并调用插件自身的 initialize 方法
        分两步保证所有插件都已加载且统一可访问。
        """
        for name, plugin in self.plugins.items():
            plugin.name = name
            plugin.context = self.context

        for plugin in self.plugins.values():
            init_fn = getattr(plugin, "initialize", None)
            if callable(init_fn):
                init_fn(self.context)

    def register_routes(self, app):
        """
        根据插件 JSON 配置中按 HTTP 方法分组的 routes 注册接口。
        每条相对路径都会自动添加插件 name 作为路径前缀。
        """
        for plugin_name, manifest in self._manifests.items():
            plugin = self.plugins.get(plugin_name)
            if plugin is None:
                logger.warning("插件 %s 未加载，跳过路由注册", plugin_name)
                continue

            route_groups = manifest.get("routes", {})
            if not isinstance(route_groups, dict):
                logger.warning("插件 %s 的 routes 必须按 GET、POST 分组", plugin_name)
                continue

            for method in ("GET", "POST"):
                for route in route_groups.get(method, []):
                    function_name = route.get("function")
                    relative_path = route.get("path")

                    if not function_name or relative_path is None:
                        logger.warning("插件 %s 存在无效路由配置", plugin_name)
                        continue

                    func = getattr(plugin, function_name, None)
                    if not callable(func):
                        raise AttributeError(
                            f"插件 {plugin_name} 中找不到可调用函数: {function_name}"
                        )

                    route_handler = getattr(app, method.lower(), None)
                    if route_handler is None:
                        raise ValueError(f"不支持的 HTTP 方法: {method}")

                    suffix = str(relative_path).strip("/")
                    path = f"/{plugin_name}"
                    if suffix:
                        path = f"{path}/{suffix}"

                    route_handler(
                        path,
                        tags=[plugin_name],
                        name=f"{plugin_name}_{function_name}"
                    )(func)

                    logger.info(
                        "注册路由 %s %s -> %s.%s",
                        method,
                        path,
                        plugin_name,
                        function_name,
                    )

    def get_plugin(self, name: str):
        if name not in self.plugins:
            raise KeyError(f"插件 {name} 未加载，已加载插件: {list(self.plugins)}")
        return self.plugins[name]

    def call(self, plugin_name: str, method_name: str, *args, **kwargs):
        plugin = self.get_plugin(plugin_name)
        method = getattr(plugin, method_name)
        return method(*args, **kwargs)

    def list_plugins(self):
        return list(self.plugins)
