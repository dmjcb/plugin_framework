# Python 插件化 FastAPI 框架

框架会扫描 `plugins` 下各插件目录中与目录同名的 JSON 配置，按配置动态加载插件、初始化插件，并将插件方法注册为 FastAPI 路由。插件之间可以通过注入的 `context` 获取或调用其他插件。

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
  "version": "1.0.0",
  "description": "问候示例插件",
  "class": "HelloPlugin",
  "routes": {
    "GET": [
      {
        "function": "greet",
        "path": "/"
      },
      {
        "function": "add_with_calc",
        "path": "/add"
      }
    ],
    "POST": []
  }
}
```

`path` 只填写插件内部的相对路径。框架会读取 `name` 并自动添加路径前缀，因此上面的两个 GET 路由最终分别是 `/hello` 和 `/hello/add`。

字段说明：

| 字段 | 是否必需 | 说明 |
| --- | --- | --- |
| `name` | 是 | 插件唯一名称，也是获取插件时使用的名称 |
| `version` | 否 | 插件版本元数据，当前框架不会主动处理 |
| `description` | 否 | 插件说明元数据，当前框架不会主动处理 |
| `entry` | 否 | 自定义入口文件，相对于当前插件目录；省略时使用与目录同名的 `.py` 文件 |
| `class` | 是 | 入口文件中要实例化的插件类名 |
| `routes` | 否 | 按 HTTP 方法划分的路由配置对象 |
| `routes.GET` | 否 | 需要注册为 GET 接口的路由列表 |
| `routes.POST` | 否 | 需要注册为 POST 接口的路由列表 |
| `routes.GET[].function` / `routes.POST[].function` | 是 | 插件类中的可调用方法名 |
| `routes.GET[].path` / `routes.POST[].path` | 是 | 插件内部相对路径，框架会自动添加 `/{name}` 前缀 |

建议确保插件名称和路由路径在整个项目中唯一。

### 3. 实现插件类

创建 `plugins/hello_plugin/hello_plugin.py`：

```python
from core.plugin_base import PluginBase


class HelloPlugin(PluginBase):
    def initialize(self, context):
        """所有插件加载完成后执行一次初始化。"""
        super().initialize(context)

    def greet(self, name: str = "World"):
        return {"message": f"Hello, {name}!"}

    def add_with_calc(self, a: float = 0, b: float = 0):
        """通过插件上下文调用已经加载的 calc 插件。"""
        return self.context.call("calc", "add", a, b)
```

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

只有在 `routes.GET` 或 `routes.POST` 中声明的方法才会注册为 HTTP 接口，不再需要为每个函数填写 `method` 字段。FastAPI 会根据方法签名解析参数：

```python
# GET /hello?name=Codex
def greet(self, name: str = "World"):
    return {"message": f"Hello, {name}!"}
```

简单参数通常来自查询参数。需要接收 JSON 请求体时，可以使用 Pydantic 模型：

```python
from pydantic import BaseModel

from core.plugin_base import PluginBase


class RepeatRequest(BaseModel):
    text: str
    times: int = 1


class HelloPlugin(PluginBase):
    def repeat(self, data: RepeatRequest):
        return {"text": data.text * data.times}
```

在 `hello_plugin.json` 的 `POST` 列表中添加相对路径即可：

```json
{
  "routes": {
    "POST": [
      {
        "function": "repeat",
        "path": "/repeat"
      }
    ]
  }
}
```

由于插件 `name` 是 `hello`，最终接口地址为 `/hello/repeat`。

## 加载流程

应用启动时，`main.py` 依次执行：

1. 创建 `PluginManager` 并指定 `plugins` 目录；
2. 递归发现文件名与所在目录同名的 JSON 插件配置；
3. 加载入口模块并实例化插件类；
4. 为全部插件注入上下文并调用 `initialize`；
5. 根据各插件的 `routes.GET`、`routes.POST` 配置注册 FastAPI 路由，并自动添加插件名称前缀。

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
- `http://127.0.0.1:8000/hello?name=Codex`：调用上面的问候示例；
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

如果入口文件不存在、未配置 `class`、配置的方法不可调用，框架会在加载或注册路由时抛出对应异常；无效 JSON 和缺少 `name` 的配置会记录日志并被忽略。
