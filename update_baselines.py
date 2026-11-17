"""
Roda localmente para popular data/baselines.json com o estado atual
de todos os concorrentes. Commite o arquivo depois para persistir
no Streamlit Cloud.

  python update_baselines.py
  git add data/baselines.json && git commit -m "chore: atualiza baselines" && git push
"""

import requests
import hashlib
import json
import os
import re
import time
import urllib3
from datetime import datetime
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

CONCORRENTES = {
    "Fsist":        "https://www.fsist.com.br/planos",
    "Sieg":         "https://www.sieg.com/planos",
    "Jettax":       "https://www.jettax.com.br/planos",
    "Hubstrom":     "https://hubstrom.com/precos",
    "Monitor DFe":  "https://monitordfe.com.br/planos",
    "Fluvi":        "https://usefluvi.com.br/precos",
    "v360":         "https://v360.io/ia-para-gestao-fiscal",
    "Vistax":       "https://www.vistaxtech.com/planos",
    "Unecount":     "https://www.unecont.com/precos",
    "Notalize":     "https://notalize.app/precos",
    "Autmais":      "https://www.autmais.com.br/planos",
    "Qive":         "https://qive.com.br/planos",
    "Klaus Fiscal": "https://klausfiscal.com.br/planos",
    "QYON":         "https://qyon.com/br/planos",
}


def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        return r.text
    except Exception as e:
        print(f"  ERRO: {e}")
        return None


def page_hash(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "meta", "link", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
    return hashlib.md5(text.encode()).hexdigest()


def extract_snippets(html):
    soup = BeautifulSoup(html, "html.parser")
    patterns = [r"R\$\s*[\d.,]+", r"[Pp]lano", r"[Pp]reço", r"[Aa]ssinatura", r"[Mm]ensalidade"]
    seen, snippets = set(), []
    for line in soup.get_text(separator="\n").split("\n"):
        line = line.strip()
        if not (8 <= len(line) <= 200) or line in seen:
            continue
        for pat in patterns:
            if re.search(pat, line):
                seen.add(line)
                snippets.append(line)
                break
    return snippets[:20]


def main():
    os.makedirs("data", exist_ok=True)
    existing = {}
    if os.path.exists("data/baselines.json"):
        with open("data/baselines.json", encoding="utf-8") as f:
            existing = json.load(f)

    baselines = dict(existing)

    for nome, url in CONCORRENTES.items():
        print(f"Processando {nome}...")
        html = fetch(url)
        if html:
            h = page_hash(html)
            prev = existing.get(nome, {}).get("hash")
            if prev and prev != h:
                print(f"  ⚠️  MUDANÇA DETECTADA em {nome}!")
            baselines[nome] = {
                "hash": h,
                "url": url,
                "data": datetime.now().isoformat(),
                "snippets": extract_snippets(html),
            }
            print(f"  OK — hash {h[:8]}…")
        else:
            print(f"  FALHOU — mantendo baseline anterior")
        time.sleep(0.5)

    with open("data/baselines.json", "w", encoding="utf-8") as f:
        json.dump(baselines, f, ensure_ascii=False, indent=2)

    print(f"\n✅ baselines.json atualizado com {len(baselines)} entradas.")
    print("Próximo passo:")
    print("  git add data/baselines.json && git commit -m 'chore: atualiza baselines' && git push")


if __name__ == "__main__":
    main()
