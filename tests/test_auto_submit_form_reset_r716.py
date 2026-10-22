"""R716 回归护栏：倒计时自动提交成功后必须像手动提交一样重置表单（文本框 + 图片）。

背景：

Web UI 的手动提交（``app.js`` 的 ``submitFeedback``）在成功后清空文本框、图片并取消勾选，
VS Code webview 的 ``submitWithData``（手动 / 自动提交共用）同理。唯独 Web UI 的自动提交
（``multi_task.js`` 的 ``submitTaskFeedback``）成功后只删除内存里保存的草稿，**没有**清理
屏幕上的表单。结果：

- 用户输入了文字 / 贴了图，倒计时归零自动提交 → 文本框和图片仍留在屏幕上；
- 下一个任务到来时，``collectTypedFeedbackForTask`` 读到文本框里的旧文字，下一次自动提交
  把「上一个任务的回复」又发给 AI 一遍（带着旧图片）。

契约：

- 自动提交成功且提交的就是当前活动任务 → 清空文本框并释放图片列表（与手动提交一致）。
- 提交的不是当前活动任务（用户已切到别的标签）→ 不碰屏幕上属于别的任务的表单。
- 提交失败（``success: false`` / 网络异常）→ 文本和图片原样保留，不丢用户内容。
- VS Code webview 的提交成功路径同样重置表单（跨端一致性护栏）。
"""

from __future__ import annotations

import json
import unittest

from tests.test_auto_submit_recommended_options_r715 import (
    _vscode_source,
    _web_source,
)
from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    _node_available,
    _poll_harness,
    _run_node,
)
from tests.test_multi_task_tab_active_sync_loop_r610 import _extract_function_body
from tests.test_vscode_task_local_cache_prune_r452 import _extract_function

WEB_PRELUDE = """
FormData = class {
  constructor() { this.entries = []; }
  append(key, value) { this.entries.push([key, value]); }
};
const textarea = { value: '' };
document.getElementById = (id) => (id === 'feedback-text' ? textarea : null);
let clearedImages = 0;
clearAllImages = () => { clearedImages += 1; selectedImages = []; };
const requests = [];
let nextResponse = { success: true };
let failNetwork = false;
fetchWithTimeout = async (url, init) => {
  requests.push({ url, entries: init.body.entries });
  if (failNetwork) throw new Error('network down');
  return { json: async () => nextResponse };
};
fetchFeedbackPromptsFresh = async () => ({ resubmit_prompt: 'RESUBMIT' });

function fieldOf(request, key) {
  const hit = request.entries.find((entry) => entry[0] === key);
  return hit ? hit[1] : null;
}

function imageKeysOf(request) {
  return request.entries.filter((entry) => entry[0].startsWith('image_')).map((entry) => entry[1]);
}
"""


