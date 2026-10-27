#!/usr/bin/env python3
"""feat-zhtw-locale (§3.3): 派生 zh-TW.json 从 zh-CN.json。

设计取舍
--------
1. **零运行时依赖**：本脚本是 dev-only，不进 Python 运行时依赖图，
   也不要求其它环境装 OpenCC / opencc-python-reimplemented，
   避免增加项目体积 + license 复杂度。
2. **inline 双层替换**：先做高频 GUI 词组替换（从左到右，每个位置取最长命中，
   一趟扫完，替换结果不会被再次扫描），
   再做字符级简-繁映射。词组覆盖了真正影响台湾用户体验的术语
   （设置→設定 / 软件→軟體 / 文件→檔案 / 视频→影片 等），
   字符表覆盖了其余高频 hanzi。
3. **MVP，待 native review**：不是完美翻译。输出的 zh-TW.json 顶部
   会注入 ``_meta.translationNote`` 标注派生来源 + 反馈渠道，
   邀请繁体中文用户走 PR 做 polish（仓库 / 翻译平台都可接受）。
4. **默认合并，不覆盖手改**：zh-TW.json 里已有的译文原样保留，只为缺失的
   key 从 zh-CN 派生；zh-CN 里已不存在的 key 会被删除；key 顺序跟随
   zh-CN；``_meta`` 保留；内容没变就不写文件（重跑 idempotent，也不会
   动 mtime）。``--force`` 才整体重新派生（丢弃全部手改）。

什么时候重跑
------------
- zh-CN.json 新增了 key → 直接跑本脚本（合并模式），zh-TW.json 才会同步
  出现新 key（否则 zh-TW 用户看到的是 fallback 到英文），再复核新派生的译文。
- zh-CN.json 改了某条已有文案 → 脚本不会动 zh-TW 里的旧译文：手改那一条，
  或先把它从 zh-TW.json 删掉再跑脚本重新派生。
- PHRASE_MAP / CHAR_MAP_v2 扩充后只影响之后新派生的 key；要对全部文案生效
  用 ``--force``，并先看 diff（它会覆盖手改）。
- ``--check`` 只报告 zh-TW 相对 zh-CN 缺的 / 多的 key，不写文件，发版清单用它。

后续 native polish
------------------
- 长期方案：维护者可直接 hand-edit zh-TW.json，不必回到 script 端。
  invariant 测试锁定 *存在性*、*schema 同构* 和「不含简体专用字」，不锁定
  具体措辞。
- 如果维护者手改了 zh-TW.json 然后下游又要从 zh-CN 重跑本脚本，
  默认的合并模式会保留手改，只补缺失的 key；``--check`` 只做 schema diff。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


_WEB_LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
_VSCODE_LOCALES_DIR = REPO_ROOT / "packages" / "vscode" / "locales"

_VARIANTS: dict[str, tuple[Path, Path]] = {
    "web": (
        _WEB_LOCALES_DIR / "zh-CN.json",
        _WEB_LOCALES_DIR / "zh-TW.json",
    ),
    "vscode": (
        _VSCODE_LOCALES_DIR / "zh-CN.json",
        _VSCODE_LOCALES_DIR / "zh-TW.json",
    ),
}


LOCALES_DIR = _WEB_LOCALES_DIR
ZH_CN_PATH = _VARIANTS["web"][0]
ZH_TW_PATH = _VARIANTS["web"][1]


PHRASE_MAP: dict[str, str] = {
    "简体中文": "繁體中文",
    "界面语言": "介面語言",
    "界面": "介面",
    "设置": "設定",
    "配置": "設定",
    "软件": "軟體",
    "硬件": "硬體",
    "视频": "影片",
    "音频": "音訊",
    "文件名": "檔名",
    "文件": "檔案",
    "项目": "專案",
    "数据": "資料",
    "网络": "網路",
    "信息": "訊息",
    "信号": "訊號",
    "服务器": "伺服器",
    "服务": "服務",
    "默认": "預設",
    "当前": "目前",
    "保存": "儲存",
    "上传": "上傳",
    "下载": "下載",
    "加载": "載入",
    "复制": "複製",
    "常用回复": "常用回覆",
    "回复": "回覆",
    "恢复": "恢復",
    "重复": "重複",
    "复原": "復原",
    "打开": "打開",
    "影响": "影響",
    "考虑": "考慮",
    "删除": "刪除",
    "状态": "狀態",
    "错误": "錯誤",
    "网络错误": "網路錯誤",
    "异常": "異常",
    "进度": "進度",
    "刷新": "重新整理",
    "刷新页面": "重新整理頁面",
    "退出": "退出",
    "关闭": "關閉",
    "启用": "啟用",
    "禁用": "停用",
    "图片": "圖片",
    "缩放": "縮放",
    "缩略图": "縮圖",
    "图标": "圖示",
    "图像": "影像",
    "标签": "標籤",
    "标准": "標準",
    "目录": "目錄",
    "支持": "支援",
    "选择": "選擇",
    "选项": "選項",
    "选中": "選取",
    "拖放": "拖放",
    "拖拽": "拖曳",
    "下拉": "下拉",
    "下方": "下方",
    "粘贴": "貼上",
    "剪贴板": "剪貼簿",
    "插入": "插入",
    "插入代码": "插入程式碼",
    "代码": "程式碼",
    "代码已插入": "程式碼已插入",
    "字符": "字元",
    "字节": "位元組",
    "页面": "頁面",
    "窗口": "視窗",
    "菜单": "選單",
    "提示语": "提示語",
    "提示": "提示",
    "操作": "操作",
    "操作不可撤销": "操作無法復原",
    "撤销": "復原",
    "确认": "確認",
    "确定": "確定",
    "确认删除": "確認刪除",
    "通知": "通知",
    "推送": "推播",
    "权限": "權限",
    "已授权": "已授權",
    "已拒绝": "已拒絕",
    "拒绝": "拒絕",
    "授权": "授權",
    "请求": "要求",
    "请求超时": "要求逾時",
    "超时": "逾時",
    "立即": "立即",
    "立即重试": "立即重試",
    "重试": "重試",
    "重新": "重新",
    "重新提交": "重新提交",
    "提交": "提交",
    "提交反馈": "提交回饋",
    "反馈": "回饋",
    "反馈内容": "回饋內容",
    "本地": "本機",
    "本地存储": "本機儲存",
    "存储": "儲存空間",
    "本机": "本機",
    "服务端": "伺服器端",
    "客户端": "用戶端",
    "用户": "使用者",
    "登录": "登入",
    "登出": "登出",
    "搜索": "搜尋",
    "查询": "查詢",
    "查找": "尋找",
    "替换": "取代",
    "缓存": "快取",
    "队列": "佇列",
    "句柄": "控制代碼",
    "标识": "識別",
    "实时": "即時",
    "实时更新": "即時更新",
    "断开": "中斷",
    "已断开": "已中斷",
    "连接": "連線",
    "已连接": "已連線",
    "重连": "重新連線",
    "重新连接": "重新連線",
    "正在重连": "正在重新連線",
    "重调": "重新調用",
    "倒计时": "倒數計時",
    "倒计时结束": "倒數結束",
    "自动": "自動",
    "自定义": "自訂",
    "活动": "活動",
    "震动": "震動",
    "声音": "聲音",
    "音量": "音量",
    "音量调节": "音量調節",
    "静音": "靜音",
    "桌面": "桌面",
    "移动": "行動",
    "移动设备": "行動裝置",
    "设备": "裝置",
    "图标URL": "圖示 URL",
    "图标 URL": "圖示 URL",
    "点击": "點擊",
    "双击": "雙擊",
    "右键": "右鍵",
    "回车": "Enter 鍵",
    "换行": "換行",
    "对外": "對外",
    "回环": "回送",
    "网卡": "網路卡",
    "环境": "環境",
    "无法": "無法",
    "未授予": "尚未授予",
    "未开启": "未開啟",
    "未启用": "未啟用",
    "已开启": "已開啟",
    "已关闭": "已關閉",
    "已暂停": "已暫停",
    "暂停": "暫停",
    "暂无": "暫無",
    "运行中": "執行中",
    "运行": "執行",
    "可执行": "可執行",
    "可执行文件": "可執行檔",
    "可疑": "可疑",
    "可选": "選用",
    "可用": "可用",
    "可达": "可達",
    "不可用": "無法使用",
    "不支持": "不支援",
    "不安全": "不安全",
    "无效": "無效",
    "无操作": "無動作",
    "操作不可": "操作無法",
    "处理": "處理",
    "处理中": "處理中",
    "成功": "成功",
    "失败": "失敗",
    "发送": "傳送",
    "发送失败": "傳送失敗",
    "已发送": "已傳送",
    "传输": "傳輸",
    "导出": "匯出",
    "导入": "匯入",
    "合并": "合併",
    "替代": "替代",
    "添加": "新增",
    "新增": "新增",
    "编辑": "編輯",
    "保留": "保留",
    "覆盖": "覆寫",
    "全部": "全部",
    "全部图片": "全部圖片",
    "全部清除": "全部清除",
    "清除": "清除",
    "清除全部": "清除全部",
    "清除所有图片": "清除所有圖片",
    "提供": "提供",
    "应用": "應用",
    "依赖": "相依",
    "属性": "屬性",
    "字段": "欄位",
    "字符串": "字串",
    "整数": "整數",
    "数组": "陣列",
    "对象": "物件",
    "数字": "數字",
    "数量": "數量",
    "范围": "範圍",
    "建议": "建議",
    "推荐": "推薦",
    "样例": "範例",
    "示例": "範例",
    "占位": "預留位置",
    "占位符": "預留位置符",
    "模块": "模組",
    "代码块": "程式碼區塊",
    "记录": "記錄",
    "日志": "日誌",
    "制作": "製作",
    "制造": "製造",
    "条目": "項目",
    "导航": "導覽",
    "栏目": "欄位",
    "切换": "切換",
    "切换主题": "切換主題",
    "主题": "主題",
    "深色": "深色",
    "浅色": "淺色",
    "跟随系统": "跟隨系統",
    "系统": "系統",
    "浏览器": "瀏覽器",
    "原生": "原生",
    "原生通知": "原生通知",
    "降级": "降級",
    "降级方案": "降級方案",
    "回退": "回退",
    "退回": "退回",
    "回退到": "回退至",
    "尚未": "尚未",
    "尚无": "尚無",
    "请输入": "請輸入",
    "请检查": "請檢查",
    "请稍后": "請稍後",
    "请刷新": "請重新整理",
    "请允许": "請允許",
    "请先": "請先",
    "请联系": "請聯繫",
    "提示信息": "提示訊息",
    "导出为": "匯出為",
    "导出文件": "匯出檔案",
    "解析": "解析",
    "压缩": "壓縮",
    "解压": "解壓",
    "构建": "建置",
    "编译": "編譯",
    "运行时": "執行階段",
    "网址": "網址",
    "链接": "連結",
    "短链接": "短網址",
    "对话框": "對話方塊",
    "弹窗": "彈出視窗",
    "面板": "面板",
    "工具栏": "工具列",
    "标题栏": "標題列",
    "侧边栏": "側邊欄",
    "底部": "底部",
    "顶部": "頂端",
    "右上角": "右上角",
    "左上角": "左上角",
    "缺少字段": "缺少欄位",
    "字段必须": "欄位必須",
    "请求体必须": "要求主體必須",
    "请求体": "要求主體",
    "细致": "細緻",
    "赞同": "贊同",
    "赞成": "贊成",
    "赞助": "贊助",
}


CHAR_MAP_v2: dict[str, str] = {
    "冻": "凍",
    "仅": "僅",
    "开": "開",
    "输": "輸",
    "键": "鍵",
    "虑": "慮",
    "许": "許",
    "体": "體",
    "访": "訪",
    "录": "錄",
    "据": "據",
    "贴": "貼",
    "绝": "絕",
    "浏": "瀏",
    "览": "覽",
    "储": "儲",
    "设": "設",
    "择": "擇",
    "写": "寫",
    "发": "發",
    "启": "啟",
    "响": "響",
    "导": "導",
    "张": "張",
    "显": "顯",
    "条": "條",
    "满": "滿",
    "网": "網",
    "获": "獲",
    "该": "該",
    "过": "過",
    "错": "錯",
    "预": "預",
    "变": "變",
    "确": "確",
    "载": "載",
    "频": "頻",
    "检": "檢",
    "个": "個",
    "时": "時",
    "间": "間",
    "问": "問",
    "题": "題",
    "号": "號",
    "块": "塊",
    "馈": "饋",
    "线": "線",
    "无": "無",
    "应": "應",
    "选": "選",
    "联": "聯",
    "处": "處",
    "试": "試",
    "现": "現",
    "运": "運",
    "传": "傳",
    "电": "電",
    "话": "話",
    "听": "聽",
    "见": "見",
    "笔": "筆",
    "约": "約",
    "组": "組",
    "终": "終",
    "结": "結",
    "续": "續",
    "继": "繼",
    "纳": "納",
    "练": "練",
    "罢": "罷",
    "执": "執",
    "挂": "掛",
    "归": "歸",
    "扫": "掃",
    "门": "門",
    "闭": "閉",
    "锁": "鎖",
    "颜": "顏",
    "页": "頁",
    "顺": "順",
    "项": "項",
    "类": "類",
    "队": "隊",
    "决": "決",
    "议": "議",
    "讨": "討",
    "讯": "訊",
    "诊": "診",
    "训": "訓",
    "评": "評",
    "识": "識",
    "证": "證",
    "诉": "訴",
    "诀": "訣",
    "让": "讓",
    "讲": "講",
    "说": "說",
    "读": "讀",
    "课": "課",
    "调": "調",
    "诗": "詩",
    "测": "測",
    "缀": "綴",
    "内": "內",
    "认": "認",
    "诚": "誠",
    "谈": "談",
    "请": "請",
    "诺": "諾",
    "谢": "謝",
    "谁": "誰",
    "语": "語",
    "误": "誤",
    "诵": "誦",
    "谋": "謀",
    "谓": "謂",
    "谚": "諺",
    "谱": "譜",
    "护": "護",
    "举": "舉",
    "买": "買",
    "卖": "賣",
    "团": "團",
    "围": "圍",
    "国": "國",
    "图": "圖",
    "园": "園",
    "区": "區",
    "医": "醫",
    "压": "壓",
    "厌": "厭",
    "厨": "廚",
    "厦": "廈",
    "厢": "廂",
    "历": "歷",
    "厉": "厲",
    "万": "萬",
    "亿": "億",
    "几": "幾",
    "为": "為",
    "余": "餘",
    "舍": "捨",
    "并": "並",
    "迹": "跡",
    "兴": "興",
    "丰": "豐",
    "范": "範",
    "扩": "擴",
    "卢": "盧",
    "炉": "爐",
    "卤": "鹵",
    "随": "隨",
    "险": "險",
    "隐": "隱",
    "雇": "僱",
    "难": "難",
    "霉": "黴",
    "雾": "霧",
    "驱": "驅",
    "驾": "駕",
    "驻": "駐",
    "验": "驗",
    "骏": "駿",
    "骑": "騎",
    "骚": "騷",
    "骤": "驟",
    "骄": "驕",
    "骇": "駭",
    "马": "馬",
    "驴": "驢",
    "鬓": "鬢",
    "饭": "飯",
    "饮": "飲",
    "饱": "飽",
    "饺": "餃",
    "饼": "餅",
    "馆": "館",
    "饿": "餓",
    "馁": "餒",
    "蚀": "蝕",
    "蛮": "蠻",
    "蜡": "蠟",
    "蝉": "蟬",
    "鸢": "鳶",
    "盐": "鹽",
    "盘": "盤",
    "盖": "蓋",
    "盗": "盜",
    "刹": "剎",
    "脸": "臉",
    "丑": "醜",
    "亏": "虧",
    "干": "乾",
    "纸": "紙",
    "墙": "牆",
    "桥": "橋",
    "环": "環",
    "脑": "腦",
    "于": "於",
    "这": "這",
    "里": "裡",
    "后": "後",
    "长": "長",
    "务": "務",
    "数": "數",
    "权": "權",
    "达": "達",
    "转": "轉",
    "划": "劃",
    "灵": "靈",
    "宫": "宮",
    "宁": "寧",
    "宝": "寶",
    "审": "審",
    "宪": "憲",
    "实": "實",
    "宽": "寬",
    "总": "總",
    "爱": "愛",
    "态": "態",
    "动": "動",
    "况": "況",
    "细": "細",
    "辞": "辭",
    "论": "論",
    "辩": "辯",
    "释": "釋",
    "毕": "畢",
    "尽": "盡",
    "贝": "貝",
    "财": "財",
    "贞": "貞",
    "负": "負",
    "贡": "貢",
    "贪": "貪",
    "贫": "貧",
    "贱": "賤",
    "贵": "貴",
    "贸": "貿",
    "费": "費",
    "贺": "賀",
    "贼": "賊",
    "贿": "賄",
    "赁": "賃",
    "资": "資",
    "赋": "賦",
    "赌": "賭",
    "赎": "贖",
    "赏": "賞",
    "赐": "賜",
    "赔": "賠",
    "赖": "賴",
    "赞": "讚",
    "赠": "贈",
    "与": "與",
    "义": "義",
    "从": "從",
    "优": "優",
    "会": "會",
    "伪": "偽",
    "关": "關",
    "则": "則",
    "协": "協",
    "参": "參",
    "吗": "嗎",
    "坏": "壞",
    "将": "將",
    "尝": "嘗",
    "帮": "幫",
    "广": "廣",
    "径": "徑",
    "损": "損",
    "换": "換",
    "断": "斷",
    "暂": "暫",
    "机": "機",
    "来": "來",
    "标": "標",
    "没": "沒",
    "码": "碼",
    "离": "離",
    "筛": "篩",
    "经": "經",
    "绪": "緒",
    "维": "維",
    "装": "裝",
    "触": "觸",
    "详": "詳",
    "轮": "輪",
    "钮": "鈕",
    "铃": "鈴",
    "铛": "鐺",
    "阶": "階",
    "须": "須",
    "么": "麼",
    "云": "雲",
    "价": "價",
    "儿": "兒",
    "党": "黨",
    "厂": "廠",
    "吨": "噸",
    "圣": "聖",
    "夸": "誇",
    "岭": "嶺",
    "异": "異",
    "忏": "懺",
    "怀": "懷",
    "怜": "憐",
    "惊": "驚",
    "愿": "願",
    "扰": "擾",
    "晒": "曬",
    "杰": "傑",
    "极": "極",
    "构": "構",
    "柜": "櫃",
    "气": "氣",
    "种": "種",
    "适": "適",
    "胜": "勝",
    "荐": "薦",
    "虫": "蟲",
    "蚕": "蠶",
    "肮": "骯",
    "业": "業",
    "书": "書",
    "产": "產",
    "偿": "償",
    "势": "勢",
    "员": "員",
    "壳": "殼",
    "宾": "賓",
    "寿": "壽",
    "岁": "歲",
    "扬": "揚",
    "担": "擔",
    "状": "狀",
    "献": "獻",
    "画": "畫",
    "礼": "禮",
    "税": "稅",
    "穷": "窮",
    "罚": "罰",
    "职": "職",
    "节": "節",
    "视": "視",
    "词": "詞",
    "诬": "誣",
    "责": "責",
    "账": "帳",
    "赂": "賂",
    "践": "踐",
    "还": "還",
    "闲": "閒",
    "际": "際",
    "颂": "頌",
    "额": "額",
    "驳": "駁",
    "栏": "欄",
    "静": "靜",
}


def _apply_phrase_map(text: str) -> str:
    """词组替换：从左到右扫描，每个位置取最长命中，一趟完成。

    替换结果不会被再次扫描：输出里含有别的词组、或含有自己源词的词（源文本已写着
    「尚未授予」时，未授予 → 尚未授予 会变成 尚尚未授予）都不会被二次替换。
    """
    lengths = sorted({len(key) for key in PHRASE_MAP if key}, reverse=True)
    out: list[str] = []
    index = 0
    while index < len(text):
        for length in lengths:
            chunk = text[index : index + length]
            if len(chunk) == length and chunk in PHRASE_MAP:
                out.append(PHRASE_MAP[chunk])
                index += length
                break
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def _apply_char_map(text: str) -> str:
    """字符级替换，作为词组之后的兜底（不在 CHAR_MAP 里的字保持原样）。"""
    if not CHAR_MAP_v2:
        return text
    out_chars = []
    for ch in text:
        out_chars.append(CHAR_MAP_v2.get(ch, ch))
    return "".join(out_chars)


def _convert_value(value):
    """递归把 dict / list / str 里的所有字符串转换成繁体。"""
    if isinstance(value, str):
        return _apply_char_map(_apply_phrase_map(value))
    if isinstance(value, dict):
        return {k: _convert_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert_value(v) for v in value]
    return value


_META_KEY = "_meta"
_MISSING = object()


def _default_meta() -> dict:
    """``_meta.translationNote``：注明派生来源并邀请 native review。"""
    return {
        "translationNote": (
            "Auto-derived from zh-CN.json by scripts/gen_zhtw_from_zhcn.py "
            "(feat-zhtw-locale §3.3 MVP). Quality is best-effort; native "
            "zh-TW review welcome via PR to refine specific keys."
        ),
        "derivedFrom": "zh-CN",
        "source": "scripts/gen_zhtw_from_zhcn.py",
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class _MergeReport:
    """合并结果：保留了多少条译文，派生了哪些 key，删除了哪些 key。"""

    kept: int = 0
    derived: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _keeps_existing(source: object, existing: object) -> bool:
    """已有的 zh-TW 值能否顶替 zh-CN 的值（同一种值；list 还要等长）。"""
    if existing is _MISSING or isinstance(source, dict):
        return False
    if isinstance(source, list):
        return isinstance(existing, list) and len(existing) == len(source)
    return type(existing) is type(source)


def _merge_children(
    source: dict, existing: dict, path: str, report: _MergeReport
) -> dict:
    merged = {
        key: _merge_node(value, existing.get(key, _MISSING), _join(path, key), report)
        for key, value in source.items()
    }
    report.dropped.extend(_join(path, key) for key in existing if key not in source)
    return merged


def _merge_node(
    source: object, existing: object, path: str, report: _MergeReport
) -> object:
    if isinstance(source, dict) and isinstance(existing, dict):
        return _merge_children(source, existing, path, report)
    if _keeps_existing(source, existing):
        report.kept += 1
        return existing
    report.derived.append(path)
    return _convert_value(source)


def _parse_existing(path: Path, text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"[ERR] {path} 不是合法 JSON（{exc}）；修复它，或加 --force 整体重新派生")
        raise SystemExit(2) from exc
    if not isinstance(data, dict):
        print(f"[ERR] {path} 顶层不是 JSON 对象；修复它，或加 --force 整体重新派生")
        raise SystemExit(2)
    return data


def _plan(variant: str, *, force: bool) -> tuple[str, _MergeReport, str | None]:
    """算出 ``variant`` 的新 zh-TW 文本与合并报告，不写任何文件。"""
    src_path, dst_path = _VARIANTS[variant]
    if not src_path.is_file():
        print(f"[ERR] source 不存在：{src_path}")
        raise SystemExit(2)
    source = {k: v for k, v in _load_json(src_path).items() if k != _META_KEY}
    old_text = dst_path.read_text(encoding="utf-8") if dst_path.is_file() else None
    existing: dict = {}
    meta = None
    if old_text is not None and not force:
        existing = _parse_existing(dst_path, old_text)
        meta = existing.pop(_META_KEY, None)
    report = _MergeReport()
    tree = {
        _META_KEY: meta if isinstance(meta, dict) else _default_meta(),
        **_merge_children(source, existing, "", report),
    }
    return json.dumps(tree, ensure_ascii=False, indent=2) + "\n", report, old_text


def _generate(variant: str = "web", *, force: bool = False) -> None:
    dst_path = _VARIANTS[variant][1]
    new_text, report, old_text = _plan(variant, force=force)
    if new_text == old_text:
        print(f"[OK] {dst_path} 已是最新 (variant={variant})")
        return
    dst_path.write_text(new_text, encoding="utf-8")
    if force:
        print(f"[OK] wrote {dst_path} (variant={variant}, --force: 全部重新派生)")
        return
    print(
        f"[OK] wrote {dst_path} (variant={variant}): 保留 {report.kept} 条，"
        f"派生 {len(report.derived)} 条，删除 {len(report.dropped)} 条"
    )
    for key in report.derived:
        print(f"  + {key}（由 zh-CN 派生，请复核措辞）")
    for key in report.dropped:
        print(f"  - {key}（zh-CN 里已没有这个 key）")


def _check(variant: str = "web") -> int:
    """schema diff（不写文件）：zh-TW 相对 zh-CN 缺的 / 多的 key，有差异返回 1。"""
    dst_path = _VARIANTS[variant][1]
    if not dst_path.exists():
        print(
            f"[ERR] {dst_path} 不存在；先跑 "
            f"``python scripts/gen_zhtw_from_zhcn.py --variant {variant}``"
        )
        return 1
    _, report, _ = _plan(variant, force=False)
    if report.derived:
        print(f"[WARN] 以下 zh-CN keys 在 zh-TW({variant}) 中缺失或类型不同：")
        for key in report.derived:
            print(f"  - {key}")
    if report.dropped:
        print(f"[WARN] 以下 zh-TW({variant}) keys 在 zh-CN 中已不存在：")
        for key in report.dropped:
            print(f"  - {key}")
    if report.derived or report.dropped:
        return 1
    print(f"[OK] zh-TW.json schema 与 zh-CN.json 同构 (variant={variant})")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Derive zh-TW.json from zh-CN.json. Existing zh-TW text is kept; "
            "only keys missing from zh-TW are derived."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Report keys missing from or extra in zh-TW.json (exit 1 on any); "
            "write nothing"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-derive every string from zh-CN and overwrite zh-TW.json, "
            "discarding hand edits"
        ),
    )
    parser.add_argument(
        "--variant",
        choices=sorted(_VARIANTS.keys()),
        default="web",
        help=(
            "Locale target. 'web' = src/.../static/locales/ (default). "
            "'vscode' = packages/vscode/locales/ (cr32 §3.2 fix, extension's "
            "zh-CN.json → zh-TW.json with the same PHRASE/CHAR mapping)."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate (or --check) all variants in one run.",
    )
    args = parser.parse_args(argv)
    if args.check and args.force:
        parser.error("--check writes nothing, so --force has no meaning with it")

    variants = list(_VARIANTS.keys()) if args.all else [args.variant]

    if args.check:
        rc = 0
        for v in variants:
            rc = _check(v) or rc
        return rc

    for v in variants:
        _generate(v, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
