from collections import deque
from difflib import SequenceMatcher
import re
import time

def normalize(text):
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text.strip())
    return text

def fingerprint(text):
    return re.sub(r"[\W_]", "", text).lower()

def is_question(text, has_context=False):
    t = normalize(text)
    if has_context and re.fullmatch(r"(那|那么|请)?(继续(解释|说|讲)?|为什么|然后呢|具体(呢|怎么实现)|展开(说说|讲讲)?)[？?。！!]*", t):
        return True
    if len(fingerprint(t)) < 4:
        return False
    patterns = [r"(什么|为何|为什么|如何|怎么|怎样|是否|能否|有没有|多少|哪[个些种里]|区别|优缺点)", r"(请|麻烦)(介绍|解释|说明|分析|比较|谈谈|设计|实现|证明)", r"(吗|么|呢)[？?。]*$"]
    # Do not mistake "我不知道为什么…" / reported questions for direct requests.
    if re.match(r"(我(知道|认为|觉得|不知道)|今天|刚才|他说|她说|谢谢|好的)", t) and not re.search(r"(请问|请你|你能|你觉得)", t):
        return False
    return any(re.search(p, t) for p in patterns) or (len(t) >= 6 and t.endswith(("?", "？")))

class Deduplicator:
    def __init__(self, window=12):
        self.window = window
        self.recent = deque(maxlen=30)

    def duplicate(self, text, now=None):
        now = time.monotonic() if now is None else now
        value = fingerprint(text)
        while self.recent and now - self.recent[0][0] > self.window:
            self.recent.popleft()
        if any(value == old or (min(len(value), len(old)) >= 6 and SequenceMatcher(None, value, old).ratio() >= .88) for _, old in self.recent):
            return True
        self.recent.append((now, value))
        return False

    def clear(self):
        self.recent.clear()
