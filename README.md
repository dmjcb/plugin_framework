# Python 插件化 FastAPI 框架

框架会扫描 `plugins` 下各插件目录中与目录同名的 JSON 配置，动态加载并初始化插件。插件方法可通过装饰器注册为 FastAPI 路由，插件之间可以通过注入的 `context` 获取或调用其他插件。

## 项目结构

```text
.
├── core/
│   ├── plugin_base.py       # 插件基类
│   └── plugin_manager.py    # 插件发现、加载、上下文和路由注册
├── plugins/
│   ├── calc_plugin/         # 示例：计算插件
│   │   ├── calc_plugin.json
│   │   └── calc_plugin.py
│   └── text_plugin/         # 示例：文本插件及跨插件调用
│       ├── text_plugin.json
│       └── text_plugin.py
└── main.py                  # FastAPI 应用入口
```

插件目录可以嵌套。`PluginManager` 会递归查找 JSON 文件，但仅把文件名与所在目录名相同的文件视为插件配置。例如，`calc_plugin/calc_plugin.json` 会被发现，`calc_plugin/plugin.json` 不会被发现。

## 新增插件

下面以新增 `hello` 插件为例。

### 1. 创建插件目录

在 `plugins` 下新建目录：

```text
plugins/
└── hello_plugin/
    ├── hello_plugin.json
    └── hello_plugin.py
```

目录名决定配置文件和默认入口文件的名称；插件运行时的唯一名称仍由 JSON 配置中的 `name` 决定。

### 2. 编写插件配置

创建 `plugins/hello_plugin/hello_plugin.json`：

```json
{
  "name": "hello",
  "dependencies": ["calc"]
}
```

字段说明：

| 字段 | 是否必需 | 说明 |
| --- | --- | --- |
| `name` | 是 | 插件唯一名称，也是获取插件时使用的名称 |
| `enabled` | 否 | 是否启用插件，默认是 `true` |
| `dependencies` | 否 | 当前插件依赖的其他插件名称列表，默认是空列表 |
| `entry` | 否 | 非标准入口文件名的兼容配置；默认使用与目录同名的 `.py` 文件 |
| `class` | 否 | 非标准插件类名的兼容配置；默认根据目录名推导 |

例如，目录名 `hello_plugin` 会自动对应入口文件 `hello_plugin.py` 和类名 `HelloPlugin`，因此通常不需要配置 `entry` 和 `class`。示例中的 `hello` 插件会在 `calc` 之后加载和初始化；依赖不存在、被禁用或形成循环时，应用会在启动期间报错。

如果需要临时停用插件，可以设置：

```json
{
  "name": "hello",
  "enabled": false
}
```

建议确保插件名称和路由路径在整个项目中唯一。JSON 配置中不再声明路由，GET 和 POST 路由统一使用代码装饰器管理。

### 3. 实现插件类

创建 `plugins/hello_plugin/hello_plugin.py`：

```python
from core.plugin_base import PluginBase, plugin_route


class HelloPlugin(PluginBase):
    def initialize(self, context):
        """所有插件加载完成后执行一次初始化。"""
        super().initialize(context)

    @plugin_route("GET")
    def greet(self, name: str = "World"):
        return {"message": f"Hello, {name}!"}

    @plugin_route("GET", "/add")
    def add_with_calc(self, a: float = 0, b: float = 0):
        """通过插件上下文调用已经加载的 calc 插件。"""
        return self.context.call("calc", "add", a, b)
```

未指定 `path` 的 `greet` 使用函数名作为路由，最终地址为 `/hello/greet`。`add_with_calc` 指定了自定义路径 `/add`，最终地址为 `/hello/add`。

插件类通常继承 `PluginBase`。框架实例化插件后，会为其设置：

- `self.name`：插件 JSON 配置中声明的插件名称；
- `self.context`：当前 `PluginManager` 实例，可用于访问其他插件。

如果插件不需要额外初始化，可以不重写 `initialize`。如果重写，建议调用 `super().initialize(context)`。

### 4. 使用插件上下文

`PluginManager` 同时承担插件上下文职责，提供以下接口：

```python
# 获取插件实例
calc = self.context.get_plugin("calc")
result = calc.add(1, 2)

# 直接调用插件方法
result = self.context.call("calc", "add", 1, 2)

# 获取所有已加载插件的名称
names = self.context.list_plugins()
```

所有插件会先完成加载，再统一执行 `initialize`，因此可以在初始化阶段或业务方法中访问其他已加载插件。请求不存在的插件会抛出 `KeyError`；调用不存在的方法会抛出 `AttributeError`。

### 5. 配置 HTTP 路由

使用 `plugin_route` 装饰器声明 GET 或 POST 接口：

```python
from core.plugin_base import plugin_route


@plugin_route("GET")
def greet(self, name: str = "World"):
    return {"message": f"Hello, {name}!"}
```

未填写 `path` 时默认使用函数名，因此完整地址为 `/{插件名}/{函数名}`。上例的插件名为 `hello`，最终地址是 `/hello/greet`。简单参数通常来自查询参数。

需要接收 JSON 请求体时，可以使用 Pydantic 模型和 POST 装饰器：

```python
from pydantic import BaseModel

from core.plugin_base import PluginBase, plugin_route


class RepeatRequest(BaseModel):
    text: str
    times: int = 1


class HelloPlugin(PluginBase):
    @plugin_route("POST")
    def repeat(self, data: RepeatRequest):
        return {"text": data.text * data.times}
```

该方法会自动注册为 `POST /hello/repeat`。需要自定义路由时，传入插件内部的相对路径：

```python
@plugin_route("POST", "/repeat-text")
def repeat(self, data: RepeatRequest):
    return {"text": data.text * data.times}
```

自定义后的完整地址为 `POST /hello/repeat-text`。装饰器仅支持 `GET` 和 `POST`，同一个函数也可以叠加多个装饰器。

## 加载流程

应用启动时，`main.py` 依次执行：

1. 创建 `PluginManager` 并指定 `plugins` 目录；
2. 递归发现文件名与所在目录同名的 JSON 插件配置；
3. 跳过 `enabled: false` 的插件，校验依赖是否存在、是否启用以及是否形成循环；
4. 按依赖顺序加载入口模块并实例化自动推导出的插件类；
5. 为全部插件注入上下文，并按依赖顺序调用 `initialize`；
6. 读取插件方法上的路由装饰器并注册 FastAPI 路由，同时自动添加插件名称前缀。

新增插件不需要修改 `main.py` 或 `core` 中的代码。

## 启动和验证

安装依赖后启动应用：

```bash
pip install fastapi uvicorn pydantic
uvicorn main:app --reload
```

启动后可访问：

- `http://127.0.0.1:8000/`：查看已加载插件；
- `http://127.0.0.1:8000/docs`：通过 Swagger UI 查看和调用所有插件路由；
- `POST http://127.0.0.1:8000/text/process-json`：发送 JSON 并返回简单处理结果；
- `http://127.0.0.1:8000/hello/greet?name=Codex`：调用上面的问候示例；
- `http://127.0.0.1:8000/hello/add?a=1&b=2`：验证跨插件调用。

`process-json` 接口请求示例：

```json
{
  "message": "  hello codex  "
}
```

返回结果：

```json
{
  "received": {
    "message": "  hello codex  "
  },
  "result": "HELLO CODEX"
}
```

如果入口文件或推导出的插件类不存在，框架会在加载时抛出异常；依赖缺失、依赖被禁用和循环依赖也会阻止应用启动。无效 JSON 和缺少 `name` 的配置会记录日志并被忽略。
