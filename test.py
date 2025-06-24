#!/usr/bin/env python3
"""
AI Intervention Agent 智能介入代理测试工具
"""

import os
import sys
import threading
import time

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def check_service(url, timeout=5):
    """检查服务是否可用"""
    try:
        import requests

        response = requests.get(url, timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def test_config_validation():
    """测试配置验证功能"""
    print("🔧 测试配置验证...")

    try:
        from server import get_web_ui_config, validate_input

        # 测试正常配置
        config = get_web_ui_config()
        print(f"✅ 配置加载成功: {config.host}:{config.port}")

        # 测试输入验证
        prompt, options = validate_input("测试消息", ["选项1", "选项2"])
        print(f"✅ 输入验证成功: prompt='{prompt[:20]}...', options={len(options)}个")

        # 测试异常输入
        try:
            validate_input("", None)
            print("✅ 空输入处理正常")
        except Exception as e:
            print(f"⚠️ 空输入处理异常: {e}")

        return True

    except Exception as e:
        print(f"❌ 配置验证测试失败: {e}")
        return False


def test_service_health():
    """测试服务健康检查"""
    print("🏥 测试服务健康检查...")

    try:
        from server import (
            get_web_ui_config,
            health_check_service,
            is_web_service_running,
        )

        config = get_web_ui_config()

        # 测试端口检查
        is_running = is_web_service_running(config.host, config.port)
        print(f"✅ 端口检查完成: {'运行中' if is_running else '未运行'}")

        # 测试健康检查
        if is_running:
            is_healthy = health_check_service(config)
            print(f"✅ 健康检查完成: {'健康' if is_healthy else '不健康'}")
        else:
            print("ℹ️ 服务未运行，跳过健康检查")

        return True

    except Exception as e:
        print(f"❌ 服务健康检查测试失败: {e}")
        return False


def test_persistent_workflow():
    """测试智能介入工作流程"""
    print("🔄 测试智能介入工作流程...")

    try:
        from server import get_web_ui_config, launch_feedback_ui

        config = get_web_ui_config()
        service_url = f"http://localhost:{config.port}/api/config"

        # 第一次调用 - 启动服务
        print("🚀 启动介入服务...")
        prompt1 = """
        # 你好，我是AI Intervention Agent
**一个让用户能够实时控制 AI 执行过程的 MCP 工具。**

支持`Cursor`、`Vscode`、`Claude Code`、`Augment`、`Windsurf`、`Trae`等 AI 工具。"""
        options1 = [
            "🔄 继续了解",
            "✅ 立刻开始",
        ]  # "✅ 服务正常", "🔄 准备第二次测试", "📊 查看详细信息"

        result1 = None

        def run_first():
            nonlocal result1
            try:
                result1 = launch_feedback_ui(prompt1, options1)
            except Exception as e:
                print(f"❌ 第一次调用失败: {e}")

        thread1 = threading.Thread(target=run_first)
        thread1.start()

        # 等待服务启动并检查
        print("⏳ 等待服务启动...")
        time.sleep(5)
        if not check_service(service_url):
            print("❌ 服务启动失败")
            return False

        print("✅ 服务启动成功，请在浏览器中提交反馈")
        print(f"🌐 浏览器地址: http://localhost:{config.port}")
        thread1.join(timeout=300)

        if result1:
            print(f"✅ 第一次反馈: {result1}")
        else:
            print("⚠️ 第一次反馈超时")
            return False

        # 第二次调用 - 更新内容
        print("🔄 更新页面内容...")
        prompt2 = """# 🎉 内容已更新！- 第二次调用

## 更新内容验证

恭喜！第一次测试已完成。现在进行 **内容动态更新** 测试。

### 新增功能测试

#### 1. 表格渲染测试
| 功能 | 状态 | 备注 |
|------|------|------|
| 服务启动 | ✅ 完成 | 第一次测试通过 |
| Markdown渲染 | 🧪 测试中 | 当前正在验证 |
| 内容更新 | 🔄 进行中 | 动态更新功能 |

#### 2. 任务列表测试
**已完成任务：**
* ✅ 服务启动验证
* ✅ 基础渲染测试
* ✅ 用户交互测试

**进行中任务：**
* 🔄 高级渲染测试
* 🔄 内容更新验证

**待完成任务：**
* ⏳ 性能测试
* ⏳ 错误处理测试

#### 3. 文本格式测试
支持的 Markdown 元素：
- **粗体文本**
- *斜体文本*
- `行内代码`
- ~~删除线~~
- [链接示例](https://example.com)

#### 4. 引用和高级代码块
> 💡 **提示**: 这是一个引用块，用于显示重要信息。
>
> 支持多行引用内容，可以包含 **格式化文本** 和 `代码`。

```javascript
/**
 * AI Intervention Agent - 内容更新模块
 * 用于动态更新页面内容和收集用户反馈
 */
class ContentUpdater {
    constructor(config) {
        this.config = config;
        this.updateCount = 0;
    }

    /**
     * 更新页面内容
     * @param {string} newContent - 新的内容
     * @param {Array} options - 用户选项
     * @returns {Promise<Object>} 更新结果
     */
    async updateContent(newContent, options) {
        try {
            this.updateCount++;
            console.log(`第 ${this.updateCount} 次内容更新`);

            // 模拟异步更新
            await new Promise(resolve => setTimeout(resolve, 100));

            return {
                success: true,
                content: newContent,
                options: options,
                timestamp: new Date().toISOString(),
                updateId: this.updateCount
            };
        } catch (error) {
            console.error("内容更新失败:", error);
            return { success: false, error: error.message };
        }
    }
}

// 使用示例
const updater = new ContentUpdater({ debug: true });
updater.updateContent("测试内容", ["选项1", "选项2"])
    .then(result => console.log("更新结果:", result));
```

#### 5. 数学公式测试（如果支持）
内联公式：$E = mc^2$

块级公式：
$$
\\sum_{i=1}^{n} x_i = x_1 + x_2 + \\cdots + x_n
$$

---

### 🎯 最终测试
请选择一个选项来完成测试流程："""
        options2 = ["🎉 内容更新成功", "✅ 测试完成"]

        result2 = launch_feedback_ui(prompt2, options2)

        if result2:
            print(f"✅ 第二次反馈: {result2}")
            print("🎉 智能介入测试完成！")
            return True
        else:
            print("⚠️ 第二次反馈失败")
            return False

    except Exception as e:
        print(f"❌ 智能介入测试失败: {e}")
        return False


def main():
    """主测试函数"""
    print("🧪 AI Intervention Agent 智能介入代理测试")
    print("=" * 50)

    # 运行所有测试
    tests = [
        ("配置验证", test_config_validation),
        ("服务健康检查", test_service_health),
        ("智能介入工作流程", test_persistent_workflow),
    ]

    results = []

    for test_name, test_func in tests:
        print(f"\n🧪 运行测试: {test_name}")
        print("-" * 30)

        try:
            success = test_func()
            results.append((test_name, success))

            if success:
                print(f"✅ {test_name} 测试通过")
            else:
                print(f"❌ {test_name} 测试失败")

        except KeyboardInterrupt:
            print(f"\n👋 {test_name} 测试被中断")
            break
        except Exception as e:
            print(f"❌ {test_name} 测试出错: {e}")
            results.append((test_name, False))

    # 显示测试结果摘要
    print("\n" + "=" * 50)
    print("📊 测试结果摘要:")

    passed = 0
    total = len(results)

    for test_name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"   {test_name}: {status}")
        if success:
            passed += 1

    print(f"\n📈 总体结果: {passed}/{total} 测试通过")

    if passed == total:
        print("🎉 所有测试都通过了！")
    else:
        print("⚠️ 部分测试失败，请检查日志")

    return passed == total


if __name__ == "__main__":
    main()
