"""Tests for the evaluation engine."""

import pytest

from sparktutor.engine.evaluator import Evaluator, EvalResult, FeedbackItem
from sparktutor.engine.normalizer import choices_match, code_match, normalize_code


class TestNormalizer:
    def test_choices_match_exact(self):
        assert choices_match("getOrCreate()", "getOrCreate()")

    def test_choices_match_case_insensitive(self):
        assert choices_match("getorcreate()", "getOrCreate()")

    def test_choices_no_match(self):
        assert not choices_match("create()", "getOrCreate()")

    def test_code_match_quotes(self):
        assert code_match('x = "hello"', "x = 'hello'")

    def test_code_match_whitespace(self):
        assert code_match("x  =  42", "x = 42")

    def test_code_no_match(self):
        assert not code_match("x = 42", "x = 43")

    def test_normalize_code(self):
        assert normalize_code("  x  =  42  ") == "x = 42"


class TestEvaluator:
    @pytest.fixture
    def evaluator(self):
        return Evaluator()

    def test_syntax_check_valid(self, evaluator):
        result = evaluator.check_syntax("x = 42")
        assert result.passed

    def test_syntax_check_invalid(self, evaluator):
        result = evaluator.check_syntax("x = ")
        assert not result.passed
        assert result.feedback[0].severity == "error"
        assert result.feedback[0].line is not None

    def test_mult_choice_correct(self, evaluator):
        result = evaluator.check_mult_choice("getOrCreate()", "getOrCreate()")
        assert result.passed

    def test_mult_choice_wrong(self, evaluator):
        result = evaluator.check_mult_choice("create()", "getOrCreate()")
        assert not result.passed

    def test_code_exact_match(self, evaluator):
        result = evaluator.check_code_exact("x = 42", "x = 42")
        assert result.passed

    def test_ast_contains_class(self, evaluator):
        code = "class Pipeline:\n    pass"
        result = evaluator.check_ast_contains(code, [{"expr": "ast_contains(class_def='Pipeline')"}])
        assert result.passed

    def test_ast_contains_missing_class(self, evaluator):
        code = "x = 42"
        result = evaluator.check_ast_contains(code, [{"expr": "ast_contains(class_def='Pipeline')"}])
        assert not result.passed
        assert any("Pipeline" in f.message for f in result.feedback)

    def test_ast_contains_method(self, evaluator):
        code = "class Foo:\n    def __init__(self):\n        pass"
        result = evaluator.check_ast_contains(code, [{"expr": "ast_contains(method='__init__')"}])
        assert result.passed

    def test_ast_contains_syntax_error(self, evaluator):
        result = evaluator.check_ast_contains("def (:", [{"expr": "ast_contains(function='foo')"}])
        assert not result.passed
        assert result.feedback[0].severity == "error"
