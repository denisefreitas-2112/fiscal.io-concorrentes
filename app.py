import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import feedparser
import hashlib
import json
import os
import re
import time
from bs4 import BeautifulSoup

st.set_page_config(
    page_title="Intel de Concorrentes — Fiscal.IO",
    page_icon="🔍",
    layout="wide",
)

# ─── Helpers ──────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}


def fetch_page(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        return r.text, r.status_code
    except Exception as e:
        return None, str(e)


def page_hash(html):
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "meta", "link", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
    return hashlib.md5(text.encode()).hexdigest()


def extract_price_snippets(html):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    patterns = [
        r"R\$\s*[\d.,]+",
        r"[Pp]lano",
        r"[Pp]reço",
        r"[Aa]ssinatura",
        r"[Mm]ensalidade",
        r"[Gg]ratuito",
        r"[Ff]ree",
    ]
    snippets = []
    for line in text.split("\n"):
        line = line.strip()
        if len(line) < 5 or len(line) > 250:
            continue
        for pat in patterns:
            if re.search(pat, line):
                snippets.append(line)
                break
    return snippets[:30]


def get_rss_entries(url, max_items=5):
    try:
        feed = feedparser.parse(url)
        return [
            {
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "published": e.get("published", "")[:10] if e.get("published") else "",
            }
            for e in feed.entries[:max_items]
        ], None
    except Exception as ex:
        return [], str(ex)


def discover_feed(base_url, max_items=5):
    for path in ["/feed", "/rss", "/blog/feed/", "/feed/", "/blog/rss/", "/sitemap.xml"]:
        try:
            r = requests.get(base_url.rstrip("/") + path, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            feed = feedparser.parse(r.text)
            if feed.entries:
                return [
                    {
                        "title": e.get("title", ""),
                        "link": e.get("link", ""),
                        "published": e.get("published", "")[:10] if e.get("published") else "",
                    }
                    for e in feed.entries[:max_items]
                ], path
            # Try as sitemap
            soup = BeautifulSoup(r.text, "xml")
            locs = [
                l.text for l in soup.find_all("loc")
                if any(k in l.text for k in ["/blog/", "/artigo", "/noticias", "/post/"])
            ][:max_items]
            if locs:
                return [{"title": l.rstrip("/").split("/")[-1].replace("-", " "), "link": l, "published": ""} for l in locs], "/sitemap.xml"
        except Exception:
            continue
    return [], None


def get_reclameaqui(slug):
    try:
        url = (
            f"https://iosearch.reclameaqui.com.br/"
            f"raichu-io-site-search-v1/query/companyComplaint/5/0?q={slug}"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        companies = r.json().get("companies", {}).get("result", [])
        if companies:
            c = companies[0]
            return {
                "nome": c.get("fantasyName", slug),
                "score": round(float(c.get("score", 0)), 1) if c.get("score") else "—",
                "total": c.get("complaintAmount", 0),
                "respondidas": c.get("answeredAmount", 0),
                "url": f"https://www.reclameaqui.com.br/empresa/{c.get('slug', slug)}/",
            }
    except Exception:
        pass
    return None


def get_meta_ads(search_term, token, limit=10):
    try:
        r = requests.get(
            "https://graph.facebook.com/v19.0/ads_archive",
            params={
                "search_terms": search_term,
                "ad_reached_countries": '["BR"]',
                "ad_active_status": "ACTIVE",
                "fields": (
                    "id,ad_creative_bodies,ad_creative_link_titles,"
                    "ad_delivery_start_time,ad_snapshot_url,page_name"
                ),
                "access_token": token,
                "limit": limit,
            },
            timeout=15,
        )
        data = r.json()
        if "error" in data:
            return [], data["error"].get("message", "Erro desconhecido")
        return data.get("data", []), None
    except Exception as ex:
        return [], str(ex)


# ─── Competitor list ──────────────────────────────────────────────────────────
CONCORRENTES = {
    "Fsist":        {"url": "https://www.fsist.com.br/",             "meta_search": "Fsist DFe",             "reclame": "fsist",        "rss": None},
    "Sieg":         {"url": "https://www.sieg.com/",                 "meta_search": "Sieg documentos fiscais","reclame": "sieg-cloud",   "rss": "https://www.sieg.com/blog/feed/"},
    "Jettax":       {"url": "https://www.jettax.com.br/",            "meta_search": "Jettax",                "reclame": "jettax",       "rss": None},
    "Hubstrom":     {"url": "https://hubstrom.com/",                 "meta_search": "Hubstrom",              "reclame": "hubstrom",     "rss": None},
    "Monitor DFe":  {"url": "https://monitordfe.com.br/",            "meta_search": "Monitor DFe",           "reclame": "monitor-dfe",  "rss": None},
    "Fluvi":        {"url": "https://usefluvi.com.br/",              "meta_search": "Fluvi fiscal",          "reclame": "fluvi",        "rss": None},
    "v360":         {"url": "https://v360.io/ia-para-gestao-fiscal", "meta_search": "v360 fiscal",           "reclame": "v360",         "rss": None},
    "Vistax":       {"url": "https://www.vistaxtech.com/",           "meta_search": "Vistax Tech",           "reclame": "vistax",       "rss": None},
    "Unecount":     {"url": "https://www.unecont.com/",              "meta_search": "Unecount",              "reclame": "unecont",      "rss": None},
    "Notalize":     {"url": "https://notalize.app/",                 "meta_search": "Notalize contador",     "reclame": "notalize",     "rss": None},
    "Autmais":      {"url": "https://www.autmais.com.br/",           "meta_search": "Autmais",               "reclame": "autmais",      "rss": None},
    "Qive":         {"url": "https://qive.com.br/",                  "meta_search": "Qive fiscal",           "reclame": "qive",         "rss": None},
    "Klaus Fiscal": {"url": "https://klausfiscal.com.br/",           "meta_search": "Klaus Fiscal",          "reclame": "klausfiscal",  "rss": None},
    "QYON":         {"url": "https://qyon.com/br/",                  "meta_search": "QYON fiscal",           "reclame": "qyon",         "rss": None},
}

META_TOKEN = st.secrets.get("META_ACCESS_TOKEN", "")

BASELINE_PATH = "data/baselines.json"


def load_baselines():
    if os.path.exists(BASELINE_PATH):
        try:
            with open(BASELINE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_baselines(data):
    os.makedirs("data", exist_ok=True)
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── Layout ───────────────────────────────────────────────────────────────────
st.title("🔍 Inteligência de Concorrentes")
st.caption(f"Fiscal.IO · {datetime.now().strftime('%d/%m/%Y %H:%M')}")

tab_meta, tab_site, tab_conteudo, tab_rep = st.tabs([
    "🎯 Meta Ads",
    "🔄 Mudanças no Site",
    "📝 Conteúdo",
    "⭐ Reclame Aqui",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Meta Ads
# ══════════════════════════════════════════════════════════════════════════════
with tab_meta:
    st.subheader("Anúncios ativos no Meta (Facebook / Instagram)")

    if not META_TOKEN:
        st.error(
            "Configure `META_ACCESS_TOKEN` nos **Secrets** do Streamlit Cloud.\n\n"
            "Obtenha seu token em: https://developers.facebook.com/tools/explorer/"
        )
    else:
        empresa_sel = st.selectbox("Concorrente", list(CONCORRENTES.keys()), key="meta_emp")

        if st.button("🔍 Buscar anúncios ativos", key="btn_meta"):
            c = CONCORRENTES[empresa_sel]
            with st.spinner(f"Consultando Meta Ad Library para {empresa_sel}..."):
                ads, err = get_meta_ads(c["meta_search"], META_TOKEN)

            if err:
                st.error(f"Erro da API: {err}")
            elif not ads:
                st.info(f"Nenhum anúncio ativo encontrado para '{empresa_sel}'.")
            else:
                st.success(f"**{len(ads)}** anúncio(s) ativo(s)")
                for ad in ads:
                    page = ad.get("page_name", "Página desconhecida")
                    inicio = (ad.get("ad_delivery_start_time") or "?")[:10]
                    titles = ad.get("ad_creative_link_titles") or []
                    bodies = ad.get("ad_creative_bodies") or []
                    with st.expander(f"📌 {page}  —  desde {inicio}"):
                        if titles:
                            st.markdown(f"**{titles[0]}**")
                        if bodies:
                            st.write(bodies[0])
                        if ad.get("ad_snapshot_url"):
                            st.markdown(f"[Ver criativo completo ↗]({ad['ad_snapshot_url']})")

    st.markdown("---")
    st.markdown("**Links diretos na Ad Library do Meta:**")
    cols = st.columns(4)
    for i, (nome, info) in enumerate(CONCORRENTES.items()):
        q = info["meta_search"].replace(" ", "%20")
        link = (
            f"https://www.facebook.com/ads/library/"
            f"?active_status=active&ad_type=all&country=BR"
            f"&q={q}&search_type=keyword_unordered"
        )
        cols[i % 4].markdown(f"[{nome}]({link})")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Mudanças no Site
# ══════════════════════════════════════════════════════════════════════════════
with tab_site:
    st.subheader("Monitoramento de alterações nas páginas dos concorrentes")
    st.caption(
        "Compara o conteúdo atual com o baseline salvo. "
        "Detecta mudanças em texto de preços, planos e copy."
    )

    baselines = load_baselines()

    empresa_site = st.selectbox("Concorrente", list(CONCORRENTES.keys()), key="site_emp")
    col_a, col_b = st.columns(2)
    btn_check = col_a.button("🔍 Verificar agora", key="btn_site_chk")
    btn_save = col_b.button("💾 Salvar como baseline", key="btn_site_save")

    if btn_check or btn_save:
        c = CONCORRENTES[empresa_site]
        with st.spinner(f"Acessando {c['url']}..."):
            html, status = fetch_page(c["url"])

        if html is None:
            st.error(f"Não foi possível acessar o site: {status}")
        else:
            cur_hash = page_hash(html)
            snippets = extract_price_snippets(html)

            if btn_save:
                baselines[empresa_site] = {
                    "hash": cur_hash,
                    "url": c["url"],
                    "data": datetime.now().isoformat(),
                    "snippets": snippets,
                }
                save_baselines(baselines)
                st.success(f"✅ Baseline salvo para **{empresa_site}** em {datetime.now().strftime('%d/%m/%Y %H:%M')}")

            if btn_check:
                baseline = baselines.get(empresa_site)
                if not baseline:
                    st.warning("Nenhum baseline para este concorrente. Salve um primeiro.")
                elif baseline["hash"] == cur_hash:
                    st.success(f"✅ Sem alterações desde {baseline['data'][:10]}")
                else:
                    st.warning(f"⚠️ **MUDANÇA DETECTADA** — baseline era de {baseline['data'][:10]}")
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Antes (baseline):**")
                        for s in baseline.get("snippets", [])[:15]:
                            st.text(s)
                    with c2:
                        st.markdown("**Agora:**")
                        for s in snippets[:15]:
                            st.text(s)

                st.markdown("---")
                st.markdown("**Trechos de preços/planos encontrados agora:**")
                if snippets:
                    for s in snippets[:20]:
                        st.text(s)
                else:
                    st.info("Nenhum trecho encontrado (site pode usar JavaScript para renderizar preços).")

    st.markdown("---")
    if st.button("📊 Verificar TODOS os concorrentes", key="btn_all_sites"):
        baselines = load_baselines()
        results = []
        prog = st.progress(0)
        txt = st.empty()
        for i, (nome, info) in enumerate(CONCORRENTES.items()):
            txt.text(f"Verificando {nome}…")
            html, _ = fetch_page(info["url"])
            cur_hash = page_hash(html) if html else None
            bl = baselines.get(nome, {})
            if not cur_hash:
                status_icon = "❌ Erro de acesso"
            elif not bl:
                status_icon = "⚪ Sem baseline"
            elif bl.get("hash") == cur_hash:
                status_icon = "✅ Sem mudanças"
            else:
                status_icon = "⚠️ MUDOU"
            results.append({
                "Concorrente": nome,
                "Status": status_icon,
                "Baseline": bl.get("data", "—")[:10] if bl else "—",
                "URL": info["url"],
            })
            prog.progress((i + 1) / len(CONCORRENTES))
            time.sleep(0.4)
        txt.empty()
        prog.empty()
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Conteúdo
# ══════════════════════════════════════════════════════════════════════════════
with tab_conteudo:
    st.subheader("Conteúdo publicado pelos concorrentes")

    RSS_CONHECIDOS = {
        "Sieg":    "https://www.sieg.com/blog/feed/",
        "Qive":    "https://qive.com.br/blog/feed/",
        "QYON":    "https://qyon.com/br/blog/feed/",
        "Autmais": "https://www.autmais.com.br/feed/",
        "Vistax":  "https://www.vistaxtech.com/blog/feed/",
    }

    empresa_cont = st.selectbox("Concorrente", list(CONCORRENTES.keys()), key="cont_emp")

    if st.button("📡 Buscar publicações recentes", key="btn_cont"):
        c = CONCORRENTES[empresa_cont]
        rss_url = c.get("rss") or RSS_CONHECIDOS.get(empresa_cont)
        with st.spinner(f"Buscando conteúdo de {empresa_cont}..."):
            entries, source = [], None
            if rss_url:
                entries, _ = get_rss_entries(rss_url)
                source = rss_url
            if not entries:
                entries, source = discover_feed(c["url"])

        if entries:
            st.success(f"{len(entries)} publicação(ões) · fonte: `{source}`")
            for e in entries:
                pub = f" · {e['published']}" if e["published"] else ""
                st.markdown(f"- [{e['title']}]({e['link']}){pub}")
        else:
            st.info(f"Feed não encontrado automaticamente para {empresa_cont}.")
            base = c["url"].rstrip("/")
            st.markdown("**Tente acessar:**")
            for path in ["/blog", "/artigos", "/noticias", "/conteudo"]:
                st.markdown(f"- [{base + path}]({base + path})")

    st.markdown("---")
    if st.button("📰 Agregar todos os feeds conhecidos", key="btn_all_feeds"):
        all_entries = []
        for nome, feed_url in RSS_CONHECIDOS.items():
            ents, _ = get_rss_entries(feed_url, max_items=5)
            for e in ents:
                e["Empresa"] = nome
                all_entries.append(e)
        if all_entries:
            df = pd.DataFrame(all_entries)[["Empresa", "title", "published", "link"]]
            df.columns = ["Empresa", "Título", "Publicado", "Link"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum feed retornou conteúdo no momento.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Reclame Aqui
# ══════════════════════════════════════════════════════════════════════════════
with tab_rep:
    st.subheader("Reputação no Reclame Aqui")

    if st.button("📊 Buscar todos os concorrentes", key="btn_ra_all"):
        results = []
        prog = st.progress(0)
        txt = st.empty()
        for i, (nome, info) in enumerate(CONCORRENTES.items()):
            txt.text(f"Consultando {nome}…")
            data = get_reclameaqui(info["reclame"])
            if data:
                results.append({
                    "Concorrente": nome,
                    "Score RA": data["score"],
                    "Reclamações": data["total"],
                    "Respondidas": data["respondidas"],
                    "Perfil": data["url"],
                })
            else:
                results.append({
                    "Concorrente": nome,
                    "Score RA": "—",
                    "Reclamações": "—",
                    "Respondidas": "—",
                    "Perfil": f"https://www.reclameaqui.com.br/empresa/{info['reclame']}/",
                })
            prog.progress((i + 1) / len(CONCORRENTES))
            time.sleep(0.3)
        txt.empty()
        prog.empty()
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

    st.markdown("---")
    empresa_ra = st.selectbox("Concorrente individual", list(CONCORRENTES.keys()), key="ra_emp")
    if st.button("🔍 Buscar", key="btn_ra_one"):
        slug = CONCORRENTES[empresa_ra]["reclame"]
        with st.spinner(f"Buscando {empresa_ra} no Reclame Aqui..."):
            data = get_reclameaqui(slug)
        if data:
            m1, m2, m3 = st.columns(3)
            m1.metric("Score RA", data["score"])
            m2.metric("Total reclamações", data["total"])
            m3.metric("Respondidas", data["respondidas"])
            st.markdown(f"[Abrir perfil completo no Reclame Aqui ↗]({data['url']})")
        else:
            ra_url = f"https://www.reclameaqui.com.br/empresa/{slug}/"
            st.info(f"Perfil não localizado via API. [Buscar manualmente ↗]({ra_url})")
