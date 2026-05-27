import streamlit as st
import requests
import pandas as pd
import folium
from folium.plugins import HeatMap, MarkerCluster
from bs4 import BeautifulSoup
from streamlit_folium import st_folium
from datetime import datetime
from pathlib import Path

# ── Configuração da página ────────────────────────────────────────
st.set_page_config(
    page_title="Focos de Queimadas – MG",
    page_icon="🔥",
    layout="wide"
)

URL_BASE = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/10min/"
MAX_ARQ  = 30
NOMES_MG = {"minas gerais", "mg", "minas_gerais"}

# ── Funções ───────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def listar_servidor():
    """Lista CSVs disponíveis no servidor INPE. Cache de 60s."""
    r = requests.get(URL_BASE, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    return sorted(
        {a["href"] for a in soup.find_all("a", href=True)
         if a["href"].endswith(".csv") and not a["href"].startswith(("?", "/"))}
    )

@st.cache_data(ttl=600, show_spinner=False)
def carregar_csv(nome_arquivo):
    """Baixa e retorna o CSV como DataFrame. Cache de 10min."""
    r = requests.get(URL_BASE + nome_arquivo, timeout=30)
    from io import StringIO
    df = pd.read_csv(StringIO(r.text))
    df.columns = [c.lower().strip() for c in df.columns]
    return df

def filtrar_mg(df):
    col = next((c for c in df.columns if "estado" in c), None)
    if not col:
        return df
    return df[df[col].str.lower().str.strip().isin(NOMES_MG)].copy()

def gerar_mapa(df_mg, arquivo_nome):
    lat_col = next((c for c in df_mg.columns if "lat" in c), None)
    lon_col = next((c for c in df_mg.columns if "lon" in c or "lng" in c), None)
    frp_col = next((c for c in df_mg.columns if "frp" in c), None)

    if not lat_col or not lon_col:
        return None

    df_mg[lat_col] = pd.to_numeric(df_mg[lat_col], errors="coerce")
    df_mg[lon_col] = pd.to_numeric(df_mg[lon_col], errors="coerce")
    df_mg = df_mg.dropna(subset=[lat_col, lon_col])

    m = folium.Map(location=[-18.5, -44.5], zoom_start=6, tiles="CartoDB dark_matter")

    if len(df_mg) > 0:
        # Heatmap
        if frp_col:
            df_mg[frp_col] = pd.to_numeric(df_mg[frp_col], errors="coerce").fillna(1)
            heat_data = df_mg[[lat_col, lon_col, frp_col]].values.tolist()
        else:
            heat_data = df_mg[[lat_col, lon_col]].assign(w=1).values.tolist()

        HeatMap(
            heat_data, radius=15, blur=12, max_zoom=12,
            gradient={"0.2": "#ffffb2", "0.5": "#fd8d3c", "0.8": "#e31a1c", "1": "#800026"}
        ).add_to(m)

        # Marcadores clicáveis
        cluster = MarkerCluster(name="Focos individuais", show=False)
        for _, row in df_mg.iterrows():
            linhas = ['<b style="color:#ff8c42">🔥 Foco – MG</b>']
            for campo in ["municipio", "municipio_nome", "bioma", "satelite",
                          "satellite", "data_hora_gmt", "datahora"]:
                if campo in df_mg.columns and pd.notna(row.get(campo)):
                    linhas.append(f"<b>{campo}:</b> {row[campo]}")
            if frp_col and pd.notna(row.get(frp_col)):
                linhas.append(f"<b>FRP:</b> {row[frp_col]:.1f} MW")
            folium.CircleMarker(
                [row[lat_col], row[lon_col]],
                radius=5, color="#ff6b35", fill=True, fill_opacity=0.8,
                popup=folium.Popup("<br>".join(linhas), max_width=260)
            ).add_to(cluster)
        cluster.add_to(m)

    folium.TileLayer("OpenStreetMap", name="Mapa").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="ESRI", name="Satélite"
    ).add_to(m)
    folium.LayerControl().add_to(m)
    return m

# ── Interface ─────────────────────────────────────────────────────
st.title("🔥 Focos de Queimadas — Minas Gerais")
st.caption("Dados: INPE · Atualização automática a cada 10 minutos")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configurações")

    auto_refresh = st.toggle("Atualização automática (60s)", value=True)
    st.divider()

    with st.spinner("Buscando arquivos no servidor..."):
        try:
            lista = listar_servidor()
            ultimos = lista[-MAX_ARQ:][::-1]  # 30 mais recentes, do novo pro antigo
        except Exception as e:
            st.error(f"Erro ao conectar no servidor INPE: {e}")
            st.stop()

    arquivo_sel = st.selectbox(
        "Arquivo (mais recente primeiro):",
        options=ultimos,
        index=0
    )

    st.divider()
    st.markdown("**Como usar:**")
    st.markdown("- Selecione um arquivo acima")
    st.markdown("- Ative camadas no canto do mapa")
    st.markdown("- Clique num foco para detalhes")
    st.markdown("- *Focos individuais* aparece no zoom")

# Carrega dados
with st.spinner(f"Carregando {arquivo_sel}..."):
    try:
        df = carregar_csv(arquivo_sel)
    except Exception as e:
        st.error(f"Erro ao carregar arquivo: {e}")
        st.stop()

df_mg = filtrar_mg(df)

# Métricas
total_mg    = len(df_mg)
total_brasil = len(df)
lat_col = next((c for c in df_mg.columns if "lat" in c), None)
municipios = 0
biomas     = 0
if lat_col:
    col_mun = next((c for c in df_mg.columns if "municipio" in c), None)
    col_bio = "bioma" if "bioma" in df_mg.columns else None
    municipios = df_mg[col_mun].nunique() if col_mun else 0
    biomas     = df_mg[col_bio].nunique() if col_bio else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("🔥 Focos em MG",     f"{total_mg:,}")
col2.metric("🏙️ Municípios",      municipios)
col3.metric("🌿 Biomas",          biomas)
col4.metric("🇧🇷 Total Brasil",   f"{total_brasil:,}")

st.divider()

# Mapa
if total_mg == 0:
    st.info("ℹ️ Nenhum foco registrado em MG neste arquivo.")
    m = gerar_mapa(df_mg, arquivo_sel)
else:
    m = gerar_mapa(df_mg.copy(), arquivo_sel)

if m:
    st_folium(m, width="100%", height=600, returned_objects=[])

# Tabela de dados (expansível)
with st.expander(f"📋 Ver dados brutos ({total_mg} focos em MG)"):
    colunas_show = [c for c in df_mg.columns
                    if any(k in c for k in ["lat","lon","municipio","estado","bioma","frp","data","satelite"])]
    st.dataframe(
        df_mg[colunas_show] if colunas_show else df_mg,
        use_container_width=True,
        height=300
    )
    st.download_button(
        "⬇️ Baixar CSV filtrado (MG)",
        data=df_mg.to_csv(index=False).encode("utf-8"),
        file_name=f"focos_mg_{arquivo_sel}",
        mime="text/csv"
    )

# Footer
st.divider()
st.caption(f"Fonte: INPE – {URL_BASE} · Última atualização da página: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

# Auto-refresh
if auto_refresh:
    import time
    time.sleep(60)
    st.rerun()
