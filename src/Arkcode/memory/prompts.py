"""长期记忆更新提示。"""

MEMORY_EXTRACTION_SYSTEM_PROMPT = """你负责维护 ArkCode 的长期记忆。
仅保留未来会话仍有价值、稳定且明确的信息。
项目知识和参考资料写入 project；用户偏好和纠正反馈写入 user。
避免重复，已有条目应 update，无价值条目可 delete。
只能返回 JSON 数组，不要 Markdown 或解释。每项格式：
{"action":"create|update|delete","level":"project|user","type":"...","title":"...","slug":"...","content":"...","filename":"..."}
无需更新时返回 []。"""


MEMORY_RECALL_SYSTEM_PROMPT = """你负责从长期记忆清单中选择与当前问题直接相关的条目。
只能返回 JSON 字符串数组，每个字符串必须是清单中已有的 scope:filename key。
最多选择 5 条，按相关性从高到低排列；没有相关内容时返回 []。
不要返回 Markdown、解释、绝对路径或清单之外的 key。"""


MEMORY_CONSOLIDATION_SYSTEM_PROMPT = """你负责周期整理 ArkCode 的长期记忆。
合并语义重复条目，将同一主题的增量信息更新到已有条目，并删除已被明确推翻或失效的内容。
不能确认冲突真伪时保留信息，不要擅自删除。
只能返回 JSON action 数组，格式与自动提取完全相同；无需修改时返回 []。
不要返回 Markdown、解释或文件路径之外的操作。"""
