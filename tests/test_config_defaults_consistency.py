import tempfile
import unittest
from pathlib import Path


class TestConfigDefaultsConsistency(unittest.TestCase):
    """防回归：默认配置字典应与模板 config.jsonc.default 的键保持一致。

    说明：
    - 真实默认配置文件优先从模板复制生成，但 `_get_default_config()` 是关键回退路径；
      一旦两者漂移，会出现“边界场景下默认值/字段名不一致”的问题。
    - 这里仅校验 **键集合一致性**，不强行约束默认值本身（值可能因安全策略调整而变化）。
    """

    def test_default_config_keys_match_template(self):
        from config_manager import ConfigManager, parse_jsonc

        repo_root = Path(__file__).resolve().parents[1]
        template_path = repo_root / "config.jsonc.default"
        self.assertTrue(template_path.exists(), f"missing template: {template_path}")

        template = parse_jsonc(template_path.read_text(encoding="utf-8"))
        self.assertIsInstance(template, dict)

        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.jsonc"
            mgr = ConfigManager(str(cfg_path))
            defaults = mgr._get_default_config()

        self.assertEqual(set(defaults.keys()), set(template.keys()))

        for section in sorted(defaults.keys()):
            self.assertIsInstance(
                defaults[section], dict, f"defaults[{section}] should be dict"
            )
            self.assertIsInstance(
                template[section], dict, f"template[{section}] should be dict"
            )
            self.assertEqual(
                set(defaults[section].keys()),
                set(template[section].keys()),
                f"section keys mismatch: {section}",
            )
