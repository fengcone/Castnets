"""A deliberately small deterministic draft provider, NOT a general language model."""
from typing import Protocol

from .models import Answer, Context, Source

GLOSSARY = [
    (("rwa", "真实世界资产"), "RWA", "RWA 是真实世界资产的缩写。在区块链语境里，通常指把现实资产的某些权利或凭证用链上的代币表示；链上凭证是否真有相应权利，还取决于具体安排。"),
    (("beta", "β", "贝塔"), "β / Beta", "Beta 常用来描述资产收益对市场变动的敏感程度。口语里说跟着 Beta，往往是在说参与市场整体带来的涨跌。"),
    (("alpha", "α", "阿尔法"), "α / Alpha", "Alpha 通常指相对于选定基准或风险模型的超额收益；生活里的 Alpha 则是一种借用这个词的比喻，并不是严格的财务指标。"),
    (("机会成本",), "机会成本", "机会成本是做一个选择时，放弃的最佳替代选择的价值。比如花一小时听节目，这一小时原本可以用来做的最有价值的事，就是比较时要考虑的机会成本。"),
]


class AnswerProvider(Protocol):
    def answer(self, question: str, context: Context) -> Answer: ...


class MockProvider:
    def answer(self, question: str, context: Context) -> Answer:
        found = [(term, explanation) for aliases, term, explanation in GLOSSARY
                 if any(alias in question.lower() for alias in aliases)]
        evidence = ([context.chapter] if context.chapter else []) + context.timed_segments + context.related_unaligned
        sources = []
        for segment in evidence:
            if segment.source not in sources:
                sources.append(segment.source)
        chapter_hint = f"当前位置对应章节「{context.chapter.text}」。" if context.chapter else "当前位置没有可用章节。"
        if found:
            sources.append(Source("demo_glossary", "urn:castnets:demo-glossary:v1",
                                  "本地人工编写的演示释义，非嘉宾原话，非实时模型回答。", "not_applicable"))
            spoken = "这是演示释义。" + " ".join(explanation for _, explanation in found)
            short = {"RWA": "现实资产的权利或凭证在链上的表示。", "β / Beta": "相对市场变动的敏感程度。",
                     "α / Alpha": "相对基准或风险模型的超额收益。", "机会成本": "被放弃的最佳替代选择的价值。"}
            summary = [f"{term}：{short[term]}" for term, _ in found][:2]
            summary.append("通用概念说明；本期具体语境需要核对原音频。")
            confidence = "draft"
        else:
            spoken = "当前是离线演示模式，我还不能可靠地回答这个问题。" + chapter_hint + "可以先回听几秒核对原话；接入模型后再生成解释。"
            summary = ["未生成实质解释：离线词表未覆盖这个问题。", chapter_hint]
            confidence = "insufficient_context"
        if context.precision != "timed":
            spoken += "我还没有这一秒的逐句转写，所以不能确定嘉宾刚才的具体意思。"
        return Answer(spoken, summary[:3], [term for term, _ in found],
                      list(dict.fromkeys(source.kind for source in sources)), sources,
                      "我们回到刚才的节目，从前面几秒接着听。", "mock", confidence,
                      ["M0 只验证结构化支线闭环；词表不会理解任意问题或连续对话。",
                       "sources 列出上下文和演示释义来源，不表示逐字稿支持该通用解释。", *context.warnings])
