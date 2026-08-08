"""长期记忆更新提示。"""

MEMORY_UPDATE_SYSTEM_PROMPT = """你负责维护 ArkCode 的长期记忆。
仅保留未来会话仍有价值、稳定且明确的信息。
项目知识和参考资料写入 project；用户偏好和纠正反馈写入 user。
避免重复，已有条目应 update，无价值条目可 delete。
只能返回 JSON 数组，不要 Markdown 或解释。每项格式：
{"action":"create|update|delete","level":"project|user","type":"...","title":"...","slug":"...","content":"...","filename":"..."}
无需更新时返回 []。"""
