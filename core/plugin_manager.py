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
        self._plugin_paths = {}
        self._load_order = []

        self.context    = self

    def discover(self):
        """
        自动发现配置文件名与所在目录同名的插件
        例如:calc_plugin/calc_plugin.json
        """
        if not self.plugin_dir.exists():
            raise FileNotFoundError(f"插件目录不存在: {self.plugin_dir}")

        manifests = {}
        plugin_paths = {}
        for manifest_path in self.plugin_dir.rglob("*.json"):
            if manifest_path.stem != manifest_path.parent.name:
                continue

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    logger.warning("忽略非对象格式的插件配置: %s", manifest_path)
                    continue

                name = manifest.get("name")
                if not isinstance(name, str) or not name.strip():
                    logger.warning("忽略缺少 name 的配置文件: %s", manifest_path)
                    continue
                name = name.strip()
                manifest["name"] = name

                enabled = manifest.get("enabled", True)
                if not isinstance(enabled, bool):
                    raise RuntimeError(
                        f"插件 {name} 的 enabled 必须是布尔值"
                    )

                dependencies = manifest.get("dependencies", [])
                if not isinstance(dependencies, list) or not all(
                    isinstance(dependency, str) and dependency
                    for dependency in dependencies
                ):
                    raise RuntimeError(
                        f"插件 {name} 的 dependencies 必须是插件名称字符串列表"
                    )

                if name in manifests:
                    raise RuntimeError(f"插件名称重复: {name}")

                manifests[name] = manifest
                plugin_paths[name] = manifest_path.parent
                logger.info("发现插件: %s (%s)", name, manifest_path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("读取插件配置失败 %s: %s", manifest_path, exc)

        self._manifests = manifests
        self._plugin_paths = plugin_paths
        return self._manifests

    def load_all(self):
        """加载所有已发现插件"""
        if not self._manifests:
            self.discover()

        load_order = self._resolve_load_order()
        for name in load_order:
            if name not in self.plugins:
                self._load_plugin_instance(name)
        self._load_order = load_order

        return self.plugins

    def load_plugin(self, name: str):
        """加载指定插件及其尚未加载的依赖。"""
        if name not in self._manifests:
            raise KeyError(f"插件 {name} 不存在")

        load_order = self._resolve_load_order([name])
        for plugin_name in load_order:
            if plugin_name not in self.plugins:
                self._load_plugin_instance(plugin_name)
            if plugin_name not in self._load_order:
                self._load_order.append(plugin_name)

        return self.plugins[name]

    def _load_plugin_instance(self, name: str):
        manifest      = self._manifests[name]
        plugin_path   = self._plugin_paths[name]
        default_entry = f"{plugin_path.name}.py"
        entry         = plugin_path / manifest.get("entry", default_entry)
        class_name    = manifest.get("class") or self._infer_class_name(plugin_path)

        if not entry.exists():
            raise FileNotFoundError(f"插件入口文件不存在: {entry}")

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

    @staticmethod
    def _infer_class_name(plugin_path: Path):
        """根据插件目录名推导类名，例如 text_plugin -> TextPlugin。"""
        return "".join(
            part.capitalize()
            for part in re.split(r"[_-]+", plugin_path.name)
            if part
        )

    def _resolve_load_order(self, targets=None):
        """校验依赖关系并返回依赖优先的插件加载顺序。"""
        if targets is None:
            targets = [
                name
                for name, manifest in self._manifests.items()
                if manifest.get("enabled", True)
            ]

        states = {}
        load_order = []

        def visit(name, chain):
            if name not in self._manifests:
                owner = chain[-1] if chain else name
                raise KeyError(f"插件 {owner} 依赖的插件 {name} 不存在")

            manifest = self._manifests[name]
            if not manifest.get("enabled", True):
                owner = chain[-1] if chain else name
                if owner == name:
                    raise RuntimeError(f"插件 {name} 已禁用")
                raise RuntimeError(f"插件 {owner} 依赖的插件 {name} 已禁用")

            state = states.get(name)
            if state == "done":
                return
            if state == "visiting":
                cycle_start = chain.index(name)
                cycle = chain[cycle_start:] + [name]
                raise RuntimeError(f"插件存在循环依赖: {' -> '.join(cycle)}")

            states[name] = "visiting"
            dependencies = manifest.get("dependencies", [])
            for dependency in dependencies:
                visit(dependency, chain + [name])
            states[name] = "done"
            load_order.append(name)

        for target in targets:
            visit(target, [])

        return load_order

    def initialize_all(self):
        """
        为所有插件注入 context, 并调用插件自身的 initialize 方法
        分两步保证所有插件都已加载，并按依赖顺序完成初始化。
        """
        for name, plugin in self.plugins.items():
            plugin.name = name
            plugin.context = self.context

        initialization_order = [
            name for name in self._load_order if name in self.plugins
        ]
        initialization_order.extend(
            name for name in self.plugins if name not in initialization_order
        )
        for name in initialization_order:
            plugin = self.plugins[name]
            init_fn = getattr(plugin, "initialize", None)
            if callable(init_fn):
                init_fn(self.context)

    def register_routes(self, app):
        """
        根据插件方法上的装饰器注册接口。
        每条相对路径都会自动添加插件 name 作为路径前缀。
        """
        for plugin_name, plugin in self.plugins.items():
            route_specs = []
            for function_name in dir(plugin):
                func = getattr(plugin, function_name)
                if not callable(func):
                    continue
                for route in getattr(func, "__plugin_routes__", ()):
                    relative_path = route["path"]
                    if relative_path is None:
                        relative_path = function_name
                    route_specs.append(
                        (route["method"], function_name, relative_path)
                    )

            registered_routes = {}
            for method, function_name, relative_path in route_specs:
                func = getattr(plugin, function_name, None)
                if not callable(func):
                    raise AttributeError(
                        f"插件 {plugin_name} 中找不到可调用函数: {function_name}"
                    )

                suffix = str(relative_path).strip("/")
                path = f"/{plugin_name}"
                if suffix:
                    path = f"{path}/{suffix}"

                route_key = (method, path)
                registered_function = registered_routes.get(route_key)
                if registered_function:
                    if registered_function != function_name:
                        raise ValueError(
                            f"插件 {plugin_name} 的路由 {method} {path} 存在冲突"
                        )
                    continue
                registered_routes[route_key] = function_name

                route_handler = getattr(app, method.lower(), None)
                if route_handler is None:
                    raise ValueError(f"不支持的 HTTP 方法: {method}")

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
