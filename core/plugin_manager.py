import importlib.util
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginDefinition:
    """一个经过校验、可直接用于加载的插件定义。"""

    name: str
    directory: Path
    enabled: bool = True
    dependencies: tuple[str, ...] = ()
    entry: str | None = None
    class_name: str | None = None

    @property
    def entry_path(self) -> Path:
        """返回入口文件路径，默认使用与插件目录同名的 Python 文件。"""
        filename = self.entry or f"{self.directory.name}.py"
        return self.directory / filename

    @property
    def resolved_class_name(self) -> str:
        """返回插件类名，默认根据目录名转换为大驼峰命名。"""
        if self.class_name:
            return self.class_name

        name_parts = re.split(r"[_-]+", self.directory.name)
        return "".join(part.capitalize() for part in name_parts if part)


@dataclass(frozen=True)
class RouteDefinition:
    """插件方法上的一条 HTTP 路由声明。"""

    method: str
    function_name: str
    relative_path: str


class PluginManager:
    """负责插件发现、依赖管理、加载、初始化和路由注册。"""

    def __init__(self, plugin_dir: str | Path):
        self.plugin_dir = Path(plugin_dir)
        self.plugins: dict[str, Any] = {}

        self._definitions: dict[str, PluginDefinition] = {}
        self._load_order: list[str] = []
        self._discovered = False

        # PluginManager 同时作为插件上下文注入，供插件间调用。
        self.context = self

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def discover(self) -> dict[str, PluginDefinition]:
        """发现并解析插件目录下的全部插件配置。"""
        if not self.plugin_dir.exists():
            raise FileNotFoundError(f"插件目录不存在: {self.plugin_dir}")

        definitions: dict[str, PluginDefinition] = {}
        for manifest_path in self._find_manifest_files():
            manifest = self._read_manifest(manifest_path)
            if manifest is None:
                continue

            definition = self._parse_definition(manifest, manifest_path)
            if definition is None:
                continue
            if definition.name in definitions:
                raise RuntimeError(f"插件名称重复: {definition.name}")

            definitions[definition.name] = definition
            logger.info("发现插件: %s (%s)", definition.name, manifest_path)

        self._definitions = definitions
        self._discovered = True
        return self._definitions

    def load_all(self) -> dict[str, Any]:
        """按依赖顺序加载全部已启用插件。"""
        self._ensure_discovered()
        load_order = self._resolve_load_order()
        self._load_plugins_in_order(load_order)
        return self.plugins

    def load_plugin(self, name: str) -> Any:
        """加载指定插件及其尚未加载的依赖。"""
        self._ensure_discovered()
        load_order = self._resolve_load_order([name])
        self._load_plugins_in_order(load_order)
        return self.plugins[name]

    def initialize_all(self) -> None:
        """注入上下文，并按依赖顺序初始化全部已加载插件。"""
        for name, plugin in self.plugins.items():
            plugin.name = name
            plugin.context = self.context

        for name in self._loaded_names_in_dependency_order():
            initialize = getattr(self.plugins[name], "initialize", None)
            if callable(initialize):
                initialize(self.context)

    def register_routes(self, app: Any) -> None:
        """注册插件方法装饰器声明的 GET、POST 路由。"""
        for plugin_name, plugin in self.plugins.items():
            routes = self._collect_plugin_routes(plugin)
            self._register_plugin_routes(app, plugin_name, plugin, routes)

    def get_plugin(self, name: str) -> Any:
        """返回指定的已加载插件。"""
        if name not in self.plugins:
            loaded_names = list(self.plugins)
            raise KeyError(f"插件 {name} 未加载，已加载插件: {loaded_names}")
        return self.plugins[name]

    def call(
        self,
        plugin_name: str,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """调用一个已加载插件的方法。"""
        plugin = self.get_plugin(plugin_name)
        method = getattr(plugin, method_name)
        return method(*args, **kwargs)

    def list_plugins(self) -> list[str]:
        """返回全部已加载插件名称。"""
        return list(self.plugins)

    # ------------------------------------------------------------------
    # 配置发现与解析
    # ------------------------------------------------------------------

    def _ensure_discovered(self) -> None:
        """尚未执行发现时自动发现插件。"""
        if not self._discovered:
            self.discover()

    def _find_manifest_files(self) -> list[Path]:
        """查找文件名与所在目录名相同的 JSON 配置。"""
        manifest_paths = (
            path
            for path in self.plugin_dir.rglob("*.json")
            if path.stem == path.parent.name
        )
        return sorted(manifest_paths)

    @staticmethod
    def _read_manifest(manifest_path: Path) -> dict[str, Any] | None:
        """读取一个 JSON 配置；不可读取的配置会记录日志并跳过。"""
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("读取插件配置失败 %s: %s", manifest_path, exc)
            return None

        if not isinstance(manifest, dict):
            logger.warning("忽略非对象格式的插件配置: %s", manifest_path)
            return None
        return manifest

    @staticmethod
    def _parse_definition(
        manifest: dict[str, Any],
        manifest_path: Path,
    ) -> PluginDefinition | None:
        """校验原始配置并转换为 PluginDefinition。"""
        raw_name = manifest.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            logger.warning("忽略缺少 name 的配置文件: %s", manifest_path)
            return None
        name = raw_name.strip()

        enabled = manifest.get("enabled", True)
        if not isinstance(enabled, bool):
            raise RuntimeError(f"插件 {name} 的 enabled 必须是布尔值")

        dependencies = manifest.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(
            isinstance(dependency, str) and dependency.strip()
            for dependency in dependencies
        ):
            raise RuntimeError(
                f"插件 {name} 的 dependencies 必须是插件名称字符串列表"
            )

        entry = PluginManager._optional_string(manifest, "entry", name)
        class_name = PluginManager._optional_string(manifest, "class", name)
        return PluginDefinition(
            name=name,
            directory=manifest_path.parent,
            enabled=enabled,
            dependencies=tuple(
                dependency.strip() for dependency in dependencies
            ),
            entry=entry,
            class_name=class_name,
        )

    @staticmethod
    def _optional_string(
        manifest: dict[str, Any],
        field_name: str,
        plugin_name: str,
    ) -> str | None:
        """读取一个可选字符串字段，并统一检查字段类型。"""
        value = manifest.get(field_name)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(
                f"插件 {plugin_name} 的 {field_name} 必须是非空字符串"
            )
        return value.strip()

    # ------------------------------------------------------------------
    # 依赖解析与插件加载
    # ------------------------------------------------------------------

    def _resolve_load_order(
        self,
        targets: Iterable[str] | None = None,
    ) -> list[str]:
        """校验依赖并返回依赖优先的加载顺序。"""
        if targets is None:
            targets = (
                name
                for name, definition in self._definitions.items()
                if definition.enabled
            )

        states: dict[str, str] = {}
        load_order: list[str] = []

        def visit(name: str, chain: list[str]) -> None:
            definition = self._require_enabled_definition(name, chain)

            # visiting 表示仍在当前递归路径中，再次遇到即说明存在环。
            state = states.get(name)
            if state == "done":
                return
            if state == "visiting":
                cycle_start = chain.index(name)
                cycle = chain[cycle_start:] + [name]
                raise RuntimeError(f"插件存在循环依赖: {' -> '.join(cycle)}")

            states[name] = "visiting"
            for dependency in definition.dependencies:
                visit(dependency, chain + [name])

            # 依赖全部加入结果后，再加入当前插件，从而得到正确加载顺序。
            states[name] = "done"
            load_order.append(name)

        for target in targets:
            visit(target, [])

        return load_order

    def _require_enabled_definition(
        self,
        name: str,
        chain: list[str],
    ) -> PluginDefinition:
        """返回已启用插件定义，并给出带依赖来源的错误信息。"""
        owner = chain[-1] if chain else name
        if name not in self._definitions:
            if not chain:
                raise KeyError(f"插件 {name} 不存在")
            raise KeyError(f"插件 {owner} 依赖的插件 {name} 不存在")

        definition = self._definitions[name]
        if not definition.enabled:
            if owner == name:
                raise RuntimeError(f"插件 {name} 已禁用")
            raise RuntimeError(f"插件 {owner} 依赖的插件 {name} 已禁用")
        return definition

    def _load_plugins_in_order(self, load_order: Iterable[str]) -> None:
        """按指定顺序加载插件，并记录后续初始化使用的顺序。"""
        for name in load_order:
            if name not in self.plugins:
                self.plugins[name] = self._create_plugin_instance(
                    self._definitions[name]
                )
            if name not in self._load_order:
                self._load_order.append(name)

    @staticmethod
    def _create_plugin_instance(definition: PluginDefinition) -> Any:
        """从插件入口文件导入并实例化插件类。"""
        entry_path = definition.entry_path
        if not entry_path.exists():
            raise FileNotFoundError(f"插件入口文件不存在: {entry_path}")

        safe_name = re.sub(r"\W", "_", definition.name)
        module_name = f"plugin_{safe_name}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载插件模块: {entry_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class_name = definition.resolved_class_name
        try:
            plugin_class = getattr(module, class_name)
        except AttributeError as exc:
            raise AttributeError(
                f"插件入口 {entry_path} 中找不到类 {class_name}"
            ) from exc

        plugin = plugin_class()
        plugin.name = definition.name
        logger.info("成功加载插件: %s", definition.name)
        return plugin

    def _loaded_names_in_dependency_order(self) -> list[str]:
        """返回依赖优先的已加载插件名称，并兼容手动注入的插件。"""
        ordered_names = [
            name for name in self._load_order if name in self.plugins
        ]
        known_names = set(ordered_names)
        ordered_names.extend(
            name for name in self.plugins if name not in known_names
        )
        return ordered_names

    # ------------------------------------------------------------------
    # 路由收集与注册
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_plugin_routes(plugin: Any) -> list[RouteDefinition]:
        """收集插件方法上由 plugin_route 装饰器声明的路由。"""
        routes: list[RouteDefinition] = []
        for function_name in dir(plugin):
            function = getattr(plugin, function_name)
            if not callable(function):
                continue

            for metadata in getattr(function, "__plugin_routes__", ()):
                relative_path = metadata["path"]
                if relative_path is None:
                    relative_path = function_name
                routes.append(
                    RouteDefinition(
                        method=metadata["method"],
                        function_name=function_name,
                        relative_path=relative_path,
                    )
                )
        return routes

    def _register_plugin_routes(
        self,
        app: Any,
        plugin_name: str,
        plugin: Any,
        routes: Iterable[RouteDefinition],
    ) -> None:
        """检查一个插件的路由冲突，并逐条注册路由。"""
        registered_routes: dict[tuple[str, str], str] = {}
        for route in routes:
            full_path = self._build_route_path(
                plugin_name,
                route.relative_path,
            )
            route_key = (route.method, full_path)
            previous_function = registered_routes.get(route_key)

            if previous_function and previous_function != route.function_name:
                raise ValueError(
                    f"插件 {plugin_name} 的路由 "
                    f"{route.method} {full_path} 存在冲突"
                )
            if previous_function:
                continue

            registered_routes[route_key] = route.function_name
            self._register_route(app, plugin_name, plugin, route, full_path)

    @staticmethod
    def _build_route_path(plugin_name: str, relative_path: str) -> str:
        """将插件名和插件内部路径组合成完整路由。"""
        suffix = relative_path.strip("/")
        if not suffix:
            return f"/{plugin_name}"
        return f"/{plugin_name}/{suffix}"

    @staticmethod
    def _register_route(
        app: Any,
        plugin_name: str,
        plugin: Any,
        route: RouteDefinition,
        full_path: str,
    ) -> None:
        """向 Web 应用注册一条已经校验的路由。"""
        function = getattr(plugin, route.function_name, None)
        if not callable(function):
            raise AttributeError(
                f"插件 {plugin_name} 中找不到可调用函数: "
                f"{route.function_name}"
            )

        route_handler: Callable[..., Any] | None = getattr(
            app,
            route.method.lower(),
            None,
        )
        if route_handler is None:
            raise ValueError(f"不支持的 HTTP 方法: {route.method}")

        route_handler(
            full_path,
            tags=[plugin_name],
            name=f"{plugin_name}_{route.function_name}",
        )(function)
        logger.info(
            "注册路由 %s %s -> %s.%s",
            route.method,
            full_path,
            plugin_name,
            route.function_name,
        )
