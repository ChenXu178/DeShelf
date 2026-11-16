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


def run_python(text, rules=None):
    st = {}
    out, removed = jzcore.clean_text(text, rules or RULES, st)
    return {"text": out, "removed": removed, "trimmed": st.get("trimmed", 0)}


def run_web(text, rules=None):
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    fd, tmp = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        io.open(tmp, "w", encoding="utf-8", newline="").write(text)
        r = subprocess.run(
            ["node", os.path.join(here, "_dump_clean.mjs"), tmp, json.dumps(rules or RULES)],
            capture_output=True, cwd=root,
        )
        if r.returncode != 0:
            raise SystemExit("node 执行失败：" + r.stderr.decode("utf-8", "ignore")[:400])
        return json.loads(r.stdout.decode("utf-8"))
    finally:
        os.remove(tmp)


# —— 简繁双份语料：盗版站常见形态，繁體版 + 简体版 各一份，其中一行还被插了网址 ——
DUAL = "\n".join([
    "第一章　雨夜",
    "##########  繁體版  ##########",
    "雨停之後，她把窗推開一條縫，讓潮氣散出去。",
    "「妳真的不打算告訴他？」室友靠在門邊問。",
    "她沒回答，只是把濕透的外套掛在椅背上。",
    "桌曆上那頁還停在上週三，紅筆圈著的日期被水泡得發皺。",
    "樓下有人按了兩次門鈴，又走遠了。",
    "她把窗簾拉嚴，屋子裡只剩冰箱低低的嗡鳴聲。",
    "那聲音持續了很久，久到她開始懷疑自己聽錯了。",
    "##########  简体版  ##########",
    "雨停之后，她把窗推开一条缝，让潮气散出去。",
    "「妳真的不打算告诉他？」室友靠在门边问。",
    "她没回答，只是把湿透的外套挂在椅背上www.zwdu.com。",
    "桌历上那页还停在上周三，红笔圈着的日期被水泡得发皱。",
    "楼下有人按了两次门铃，又走远了。",
    "她把窗帘拉严，屋子里只剩冰箱低低的嗡鸣声。",
    "那声音持续了很久，久到她开始怀疑自己听错了。",
])

# 繁体行里被整段追加了乱码：长度差出一大截，但短那行是长那行的完整前缀
DUAL3 = "\n".join([
    "第二章　樓梯",
    "##########  繁體版  ##########",
    "她把濕透的外套掛在椅背上，屋裡只剩冰箱低低的嗡鳴。",
    "樓梯踩上去的每一步都很輕，卻像在這間屋子裡敲了一記悶雷。",
    "【影の通信  ようこそ、復讐を望む者よ】",
    "她把手機放到桌上，螢幕朝下，像在躲什麼。",
    "窗外的雨還在下，打在冷氣機殼上發出細碎的聲響。",
    "那聲音持續了很久，久到她開始懷疑自己聽錯了。",
    "她沒有開燈，摸黑走上二樓，扶手冰得像鐵。",
    "房門關上的那一刻，整棟房子忽然安靜得可怕。",
    "標題我都幫妳想好了：弎氿z灵┈壹⒊叁⑦Т衣泗",
    "##########  简体版  ##########",
    "她把湿透的外套挂在椅背上，屋里只剩冰箱低低的嗡鸣。",
    "楼梯踩上去的每一步都很轻，却像在这间屋子里敲了一记闷雷。",
    "【影の通信  ようこそ、復讐を望む者よ】",
    "她把手机放到桌上，屏幕朝下，像在躲什么。",
    "窗外的雨还在下，打在冷气机壳上发出细碎的声响。",
    "那声音持续了很久，久到她开始怀疑自己听错了。",
    "她没有开灯，摸黑走上二楼，扶手冰得像铁。",
    "房门关上的那一刻，整栋房子忽然安静得可怕。",
    "标题我都帮妳想好了",
])

# 纯简体文本：一行都不许动
SIMPLY = "\n".join([
    "第一章　雨夜",
    "雨停之后，她把窗推开一条缝，让潮气散出去。",
    "「你真的不打算告诉他？」室友靠在门边问。",
    "她没回答，只是把湿透的外套挂在椅背上。",
    "楼下有人按了两次门铃，又走远了。",
])


def _trad_left(text):
    out = []
    for ln in text.split("\n"):
        if jzcore._trad_score(ln) >= 2:
            out.append(ln)
    return out


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

    print("== 简繁重复行 ==")
    jd_rules = ["jsdup"]
    jd = run_python(DUAL, jd_rules)
    jd_web = run_web(DUAL, jd_rules)
    left = _trad_left(jd["text"])
    chk("繁体那几行全部删掉", not left, left[:3])
    chk("简体正文一句不少", "雨停之后" in jd["text"] and "怀疑自己听错了" in jd["text"]
        and "冰箱低低的嗡鸣声" in jd["text"])
    chk("版本标记行整行删掉", "繁體版" not in jd["text"] and "简体版" not in jd["text"])
    chk("Python / Web 逐字相同", jd["text"] == jd_web["text"],
        None if jd["text"] == jd_web["text"] else (jd["text"][:200], jd_web["text"][:200]))
    chk("删除计数相同", jd["removed"] == jd_web["removed"], (jd["removed"], jd_web["removed"]))
    jd3 = run_python(DUAL3, jd_rules)
    jd3_web = run_web(DUAL3, jd_rules)
    chk("整段追加乱码的繁体行也删掉", "標題" not in jd3["text"] and "弎氿" not in jd3["text"])
    chk("对应的简体短行留下", "标题我都帮妳想好了" in jd3["text"])
    chk("块内两份一样的行只留一份", jd3["text"].count("影の通信") == 1, jd3["text"].count("影の通信"))
    chk("正文没被误删", "楼梯踩上去的每一步都很轻" in jd3["text"] and "怀疑自己听错了" in jd3["text"])
    chk("DUAL3 Python / Web 逐字相同", jd3["text"] == jd3_web["text"],
        None if jd3["text"] == jd3_web["text"] else (jd3["text"][:200], jd3_web["text"][:200]))
    plain = run_python(SIMPLY, jd_rules)
    chk("纯简体文本一字不动", plain["text"].strip("\n") == SIMPLY and plain["removed"] == 0, plain["removed"])

    print("\n结果: %d 通过, %d 失败" % (ok, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
