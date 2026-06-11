"""测试用例名规范化单元测试。"""
from qaplatform.domain.services.test_case_normalizer import normalize_case_name


class TestNormalizeCaseName:
    """测试 normalize_case_name 函数。"""

    def test_no_parameters(self):
        """无参数：原样返回。"""
        assert normalize_case_name("test_foo") == "test_foo"
        assert normalize_case_name("test_bar_baz") == "test_bar_baz"

    def test_single_bracket_parameter(self):
        """单个方括号参数：剥离。"""
        assert normalize_case_name("test_foo[param1]") == "test_foo"
        assert normalize_case_name("test_bar[value]") == "test_bar"

    def test_single_paren_parameter(self):
        """单个圆括号参数：剥离。"""
        assert normalize_case_name("test_foo(param1)") == "test_foo"
        assert normalize_case_name("test_bar(value)") == "test_bar"

    def test_multiple_bracket_parameters(self):
        """多个方括号参数：全部剥离。"""
        assert normalize_case_name("test_foo[a][b]") == "test_foo"
        assert normalize_case_name("test_bar[1][2][3]") == "test_bar"

    def test_complex_parameter_values(self):
        """复杂参数值：带连字符、空格、特殊字符。"""
        assert normalize_case_name("test_foo[a-b-c]") == "test_foo"
        assert normalize_case_name("test_bar[param with spaces]") == "test_bar"
        assert normalize_case_name("test_baz[key=value]") == "test_baz"

    def test_nested_brackets_in_parameter(self):
        """参数内嵌套括号：仍正确剥离外层。"""
        assert normalize_case_name("test_foo[list[int]]") == "test_foo"
        assert normalize_case_name("test_bar[(a, b)]") == "test_bar"

    def test_empty_parameters(self):
        """空参数段：剥离。"""
        assert normalize_case_name("test_foo[]") == "test_foo"
        assert normalize_case_name("test_bar()") == "test_bar"

    def test_name_contains_brackets(self):
        """用例名本身包含括号（非参数）：保留。"""
        # 名字中间的括号不是尾部参数，保留
        assert normalize_case_name("test_foo[bar]_baz") == "test_foo[bar]_baz"
        assert normalize_case_name("test(internal)_name") == "test(internal)_name"

    def test_mixed_bracket_types(self):
        """混合括号类型：都剥离。"""
        assert normalize_case_name("test_foo[a](b)") == "test_foo"
        assert normalize_case_name("test_bar(x)[y]") == "test_bar"

    def test_unmatched_brackets(self):
        """不匹配的括号：安全处理。"""
        # 只有尾部闭合括号没有对应开括号时，不剥离
        assert normalize_case_name("test_foo]") == "test_foo]"
        assert normalize_case_name("test_bar)") == "test_bar)"
