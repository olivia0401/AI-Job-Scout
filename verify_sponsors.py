# -*- coding: utf-8 -*-
"""在官方 sponsor register 中核验精选科技/AI 公司的担保资质。"""
import csv
import re
import sys
import json

REGISTER = r"C:\Users\olivi\Downloads\SP_-_Worker_and_Temporary_Worker_Web_Register_-_2026-07-06.csv"
OUT = r"C:\Users\olivi\OneDrive\Desktop\ASTON\求职\认真开始找工作了\AI-Job-Scout\verified_tech_sponsors.csv"

# 精选英国科技/AI 雇主（品牌名 -> 可能的注册名别名）
TARGETS = {
    # AI labs / AI-first
    "DeepMind": ["deepmind", "deepmind technologies"],
    "Google": ["google", "google uk"],
    "Anthropic": ["anthropic"],
    "OpenAI": ["openai"],
    "Microsoft": ["microsoft", "microsoft limited", "microsoft research"],
    "Amazon": ["amazon", "amazon uk services", "amazon development centre", "amazon web services uk"],
    "Meta": ["meta platforms", "facebook uk"],
    "Apple": ["apple", "apple europe"],
    "Nvidia": ["nvidia"],
    "ByteDance/TikTok": ["tiktok information technologies uk", "bytedance uk", "tiktok"],
    "Stability AI": ["stability ai"],
    "Synthesia": ["synthesia"],
    "Faculty": ["faculty science", "faculty ai", "faculty"],
    "PolyAI": ["polyai", "poly ai"],
    "Quantexa": ["quantexa"],
    "Darktrace": ["darktrace"],
    "BenevolentAI": ["benevolentai", "benevolent ai"],
    "Wayve": ["wayve", "wayve technologies"],
    "Oxa": ["oxa autonomy", "oxbotica"],
    "Graphcore": ["graphcore"],
    "Tractable": ["tractable"],
    "Onfido": ["onfido"],
    "Signal AI": ["signal ai", "signal media"],
    "Peak": ["peak ai"],
    "Featurespace": ["featurespace"],
    "Healx": ["healx"],
    "Exscientia": ["exscientia"],
    "InstaDeep": ["instadeep"],
    "Cohere": ["cohere", "cohere uk"],
    "Hugging Face": ["hugging face"],
    "Isomorphic Labs": ["isomorphic labs"],
    "Speechmatics": ["speechmatics", "cantab research"],
    "V7": ["v7", "v7 labs"],
    "Encord": ["encord", "cord technologies"],
    "Papercup": ["papercup"],
    "Unlikely AI": ["unlikely ai"],
    "Mind Foundry": ["mind foundry"],
    "Secondmind": ["secondmind"],
    "Eigen Technologies": ["eigen technologies"],
    "Scale AI": ["scale ai"],
    "Palantir": ["palantir", "palantir technologies uk"],
    "Databricks": ["databricks", "databricks uk"],
    "Snowflake": ["snowflake computing uk", "snowflake computing u k"],
    "QuantumBlack": ["quantumblack", "mckinsey"],
    # Fintech
    "Monzo": ["monzo", "monzo bank"],
    "Wise": ["wise", "wise payments", "transferwise"],
    "Revolut": ["revolut"],
    "Starling Bank": ["starling bank"],
    "Checkout.com": ["checkout", "checkout ltd", "cko"],
    "GoCardless": ["gocardless"],
    "Stripe": ["stripe", "stripe payments uk"],
    "Klarna": ["klarna", "klarna financial services uk", "klarna bank ab uk branch", "klarna bank ab"],
    "Zopa": ["zopa", "zopa bank"],
    "Thought Machine": ["thought machine"],
    "10x Banking": ["10x banking", "10x future technologies"],
    "ClearBank": ["clearbank", "clear bank"],
    "Form3": ["form3", "form3 financial cloud"],
    "Tide": ["tide", "tide platform"],
    "Marshmallow": ["marshmallow", "marshmallow financial services"],
    "Freetrade": ["freetrade"],
    "Plaid": ["plaid", "plaid financial"],
    "Bloomberg": ["bloomberg", "bloomberg lp"],
    "JPMorgan": ["jpmorgan", "jp morgan", "j.p. morgan", "jpmorgan chase bank national association"],
    "Goldman Sachs": ["goldman sachs"],
    "Morgan Stanley": ["morgan stanley"],
    "Barclays": ["barclays", "barclays bank", "barclays execution services"],
    "HSBC": ["hsbc", "hsbc bank", "hsbc uk bank", "hsbc global services uk"],
    "Lloyds Banking Group": ["lloyds banking group", "lloyds bank"],
    "NatWest": ["natwest", "natwest group", "national westminster bank"],
    "American Express": ["american express"],
    "Mastercard": ["mastercard", "mastercard uk", "mastercard uk management services"],
    "Visa": ["visa europe"],
    # Tech / product
    "Deliveroo": ["deliveroo", "roofoods"],
    "Ocado": ["ocado", "ocado group", "ocado technology", "ocado innovation", "ocado central services", "ocado retail"],
    "Just Eat": ["just eat", "just eat takeaway"],
    "Skyscanner": ["skyscanner"],
    "Expedia": ["expedia", "expedia group", "expedia com"],
    "Booking.com": ["booking.com"],
    "Spotify": ["spotify"],
    "Trainline": ["trainline", "trainline.com"],
    "Zoopla": ["zoopla", "zpg"],
    "Rightmove": ["rightmove"],
    "Auto Trader": ["auto trader", "autotrader"],
    "Motorway": ["motorway", "motorway online"],
    "Depop": ["depop"],
    "ASOS": ["asos", "asos.com"],
    "THG": ["thg", "the hut group", "the hut.com"],
    "King": ["king.com", "king digital"],
    "Improbable": ["improbable", "improbable worlds"],
    "Sky": ["sky uk", "sky"],
    "BT": ["bt", "british telecommunications"],
    "Vodafone": ["vodafone", "vodafone group services", "vodafone limited"],
    "Arm": ["arm", "arm limited"],
    "Dyson": ["dyson", "dyson technology"],
    "Rolls-Royce": ["rolls-royce", "rolls royce"],
    "BAE Systems": ["bae systems", "bae systems digital intelligence"],
    "Samsung": ["samsung electronics uk", "samsung electronics (uk)", "samsung r&d institute uk"],
    "Huawei": ["huawei technologies (uk)", "huawei technologies uk"],
    "IBM": ["ibm", "ibm united kingdom"],
    "Oracle": ["oracle", "oracle corporation uk"],
    "SAP": ["sap uk", "sap (uk)"],
    "Salesforce": ["salesforce", "salesforce uk", "salesforce.com"],
    "Adobe": ["adobe", "adobe systems europe"],
    "Cisco": ["cisco", "cisco international", "cisco systems"],
    "Intel": ["intel", "intel corporation (uk)"],
    "Qualcomm": ["qualcomm", "qualcomm technologies international"],
    "Sage": ["sage", "sage (uk)", "the sage group"],
    "Aveva": ["aveva", "aveva solutions"],
    "Datadog": ["datadog", "datadog uk", "datadog ireland"],
    "Elastic": ["elastic", "elasticsearch"],
    "MongoDB": ["mongodb"],
    "Twilio": ["twilio", "twilio uk"],
    "Snyk": ["snyk", "snyk ltd"],
    "Sophos": ["sophos"],
    "Kainos": ["kainos", "kainos software"],
    "Softwire": ["softwire", "softwire technology"],
    "TPP": ["tpp", "the phoenix partnership"],
    "UiPath": ["uipath"],
    "Wayfair": ["wayfair", "wayfair (uk)"],
    "Netflix": ["netflix", "netflix services uk"],
    "Airbnb": ["airbnb", "airbnb uk"],
    "Uber": ["uber", "uber london", "uber britannia"],
    "LinkedIn": ["linkedin", "linkedin technology uk"],
    "Tesco": ["tesco", "tesco stores"],
    "Sainsbury's": ["sainsbury's", "sainsburys", "j sainsbury"],
    "John Lewis": ["john lewis", "john lewis plc", "john lewis partnership"],
    "Accenture": ["accenture", "accenture (uk)"],
    "Capgemini": ["capgemini", "capgemini uk"],
    "Infosys": ["infosys", "infosys limited"],
    "TCS": ["tata consultancy services"],
    "Wipro": ["wipro", "wipro limited"],
    "Deloitte": ["deloitte", "deloitte llp", "deloitte mcs"],
    "PwC": ["pricewaterhousecoopers", "pwc"],
    "KPMG": ["kpmg", "kpmg llp"],
    "EY": ["ernst & young", "ernst and young"],
}

