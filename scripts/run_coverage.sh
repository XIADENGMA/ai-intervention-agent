#!/bin/bash
# 运行测试并生成覆盖率报告
# 使用方法: ./scripts/run_coverage.sh [options]
# 选项:
#   --html    生成 HTML 报告
#   --xml     生成 XML 报告
#   --open    自动打开 HTML 报告

set -e

cd "$(dirname "$0")/.."

echo "🧪 运行测试并收集覆盖率..."
echo ""

# 默认选项
HTML_REPORT=false
XML_REPORT=false
OPEN_REPORT=false

# 解析命令行参数
for arg in "$@"; do
    case $arg in
        --html)
            HTML_REPORT=true
            ;;
        --xml)
            XML_REPORT=true
            ;;
        --open)
            OPEN_REPORT=true
            HTML_REPORT=true
            ;;
    esac
done

# 运行测试并收集覆盖率
uv run pytest tests/ \
    --cov=. \
    --cov-report=term-missing \
    --cov-config=.coveragerc \
    -v

# 生成 HTML 报告
if [ "$HTML_REPORT" = true ]; then
    echo ""
    echo "📊 生成 HTML 覆盖率报告..."
    uv run coverage html
    echo "✅ HTML 报告已生成: htmlcov/index.html"

    # 自动打开报告
    if [ "$OPEN_REPORT" = true ]; then
        if command -v xdg-open &> /dev/null; then
            xdg-open htmlcov/index.html
        elif command -v open &> /dev/null; then
            open htmlcov/index.html
        fi
    fi
fi

# 生成 XML 报告
if [ "$XML_REPORT" = true ]; then
    echo ""
    echo "📊 生成 XML 覆盖率报告..."
    uv run coverage xml
    echo "✅ XML 报告已生成: coverage.xml"
fi

echo ""
echo "🎉 测试完成！"
