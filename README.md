## 插件

### 文件

#### plugin.json

每个插件目录下必须存在 plugin.json

```json
{
  "name": "插件名称，唯一",
  "version": "1.0.0",
  "description": "插件描述",
  "entry": "插件入口 Python 文件名",
  "class": "插件入口文件中的类名",
  "routes": [
    {
      "function": "公开函数名",
      "method": "GET 或 POST",
      "path": "API的URL 路径"
    }
  ]
}
```

#### plugin.py

包含插件的具体实现

```py
class BasePlugin:
    def __init__(self):
        self.name = None
        self.context = None

    def initialize(self, context):
        """所有插件加载后，由 PluginManager 调用"""
        self.context = context

    def shutdown(self):
        pass
```

### 新增

假设需要新增一个 hello 插件：

1. 在 plugins/ 下新建 hello/ 目录

2. 编写 plugin.json；

3. 编写 plugin.py，定义插件类和公开函数；

4. 如有插件间调用，使用 self.context.get_plugin("other_plugin_name")；

5. 启动应用，框架自动发现并注册接口，无需修改核心代码。