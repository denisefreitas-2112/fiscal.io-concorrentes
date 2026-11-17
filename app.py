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
    "Accept-Language": "pt-BR,pt;q=0.9",
}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
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


def extract_page_info(html):
    """Extract meta title, description and any visible price snippets."""
    result = {"title": "", "description": "", "snippets": []}
    if not html:
        return result
    soup = BeautifulSoup(html, "html.parser")

    tag = soup.find("title")
    if tag:
        result["title"] = tag.get_text().strip()

    for attr in [{"property": "og:description"}, {"name": "description"}]:
        m = soup.find("meta", attr)
        if m and m.get("content"):
            result["description"] = m["content"].strip()
            break

    # price snippets — best effort
    patterns = [r"R\$\s*[\d.,]+", r"[Pp]lano", r"[Pp]reço", r"[Aa]ssinatura", r"[Mm]ensalidade", r"[Gg]ratuito", r"trial"]
    seen = set()
    for line in soup.get_text(separator="\n").split("\n"):
        line = line.strip()
        if not (8 <= len(line) <= 200) or line in seen:
            continue
        for pat in patterns:
            if re.search(pat, line):
                seen.add(line)
                result["snippets"].append(line)
                break
    result["snippets"] = result["snippets"][:20]
    return result


def extract_price_snippets(html):
    return extract_page_info(html)["snippets"]


