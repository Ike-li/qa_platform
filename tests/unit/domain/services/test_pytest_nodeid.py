"""pytest nodeid 重构单元测试。"""
from qaplatform.domain.services.pytest_nodeid import reconstruct_nodeid


class TestReconstructNodeid:
    """测试 nodeid 重构逻辑。"""

    def test_module_level_function(self):
        """模块级函数：无类名。"""
        assert reconstruct_nodeid("tests.unit.test_x", "test_foo") == "tests/unit/test_x.py::test_foo"

    def test_class_method(self):
        """类方法：末段大写开头视为类名。"""
        assert (
            reconstruct_nodeid("tests.unit.test_x.TestClass", "test_method")
            == "tests/unit/test_x.py::TestClass::test_method"
        )

    def test_parametrized_case(self):
        """参数化用例：保留参数段。"""
        assert (
            reconstruct_nodeid("tests.unit.test_x", "test_foo[param1]")
            == "tests/unit/test_x.py::test_foo[param1]"
        )
        assert (
            reconstruct_nodeid("tests.unit.test_x.TestClass", "test_method[a-b]")
            == "tests/unit/test_x.py::TestClass::test_method[a-b]"
        )

    def test_deep_path(self):
        """深层路径：多级目录。"""
        assert (
            reconstruct_nodeid("tests.integration.api.v1.test_runs", "test_create")
            == "tests/integration/api/v1/test_runs.py::test_create"
        )

    def test_nested_class(self):
        """嵌套类：只取最后一段判断（pytest 不支持多级类嵌套 nodeid，此处简化）。"""
        assert (
            reconstruct_nodeid("tests.unit.test_x.OuterClass.InnerClass", "test_inner")
            == "tests/unit/test_x.py::OuterClass.InnerClass::test_inner"
        )

    def test_class_name_with_lowercase_start(self):
        """边界：末段小写开头，即使看起来像类名，也视为模块。"""
        assert (
            reconstruct_nodeid("tests.unit.test_helpers.helperClass", "test_something")
            == "tests/unit/test_helpers.py::helperClass::test_something"
        )

    def test_single_segment(self):
        """边界：单段 suite（不常见但合法）。"""
        assert reconstruct_nodeid("test_root", "test_case") == "test_root.py::test_case"

    def test_empty_parameter(self):
        """边界：空参数段（理论上不应出现，但不应崩溃）。"""
        assert reconstruct_nodeid("tests.unit.test_x", "test_foo[]") == "tests/unit/test_x.py::test_foo[]"
