# -*- coding: utf-8 -*-
"""卷帙清洗逻辑：真机语料回归 + Python / Web 一致性校验。

覆盖那个真实用户反馈的问题：盗版站把网址直接粘在段落末尾，
旧逻辑按整行删除，会把整本书的正文一起删光。

用法（在 Juanzhi/ 下）：
    python tools/test_clean_parity.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jzcore  # noqa: E402

RULES = ["url", "site", "nav", "trim", "blank2"]

# —— 真实语料：全部是盗版 TXT 里常见的形态 ——
PARA = ("她听我分析的头头是道，目光里写满了敬佩，等我说完后，歪着头看着桌上那把枪喃喃自语说："
        "“这把枪怎么很面熟？”她忽然意识到了什么，双手拍拍腰上，“嗷”地叫了一声，"
        "冲过来一把夺走了手枪，瞪着我问：“你什么时候偷走的？”")
CORPUS = "\n".join([
    "阴阳鬼探",
    "",
    "第一章　凶宅",
    "",
    PARA + "WwW.zhudao.com",
    "zhudao.com 【猪猪岛】小说章节更新最快",
    "一秒记住【猪猪岛】手机版阅读网址：m.zhudao.com",
    "“你刚才倒下的时候。”",
    "把客人请到屋里坐下，倒了杯热茶。",
    "你上百度搜索一下就知道我说的是真的。",
    "他去过很多地方，比如那个叫 www.example.com 的站子，后来也走了很久很久才回来，"
    "路上的风景很好，天上的云很低，他一直记着那句话，说要好好活着。",
    "我嘿嘿一笑：“我不是鬼，以前当过兵，对于武器什么的颇为了解。”说着站起身，"
    "比划着关保险的动作WwW.zhudao.com",
    "他点开 www.zhudao.com 看了一眼，又关掉了。",
    "www.zhudao.com",
    "http://www.xxx.net 小说下载网，TXT下载请到本站。",
    "www.zhudao.com 我常去逛的站子，里面什么都有，还能看连载。",
    "上一页　下一页",
    "第１２章　夜路",
    "",
])

EXPECT = [
    ("长段落保住，只裁网址", PARA in CORPUS),        # 由下面对输出做断言
]


def run_python(text):
    st = {}
    out, removed = jzcore.clean_text(text, RULES, st)
    return {"text": out, "removed": removed, "trimmed": st.get("trimmed", 0)}


def run_web(text):
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    fd, tmp = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        io.open(tmp, "w", encoding="utf-8", newline="").write(text)
        r = subprocess.run(
            ["node", os.path.join(here, "_dump_clean.mjs"), tmp, json.dumps(RULES)],
            capture_output=True, cwd=root,
        )
        if r.returncode != 0:
            raise SystemExit("node 执行失败：" + r.stderr.decode("utf-8", "ignore")[:400])
        return json.loads(r.stdout.decode("utf-8"))
    finally:
        os.remove(tmp)


def main():
    ok = fail = 0

    def chk(name, cond, detail=None):
        nonlocal ok, fail
        if cond:
            ok += 1
            print("  OK   " + name)
        else:
            fail += 1
            print("  FAIL " + name + ("  | " + repr(detail) if detail is not None else ""))

    py = run_python(CORPUS)
    web = run_web(CORPUS)
    text = py["text"]
    lines = text.split("\n")

    print("== 正文是否被洗干净 ==")
    chk("长段落完整保留", PARA in text)
    chk("第二段（网址粘在句尾）也保留", "比划着关保险的动作" in text)
    chk("短对话保留", "“你刚才倒下的时候。”" in text)
    chk("正文里提到网址的句子没被删", "他点开" in text)
    chk("“请到”句没被误删", "把客人请到屋里坐下" in text)
    chk("“百度搜索”句没被误删", "你上百度搜索一下" in text)
    chk("网址夹在长句中间原样保留", "比如那个叫 www.example.com 的站子" in text)
    # 行内夹网址、前后都是正文：宁可整行不动，也不删字（删字比留个网址更糟）
    chk("句中夹网址的短句整行保留", "他点开 www.zhudao.com 看了一眼" in text)

    print("== 广告行是否照样删掉 ==")
    chk("网址打头的广告行已删", "小说章节更新最快" not in text)
    chk("推广语在前的广告行已删", "手机版阅读网址" not in text)
    chk("孤零零的网址行已删", "www.zhudao.com\n" not in ("\n".join(lines) + "\n"))
    chk("网址在前、推广语在后的广告行已删", "小说下载网" not in text)
    chk("网址在前、后面接着正文的长句保留", "我常去逛的站子" in text)
    chk("翻页导航已删", "下一页" not in text)
    chk("章节标题保留", "第１２章　夜路" in text)

    print("== 计数 ==")
    chk("trimmed 计数正确", py["trimmed"] == 2, py["trimmed"])   # 两段是行尾粘网址
    chk("removed 计数正确", py["removed"] == 5, py["removed"])   # 4 条广告行 + 1 条导航

    print("== Python / Web 一致性 ==")
    chk("清洗后文本逐字相同", py["text"] == web["text"],
        None if py["text"] == web["text"] else (py["text"][:200], web["text"][:200]))
    chk("removed 相同", py["removed"] == web["removed"], (py["removed"], web["removed"]))
    chk("trimmed 相同", py["trimmed"] == web["trimmed"], (py["trimmed"], web["trimmed"]))
    chk("裁剪位置相同", len(web["cuts"]) == py["trimmed"], web["cuts"])

    print("\n结果: %d 通过, %d 失败" % (ok, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
