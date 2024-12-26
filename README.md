# SHU 上海大学抢课助手（2024 新系统）

### 安装与使用

1. **安装 uv (推荐)**

   使用 uv 可以更快速地安装依赖：

   ```sh
   # 安装 uv
   pip install uv

   # 使用 uv 安装依赖
   uv pip install -r requirements.txt
   # 或者
   uv pip install .
   ```

   或者使用传统的 pip 安装：

   ```sh
   pip install requests toml glog selenium
   ```

2. **配置 `config.toml` 文件**

   复制 `config.template.toml` 为 `config.toml`，并根据以下示例填写内容：

   ```toml
   # 基本配置
   use_multithreading = false      # 是否启用多线程
   allow_over_capacity = false     # 是否允许超过容量选课（用于第一轮选课未踢人情况）
   wait_time = 5.0                 # 每次尝试后的等待时间（秒）
   username = ""                   # 你的学号
   password = ""                   # 你的密码
   browser = "chrome"              # 浏览器类型: "chrome", "firefox", 或 "edge"

   # 课程信息列表
   [[courses]]
   KCH = ""                       # 课程号
   JSH = ""                       # 教师号
   priority = 1                   # 优先级，值越低越优先
   ```

3. **运行脚本**

   在命令行中运行脚本：

   ```sh
   python main.py
   ```

### 使用说明

- 脚本会反复查询课程状态，并在有空位时尝试抢课
- 支持多线程抢课（可在配置文件中开启）
- 支持课程优先级设置
- 支持多种浏览器（Chrome、Firefox、Edge）
- 自动处理 token 刷新
- 详细的日志记录（保存在 app.log）

### 开发相关

- 使用 uv 管理依赖，更快速的包管理体验
- 使用 pyproject.toml 管理项目配置
- 支持 pytest 进行测试
- 包含代码覆盖率检查

### 注意事项

- **频率控制**：请勿过于频繁地发送请求，建议使用脚本中的随机延时设置
- **合法使用**：请遵守学校的选课规定，合理使用此脚本
- **风险提示**：使用该脚本存在被学校系统封禁账号的风险，请自行评估并承担相关责任

### 开发环境设置

```sh
# 使用 uv 创建虚拟环境
uv venv

# 激活虚拟环境
# Windows
.venv/Scripts/activate
# Linux/macOS
source .venv/bin/activate

# 安装开发依赖
uv pip install -e ".[dev]"
```

### 运行测试

```sh
pytest
```

### 贡献代码

1. Fork 本仓库
2. 创建您的特性分支
3. 提交您的更改
4. 推送到分支
5. 创建新的 Pull Request

### 许可证

MIT License