def _run(case_js: str) -> dict:
    return json.loads(_run_node(_poll_harness(WEB_PRELUDE + case_js)))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWebAutoSubmitResetsForm(unittest.TestCase):
    def test_successful_submit_of_the_active_task_clears_text_and_images(self) -> None:
        result = _run(
            """
            activeTaskId = 't1';
            taskTextareaContents.t1 = 'typed text';
            textarea.value = 'typed text';
            selectedImages = [{ file: 'IMG-1' }];
            await submitTaskFeedback('t1', 'typed text', []);
            process.stdout.write(JSON.stringify({
              text: textarea.value,
              clearedImages,
              imagesLeft: selectedImages.length,
              savedText: taskTextareaContents.t1 === undefined,
              requests: requests.length,
            }));
            """
        )
        self.assertEqual(result["text"], "")
        self.assertEqual(result["clearedImages"], 1)
        self.assertEqual(result["imagesLeft"], 0)
        self.assertTrue(result["savedText"])
        self.assertEqual(result["requests"], 1)

    def test_submit_of_another_task_leaves_the_live_form_alone(self) -> None:
        result = _run(
            """
            activeTaskId = 't2';
            textarea.value = 'draft for t2';
            selectedImages = [{ file: 'IMG-T2' }];
            await submitTaskFeedback('t1', 'resubmit', []);
            process.stdout.write(JSON.stringify({
              text: textarea.value,
              clearedImages,
              imagesLeft: selectedImages.length,
            }));
            """
        )
        self.assertEqual(result["text"], "draft for t2")
        self.assertEqual(result["clearedImages"], 0)
        self.assertEqual(result["imagesLeft"], 1)

    def test_rejected_submit_keeps_text_and_images(self) -> None:
        result = _run(
            """
            activeTaskId = 't1';
            textarea.value = 'typed text';
            selectedImages = [{ file: 'IMG-1' }];
            nextResponse = { success: false, error: 'nope' };
            await submitTaskFeedback('t1', 'typed text', []);
            process.stdout.write(JSON.stringify({
              text: textarea.value,
              clearedImages,
              imagesLeft: selectedImages.length,
            }));
            """
        )
        self.assertEqual(result["text"], "typed text")
        self.assertEqual(result["clearedImages"], 0)
        self.assertEqual(result["imagesLeft"], 1)

    def test_network_failure_keeps_text_and_images(self) -> None:
        result = _run(
            """
            activeTaskId = 't1';
            textarea.value = 'typed text';
            selectedImages = [{ file: 'IMG-1' }];
            failNetwork = true;
            await submitTaskFeedback('t1', 'typed text', []);
            process.stdout.write(JSON.stringify({
              text: textarea.value,
              clearedImages,
              imagesLeft: selectedImages.length,
            }));
            """
        )
        self.assertEqual(result["text"], "typed text")
        self.assertEqual(result["clearedImages"], 0)
        self.assertEqual(result["imagesLeft"], 1)

    def test_submit_without_images_does_not_touch_the_image_list(self) -> None:
        result = _run(
            """
            activeTaskId = 't1';
            textarea.value = 'typed text';
            selectedImages = [];
            await submitTaskFeedback('t1', 'typed text', []);
            process.stdout.write(JSON.stringify({ text: textarea.value, clearedImages }));
            """
        )
        self.assertEqual(result["text"], "")
        self.assertEqual(result["clearedImages"], 0)

    def test_next_task_auto_submit_does_not_resend_the_previous_reply(self) -> None:
        result = _run(
            """
            window.currentTasks = [{ task_id: 't1' }, { task_id: 't2' }];
            activeTaskId = 't1';
            textarea.value = 'first reply';
            selectedImages = [{ file: 'IMG-1' }];
            await autoSubmitTask('t1');

            activeTaskId = 't2';
            await autoSubmitTask('t2');

            process.stdout.write(JSON.stringify({
              first: {
                url: requests[0].url,
                text: fieldOf(requests[0], 'feedback_text'),
                images: imageKeysOf(requests[0]),
              },
              second: {
                url: requests[1].url,
                text: fieldOf(requests[1], 'feedback_text'),
                images: imageKeysOf(requests[1]),
              },
            }));
            """
        )
        self.assertEqual(
            result["first"],
            {
                "url": "/api/tasks/t1/submit",
                "text": "first reply",
                "images": ["IMG-1"],
            },
        )
        self.assertEqual(
            result["second"],
            {"url": "/api/tasks/t2/submit", "text": "RESUBMIT", "images": []},
        )


class TestSourceContract(unittest.TestCase):
    def test_web_submit_success_resets_the_live_form_for_the_active_task(self) -> None:
        body = _extract_function_body(_web_source(), "submitTaskFeedback")
        self.assertIn("taskId === activeTaskId", body)
        self.assertIn('getElementById("feedback-text")', body)
        self.assertIn("clearAllImages", body)

    def test_vscode_submit_success_resets_text_images_and_options(self) -> None:
        source = _vscode_source()
        # The success branch lives in ``finishSuccessfulSubmit`` (taken out of the
        # 253-line ``submitWithData``); the submit path must still end in it.
        self.assertIn(
            "return finishSuccessfulSubmit(",
            _extract_function(source, "submitWithData"),
        )
        body = _extract_function(source, "finishSuccessfulSubmit")
        self.assertIn("textarea.value = ''", body)
        self.assertIn("uploadedImages = []", body)
        self.assertIn("checkbox.checked = false", body)


if __name__ == "__main__":
    unittest.main()