@st.cache_data(ttl=3600, show_spinner=False)
def get_rss_entries(url, max_items=6):
    try:
        feed = feedparser.parse(url)
        return [
            {
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "published": (e.get("published") or "")[:10],
            }
            for e in feed.entries[:max_items]
        ]
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def get_reclameaqui(nome_empresa):
    """Busca pelo nome da empresa no Reclame Aqui."""
    try:
        q = requests.utils.quote(nome_empresa)
        url = (
            "https://iosearch.reclameaqui.com.br/"
            f"raichu-io-site-search-v1/query/companyComplaint/5/0?q={q}"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        companies = r.json().get("companies", {}).get("result", [])
        if companies:
            c = companies[0]
            score = c.get("score")
            return {
                "nome": c.get("fantasyName", nome_empresa),
                "score": round(float(score), 1) if score else "—",
                "total": c.get("complaintAmount", 0),
                "respondidas": c.get("answeredAmount", 0),
                "ra_slug": c.get("slug", ""),
                "url": f"https://www.reclameaqui.com.br/empresa/{c.get('slug', '')}/",
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


# ─── Competitor list ──────────────────────────────────────────────────────────
CONCORRENTES = {
    "Fsist":        {
        "url": "https://www.fsist.com.br/",
        "pricing_url": "https://www.fsist.com.br/planos",
        "meta_search": "Fsist DFe",
        "reclame": "fsist",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "Sieg":         {
        "url": "https://www.sieg.com/",
        "pricing_url": "https://www.sieg.com/planos",
        "meta_search": "Sieg documentos fiscais",
        "reclame": "sieg-cloud",
        "g2": "https://www.g2.com/search#q=sieg%20cloud",
        "capterra": "https://www.capterra.com.br/search#q=sieg",
        "changelog": None,
        "rss": "https://www.sieg.com/blog/feed/",
    },
    "Jettax":       {
        "url": "https://www.jettax.com.br/",
        "pricing_url": "https://www.jettax.com.br/planos",
        "meta_search": "Jettax",
        "reclame": "jettax",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "Hubstrom":     {
        "url": "https://hubstrom.com/",
        "pricing_url": "https://hubstrom.com/precos",
        "meta_search": "Hubstrom",
        "reclame": "hubstrom",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "Monitor DFe":  {
        "url": "https://monitordfe.com.br/",
        "pricing_url": "https://monitordfe.com.br/planos",
        "meta_search": "Monitor DFe",
        "reclame": "monitor-dfe",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "Fluvi":        {
        "url": "https://usefluvi.com.br/",
        "pricing_url": "https://usefluvi.com.br/precos",
        "meta_search": "Fluvi fiscal",
        "reclame": "fluvi",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "v360":         {
        "url": "https://v360.io/ia-para-gestao-fiscal",
        "pricing_url": "https://v360.io/ia-para-gestao-fiscal",
        "meta_search": "v360 fiscal",
        "reclame": "v360",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "Vistax":       {
        "url": "https://www.vistaxtech.com/",
        "pricing_url": "https://www.vistaxtech.com/planos",
        "meta_search": "Vistax Tech",
        "reclame": "vistax",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "Unecount":     {
        "url": "https://www.unecont.com/",
        "pricing_url": "https://www.unecont.com/precos",
        "meta_search": "Unecount",
        "reclame": "unecont",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "Notalize":     {
        "url": "https://notalize.app/",
        "pricing_url": "https://notalize.app/precos",
        "meta_search": "Notalize contador",
        "reclame": "notalize",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "Autmais":      {
        "url": "https://www.autmais.com.br/",
        "pricing_url": "https://www.autmais.com.br/planos",
        "meta_search": "Autmais",
        "reclame": "autmais",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": "https://www.autmais.com.br/feed/",
    },
    "Qive":         {
        "url": "https://qive.com.br/",
        "pricing_url": "https://qive.com.br/planos",
        "meta_search": "Qive fiscal",
        "reclame": "qive",
        "g2": "https://www.g2.com/search#q=qive",
        "capterra": "https://www.capterra.com.br/search#q=qive",
        "changelog": None,
        "rss": "https://qive.com.br/blog/feed/",
    },
    "Klaus Fiscal": {
        "url": "https://klausfiscal.com.br/",
        "pricing_url": "https://klausfiscal.com.br/planos",
        "meta_search": "Klaus Fiscal",
        "reclame": "klausfiscal",
        "g2": None,
        "capterra": None,
        "changelog": None,
        "rss": None,
    },
    "QYON":         {
        "url": "https://qyon.com/br/",
        "pricing_url": "https://qyon.com/br/planos",
        "meta_search": "QYON fiscal",
        "reclame": "qyon",
        "g2": "https://www.g2.com/search#q=qyon",
        "capterra": "https://www.capterra.com.br/search#q=qyon",
        "changelog": "https://qyon.com/br/novidades",
        "rss": "https://qyon.com/br/blog/feed/",
    },
}

RSS_CONHECIDOS = {
    "Sieg":    "https://www.sieg.com/blog/feed/",
    "Qive":    "https://qive.com.br/blog/feed/",
    "QYON":    "https://qyon.com/br/blog/feed/",
    "Autmais": "https://www.autmais.com.br/feed/",
    "Vistax":  "https://www.vistaxtech.com/blog/feed/",
}

META_TOKEN = st.secrets.get("META_ACCESS_TOKEN", "")

# ─── Load slow data once per session (Reclame Aqui — 14 calls) ───────────────
if "ra_loaded" not in st.session_state:
    st.session_state.ra_loaded = False
    st.session_state.ra_data = []

if "rss_loaded" not in st.session_state:
    st.session_state.rss_loaded = False
    st.session_state.rss_data = []

# ─── Header ───────────────────────────────────────────────────────────────────
st.title("🔍 Inteligência de Concorrentes — Fiscal.IO")
st.caption(f"14 concorrentes monitorados · {datetime.now().strftime('%d/%m/%Y %H:%M')}")

tab_rep, tab_site, tab_conteudo, tab_meta = st.tabs([
    "⭐ Avaliações",
    "💰 Preços & Sites",
    "📝 Conteúdo & Features",
    "🎯 Meta Ads",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Avaliações (Reclame Aqui + G2 + Capterra)
# ══════════════════════════════════════════════════════════════════════════════
with tab_rep:
    st.subheader("Avaliações e reputação")

    # ── Reclame Aqui ──────────────────────────────────────────────────────────
    st.markdown("### Reclame Aqui")
    if not st.session_state.ra_loaded:
        st.info("Clique para carregar os dados de todos os concorrentes.")
        if st.button("📊 Carregar Reclame Aqui", key="btn_ra_load"):
            results = []
            prog = st.progress(0)
            status_txt = st.empty()
            for i, (nome, info) in enumerate(CONCORRENTES.items()):
                status_txt.text(f"Consultando {nome}…")
                data = get_reclameaqui(nome)
                if data:
                    total = data["total"] or 0
                    resp = data["respondidas"] or 0
                    pct = f"{round(int(resp) / int(total) * 100)}%" if int(total) > 0 else "—"
                    results.append({
                        "Concorrente": nome,
                        "Score RA": data["score"],
                        "Reclamações": total,
                        "Respondidas": resp,
                        "% Resp.": pct,
                        "Perfil RA": data["url"],
                    })
                else:
                    q = requests.utils.quote(nome)
                    results.append({
                        "Concorrente": nome,
                        "Score RA": "Sem perfil",
                        "Reclamações": "—",
                        "Respondidas": "—",
                        "% Resp.": "—",
                        "Perfil RA": f"https://www.reclameaqui.com.br/busca/?q={q}",
                    })
                prog.progress((i + 1) / len(CONCORRENTES))
                time.sleep(0.2)
            status_txt.empty()
            prog.empty()
            st.session_state.ra_data = results
            st.session_state.ra_loaded = True
            st.rerun()
    else:
        df = pd.DataFrame(st.session_state.ra_data)
        st.dataframe(
            df[["Concorrente", "Score RA", "Reclamações", "Respondidas", "% Resp.", "Perfil RA"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score RA": st.column_config.NumberColumn("Score RA", format="%.1f"),
                "Perfil RA": st.column_config.LinkColumn("Perfil RA", display_text="Ver perfil ↗"),
            },
        )

        if st.button("🔄 Recarregar RA", key="btn_ra_reload"):
            get_reclameaqui.clear()
            st.session_state.ra_loaded = False
            st.session_state.ra_data = []
            st.rerun()

    # ── G2 & Capterra ──────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### G2 & Capterra")
    st.caption(
        "Links para os perfis de cada concorrente nas principais plataformas de review B2B. "
        "Os que ainda não têm perfil confirmado vão para a busca da plataforma."
    )

    g2_rows = []
    for nome, info in CONCORRENTES.items():
        g2_url = info.get("g2") or f"https://www.g2.com/search#q={requests.utils.quote(nome)}"
        cap_url = info.get("capterra") or f"https://www.capterra.com.br/search#q={requests.utils.quote(nome)}"
        g2_rows.append({"Concorrente": nome, "G2": g2_url, "Capterra": cap_url})

    df_g2 = pd.DataFrame(g2_rows)
    st.dataframe(
        df_g2,
        use_container_width=True,
        hide_index=True,
        column_config={
            "G2": st.column_config.LinkColumn("G2", display_text="Abrir no G2 ↗"),
            "Capterra": st.column_config.LinkColumn("Capterra", display_text="Abrir no Capterra ↗"),
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Preços & Sites
# ══════════════════════════════════════════════════════════════════════════════
with tab_site:
    st.subheader("Planos e preços dos concorrentes")

    # ── Tabela de links diretos (sempre visível) ───────────────────────────────
    pricing_rows = []
    for nome, info in CONCORRENTES.items():
        p_url = info.get("pricing_url") or info["url"]
        pricing_rows.append({"Concorrente": nome, "Página de preços": p_url})
    df_pricing = pd.DataFrame(pricing_rows)
    st.dataframe(
        df_pricing,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Página de preços": st.column_config.LinkColumn("Página de preços", display_text="Abrir ↗"),
        },
    )

    # ── Análise individual ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Análise individual")

    empresa_site = st.selectbox("Concorrente", list(CONCORRENTES.keys()), key="site_emp")
    c = CONCORRENTES[empresa_site]
    pricing_url = c.get("pricing_url") or c["url"]

    with st.spinner(f"Carregando {empresa_site}…"):
        html, status = fetch_page(pricing_url)

    if html is None:
        st.error(f"Não foi possível acessar {empresa_site}: {status}")
    else:
        info_page = extract_page_info(html)
        cur_hash = page_hash(html)

        # Baselines: arquivo persistido + session_state como fallback
        baselines = load_baselines()
        if empresa_site not in baselines and empresa_site not in st.session_state.get("auto_baselines", {}):
            # Auto-cria baseline na primeira visita (mantido na sessão)
            if "auto_baselines" not in st.session_state:
                st.session_state.auto_baselines = {}
            st.session_state.auto_baselines[empresa_site] = {
                "hash": cur_hash, "data": datetime.now().isoformat()[:10], "snippets": info_page["snippets"],
            }

        # Pega o baseline (arquivo > session)
        baseline = baselines.get(empresa_site) or st.session_state.get("auto_baselines", {}).get(empresa_site)

        # Cabeçalho com link
        col_h, col_link = st.columns([4, 1])
        col_h.markdown(f"**{empresa_site}** — [{pricing_url}]({pricing_url})")
        col_link.markdown(f"[Abrir ↗]({pricing_url})")

        # Metadados da página (sempre disponível, mesmo em sites JS)
        if info_page["title"]:
            st.markdown(f"**Título da página:** {info_page['title']}")
        if info_page["description"]:
            st.markdown(f"**Descrição:** {info_page['description']}")

        # Status de mudança
        if baseline:
            if baseline["hash"] == cur_hash:
                st.success(f"✅ Sem alterações desde {baseline['data'][:10]}")
            else:
                st.warning(f"⚠️ **MUDANÇA DETECTADA** desde {baseline['data'][:10]} — acesse a página para ver o que mudou")

        # Snippets de preço (bonus quando disponível)
        if info_page["snippets"]:
            with st.expander(f"📋 {len(info_page['snippets'])} trechos com preços/planos encontrados no HTML"):
                for s in info_page["snippets"]:
                    st.text(s)
        else:
            st.caption("Preços não disponíveis no HTML estático (site provavelmente usa JavaScript). Use o link acima para ver os valores.")

        # Salvar baseline persistente
        if st.button("💾 Salvar baseline permanente", key="btn_save_bl"):
            baselines[empresa_site] = {
                "hash": cur_hash,
                "url": pricing_url,
                "data": datetime.now().isoformat(),
                "snippets": info_page["snippets"],
            }
            save_baselines(baselines)
            st.success(f"✅ Baseline salvo para {empresa_site}")

    # ── Detectar mudanças em todos ─────────────────────────────────────────────
    st.markdown("---")
    if st.button("📊 Escanear TODOS — detectar mudanças", key="btn_all_sites"):
        baselines = load_baselines()
        auto_bl = st.session_state.get("auto_baselines", {})
        results = []
        prog = st.progress(0)
        txt = st.empty()
        for i, (nome, info) in enumerate(CONCORRENTES.items()):
            txt.text(f"Verificando {nome}…")
            p_url = info.get("pricing_url") or info["url"]
            html_all, _ = fetch_page(p_url)
            cur = page_hash(html_all) if html_all else None
            bl = baselines.get(nome) or auto_bl.get(nome)
            if not cur:
                icone = "❌ Erro de acesso"
            elif not bl:
                icone = "⚪ Sem baseline (visite a aba individual)"
            elif bl.get("hash") == cur:
                icone = "✅ Sem mudanças"
            else:
                icone = "⚠️ MUDOU"
            results.append({
                "Concorrente": nome,
                "Status": icone,
                "Baseline": bl.get("data", "—")[:10] if bl else "—",
            })
            prog.progress((i + 1) / len(CONCORRENTES))
            time.sleep(0.3)
        txt.empty()
        prog.empty()
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Conteúdo & Features
# ══════════════════════════════════════════════════════════════════════════════
with tab_conteudo:
    st.subheader("Conteúdo e novidades dos concorrentes")

    # Auto-load known RSS feeds once per session
    if not st.session_state.rss_loaded:
        all_entries = []
        for nome, info in CONCORRENTES.items():
            feed_url = info.get("rss") or RSS_CONHECIDOS.get(nome)
            if feed_url:
                ents = get_rss_entries(feed_url, max_items=5)
                for e in ents:
                    e["Empresa"] = nome
                    all_entries.append(e)
        st.session_state.rss_data = all_entries
        st.session_state.rss_loaded = True

    if st.session_state.rss_data:
        df = pd.DataFrame(st.session_state.rss_data)[["Empresa", "title", "published", "link"]]
        df.columns = ["Empresa", "Título", "Publicado", "Link"]
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(
            f"Feeds com dados: "
            + ", ".join(sorted(set(e["Empresa"] for e in st.session_state.rss_data)))
        )
    else:
        st.info("Nenhum feed retornou conteúdo no momento.")

    if st.button("🔄 Recarregar feeds", key="btn_reload_feeds"):
        get_rss_entries.clear()
        st.session_state.rss_loaded = False
        st.session_state.rss_data = []
        st.rerun()

    # ── Changelogs / Páginas de novidades ─────────────────────────────────────
    st.markdown("---")
    st.markdown("### Páginas de novidades e changelog")
    st.caption("Links para páginas de updates/features dos concorrentes.")

    chg_rows = []
    for nome, info in CONCORRENTES.items():
        changelog = info.get("changelog")
        blog_url = info["url"].rstrip("/") + "/blog"
        chg_rows.append({
            "Concorrente": nome,
            "Changelog / Novidades": changelog or "—",
            "Blog": blog_url,
        })
    df_chg = pd.DataFrame(chg_rows)
    st.dataframe(df_chg, use_container_width=True, hide_index=True)

    # ── Busca individual ───────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("🔍 Descobrir feed de concorrente sem RSS cadastrado"):
        empresa_cont = st.selectbox("Concorrente", list(CONCORRENTES.keys()), key="cont_emp")
        if st.button("Descobrir", key="btn_cont"):
            c = CONCORRENTES[empresa_cont]
            rss_url = c.get("rss") or RSS_CONHECIDOS.get(empresa_cont)
            with st.spinner(f"Buscando…"):
                entries = []
                source = None
                if rss_url:
                    entries = get_rss_entries(rss_url)
                    source = rss_url
                if not entries:
                    for path in ["/feed", "/rss", "/blog/feed/", "/feed/"]:
                        try:
                            r2 = requests.get(c["url"].rstrip("/") + path, headers=HEADERS, timeout=8)
                            if r2.status_code == 200:
                                feed2 = feedparser.parse(r2.text)
                                if feed2.entries:
                                    entries = [
                                        {"title": e.get("title", ""), "link": e.get("link", ""), "published": (e.get("published") or "")[:10]}
                                        for e in feed2.entries[:6]
                                    ]
                                    source = path
                                    break
                        except Exception:
                            continue
            if entries:
                st.success(f"{len(entries)} publicações encontradas · `{source}`")
                for e in entries:
                    pub = f" · {e['published']}" if e["published"] else ""
                    st.markdown(f"- [{e['title']}]({e['link']}){pub}")
            else:
                st.info(f"Feed não localizado automaticamente. [Abrir blog ↗]({c['url'].rstrip('/')}/blog)")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Meta Ads
# ══════════════════════════════════════════════════════════════════════════════
with tab_meta:
    st.subheader("Anúncios ativos no Meta (Facebook / Instagram)")

    empresa_sel = st.selectbox("Concorrente", list(CONCORRENTES.keys()), key="meta_emp", disabled=not META_TOKEN)
    btn_meta = st.button("🔍 Buscar anúncios ativos", key="btn_meta", disabled=not META_TOKEN)

    if not META_TOKEN:
        st.info(
            "🔧 **Integração em configuração.** "
            "A busca automática ficará disponível após configurar o `META_ACCESS_TOKEN` nos Secrets do Streamlit Cloud."
        )
    elif btn_meta:
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

    # Links diretos sempre visíveis
    st.markdown("---")
    st.markdown("**Links diretos na Ad Library (sem token):**")
    cols = st.columns(4)
    for i, (nome, info) in enumerate(CONCORRENTES.items()):
        q = info["meta_search"].replace(" ", "%20")
        link = (
            f"https://www.facebook.com/ads/library/"
            f"?active_status=active&ad_type=all&country=BR"
            f"&q={q}&search_type=keyword_unordered"
        )
        cols[i % 4].markdown(f"[{nome}]({link})")
