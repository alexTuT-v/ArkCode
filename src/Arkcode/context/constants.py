"""上下文管理使用的稳定阈值。"""

# 单条工具结果落盘阈值（UTF-8 字节）。
SINGLE_RESULT_LIMIT = 50000
# 单条工具消息内结果聚合阈值（UTF-8 字节）。
MESSAGE_AGGREGATE_LIMIT = 200000
# 摘要输出预留 token。
SUMMARY_RESERVE = 20000
# 自动压缩安全余量 token。
AUTO_SAFETY_MARGIN = 13000
# 手动与紧急压缩安全余量 token。
MANUAL_SAFETY_MARGIN = 3000
# 恢复段最多保留的文件数。
RECOVERY_FILE_LIMIT = 5
# 恢复段单文件最多估算 token。
RECOVERY_TOKENS_PER_FILE = 5000
# 摘要后近期原文的 token 下界。
RECENT_KEEP_TOKENS = 10000
# 摘要后近期原文的消息数下界。
RECENT_KEEP_MESSAGES = 5
# 自动压缩连续失败熔断阈值。
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES = 3
# 摘要请求过长时逐组丢弃的重试次数。
PTL_RETRY_LIMIT = 3
# 逐组重试后每轮丢弃的剩余分组比例。
PTL_DROP_PERCENTAGE = 0.2
# 无 tokenizer 时采用的字符 token 比。
ESTIMATE_CHARS_PER_TOKEN = 3.5
# 工具结果预览头部最大 UTF-8 字节数。
PREVIEW_HEAD_BYTES = 2048
# 工具结果预览头部最大行数。
PREVIEW_HEAD_LINES = 20
