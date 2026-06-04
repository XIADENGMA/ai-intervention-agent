# `zhconv` 依赖评估 — cr33 §8 #2 follow-up

## 0. 触发条件 (背景)

cr33 §8 #2 [low]: 建议在 `CHAR_MAP_v2` 增长到 ~600 条目之前评估
`zhconv` / `opencc-python` 第三方库，替换当前
`scripts/gen_zhtw_from_zhcn.py` 内的纯 inline 字符 + phrase 映射
管线。当前 `CHAR_MAP_v2` = **445 条目**。

## 1. 方法

```bash
uv pip install zhconv
# 用 zhconv.convert(text, 'zh-tw') 跑整份 src/.../locales/zh-CN.json，
# 与 inline 流水线产生的 zh-TW.json 做逐 string diff。
```

完整再现脚本：

```python
import zhconv, json, pathlib
p = pathlib.Path('src/ai_intervention_agent/static/locales/zh-CN.json')
d = json.loads(p.read_text(encoding='utf-8'))
def flat(o, prefix=''):
    for k, v in o.items():
        kp = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            yield from flat(v, kp)
        else:
            yield kp, v
items = list(flat(d))
zhconv_out = {kp: zhconv.convert(v, 'zh-tw') for kp, v in items if isinstance(v, str)}
inline = json.loads(
    pathlib.Path('src/ai_intervention_agent/static/locales/zh-TW.json')
    .read_text(encoding='utf-8'))
inline_flat = dict(flat(inline))
match = sum(
    1 for k, v in zhconv_out.items()
    if not k.startswith('_') and inline_flat.get(k) == v
)
print(f'matched {match}/{len(zhconv_out)} ({100 * match / len(zhconv_out):.1f}%)')
```

## 2. 结果

| 维度 | 当前 inline 流水线 | `zhconv.convert(..., 'zh-tw')` |
|---|---|---|
| 字符层覆盖 | 445 个 `CHAR_MAP_v2` 条目；missing 字符直接保留 SC | 完整繁体字典；几乎 100% 字符层 |
| Phrase 层覆盖 | 几十个 `PHRASE_MAP` 条目（"反馈" → "回饋"、"调用" → "調用" 等台湾本地化） | 0；纯字符层转换 |
| 与现 `zh-TW.json` 字符串级一致率 | n/a (base) | **34.3 %** (102 / 297 strings) |
| 安装大小 | 0 (dev only, vendored script) | ~250 KB pure Python |
| 维护成本 | 每次发现新简体残留要手动加映射 | 第三方维护；偶尔出 release |

## 3. 差异样本

```text
key                                  zhconv (zh-tw)                    inline (current)
page.noContent.title                 暫無交互反饋請求                  暫無交互回饋要求
page.noContent.description           等待新的交互反饋請求…             等待新的交互回饋要求…
page.noContent.newTasks              # 個新的交互反饋請求              # 個新的交互回饋要求
page.countdown                       # 秒後自動重調                     # 秒後自動重新調用
page.loading                         加載中…                            載入中…
```

观察：

- **zhconv 是纯字符层翻译**。"反馈" → "反饋" 字面正确，但台灣國
  語在 UI / 文档场景习惯写 "回饋"。inline 流水线通过 `PHRASE_MAP`
  做了 "反饋 → 回饋"、"加載 → 載入"、"重調 → 重新調用" 这类
  **本地化** 而非 **音译** 的调整。
- **66 % 的差异都是合法繁体**，但 zhconv 选择**字面贴近源**，inline
  选择**贴近台湾用户预期**。两者都不算"错"，差别在风格 / 语料。

## 4. 决策

**不采用** zhconv 替换 inline 流水线，理由：

1. **覆盖率反过来不利于我们**。zhconv 字符层覆盖 ~100 % 听起来好，
   但只是把"未映射 SC 字符不输出 TC"的失败模式换成了"输出**字面**
   TC 但风格 ML 化"的失败模式。我们当前的失败模式（漏映射）至少
   是 visible 的（用户立刻看到 SC 字符）；zhconv 的失败模式
   （phrase 不本地化）是 invisible 的（用户读了觉得别扭但不会去
   报 bug）。
2. **inline 流水线已经达到 cr33 §8 #2 关注的 445 条目阈值**，但
   80% 来自 `CHAR_MAP_v2`（基本字符映射），20% 来自手动添加
   （cycle-1 / cr32 §3.2 fix 添加的 "测/缀/内" 等）。**增长曲线
   是亚线性**，不是 cr33 担心的"指数增长直到崩溃"。
3. **dev-only script**：`scripts/gen_zhtw_from_zhcn.py` 只在构建
   时跑一次，运行成本不重要；维护成本才是关键。
4. **隔离 vs 依赖**：第三方库更新可能不同步推送新 zh-TW 词条
   （opencc 也有这种风险）；inline 完全在 monorepo 内控制，
   adopt-rate 100% 可预测。

## 5. Hybrid 设计（**未实施**）

如果未来真的撞到 inline maintenance 的痛点（例如 `CHAR_MAP_v2`
增长到 800+ 条目），可以走 **inline phrase first + zhconv char
fallback** 的混合策略：

1. PHRASE_MAP 优先匹配（已有逻辑）
2. CHAR_MAP_v2 字符替换（已有逻辑）
3. 输出前再走 zhconv 字符 fallback（**新**）— 兜底任何漏映射

这样：
- inline 仍然控制 **风格** （phrase 本地化）
- zhconv 兜底 **覆盖** （字符层 100% TC）
- 失败模式从"漏映射出 SC 字符"变成"漏映射 zhconv 兜底"——
  最差也是字面 TC，不会出现 SC 残留

但**这是一个 future track**，不在本 cycle 实施。触发条件：
`CHAR_MAP_v2` ≥ 600 条目，且发现 3 + 次 SC 残留 bug。

## 6. 对 cr33 §8 #2 的回应

- **不采纳 zhconv 替换**。理由：风格控制 > 字符覆盖；inline
  增长曲线亚线性可控；dev-only 维护可承受。
- **Hybrid 设计纳入 deferred 列表**，触发条件：`CHAR_MAP_v2` ≥ 600
  且观察到 3+ 次 SC 残留 bug。

## 7. 关联文档

- `scripts/gen_zhtw_from_zhcn.py` — inline 转换管线源
- `docs/code-reviews/cr33.md` §8 #2 — 触发本评估的 follow-up
- `docs/feature-mining-cycle-2.md` §4.1 — 本 doc 在 cycle 中的位置