SUFFIX_WORDS = {
    "ltd", "limited", "plc", "llp", "lp", "inc", "uk", "group", "holdings",
    "technologies", "technology", "labs", "lab", "co", "company", "services",
    "service", "international", "europe", "eu", "gb", "britain", "software",
    "systems", "solutions", "the", "and",
}


def norm(s):
    s = s.lower().strip()
    s = re.sub(r"\(.*?\)", " ", s)          # 去括号内容
    s = re.sub(r"t/a.*$", " ", s)           # 去 trading-as 后缀
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_suffix(words):
    w = list(words)
    while len(w) > 1 and w[-1] in SUFFIX_WORDS:
        w.pop()
    return w


def main():
    # 建别名索引
    alias_map = {}  # normalized alias -> brand
    for brand, aliases in TARGETS.items():
        for a in aliases + [brand]:
            alias_map[norm(a)] = brand

    matches = {}  # brand -> [rows]
    with open(REGISTER, encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            name = (row.get("Organisation Name") or "").strip()
            route = (row.get("Route") or "").strip()
            if not name or route != "Skilled Worker":
                continue
            n = norm(name)
            words = n.split()
            cands = {n, " ".join(strip_suffix(words))}
            # 前缀匹配：剩余部分全是后缀词才算
            for alias, brand in alias_map.items():
                aw = alias.split()
                if words[:len(aw)] == aw and all(x in SUFFIX_WORDS for x in words[len(aw):]):
                    cands.add(alias)
            hit = None
            for c in cands:
                if c in alias_map:
                    hit = alias_map[c]
                    break
            if hit:
                matches.setdefault(hit, [])
                rec = (name, (row.get("Town/City") or "").strip(),
                       (row.get("Type & Rating") or "").strip())
                if rec not in matches[hit]:
                    matches[hit].append(rec)

    found = sorted(matches)
    missing = sorted(set(TARGETS) - set(found))
    print(f"核验通过 {len(found)}/{len(TARGETS)} 家：")
    for b in found:
        regs = "; ".join(f"{n} ({t})" for n, t, _ in matches[b][:3])
        print(f"  ✓ {b}  ->  {regs}")
    print(f"\n未在 Skilled Worker 注册表中找到 {len(missing)} 家：")
    print("  " + ", ".join(missing))

    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Company", "Registered Name(s)", "Town/City", "Rating"])
        for b in found:
            for name, town, rating in matches[b]:
                w.writerow([b, name, town, rating])
    print(f"\n已写出: {OUT}")
    print(json.dumps(found, ensure_ascii=False))


if __name__ == "__main__":
    main()
