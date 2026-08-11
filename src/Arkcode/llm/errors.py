"""跨 Provider 共用的稳定异常类型。"""


class PromptTooLongError(Exception):
    """Provider 上报上下文超出窗口时统一使用的哨兵异常。"""
