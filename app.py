import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from supabase import create_client, Client

# Configuración de la página de Streamlit
st.set_page_config(
    page_title="Dashboard de Ventas IA",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Dashboard de Ventas IA")

# 1. Lectura de Credenciales de Supabase desde st.secrets
def get_supabase_credentials():
    url = None
    key = None

    # Intentar obtener de la raíz de st.secrets
    try:
        url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase_url")
        key = st.secrets.get("SUPABASE_KEY") or st.secrets.get("supabase_key")
    except Exception:
        pass

    # Intentar obtener desde una sección específica [supabase]
    if not url or not key:
        try:
            if "supabase" in st.secrets:
                sub_sec = st.secrets["supabase"]
                if hasattr(sub_sec, "get"):
                    if not url:
                        url = sub_sec.get("url") or sub_sec.get("SUPABASE_URL") or sub_sec.get("supabase_url")
                    if not key:
                        key = sub_sec.get("key") or sub_sec.get("SUPABASE_KEY") or sub_sec.get("supabase_key")
                elif isinstance(sub_sec, dict):
                    if not url:
                        url = sub_sec.get("url") or sub_sec.get("SUPABASE_URL")
                    if not key:
                        key = sub_sec.get("key") or sub_sec.get("SUPABASE_KEY")
        except Exception:
            pass

    return url, key

supabase_url, supabase_key = get_supabase_credentials()

# Mostrar error explícito en pantalla si faltan credenciales
if not supabase_url or not supabase_key:
    st.error("""
    ❌ **Error de Configuración**: No se encontraron las credenciales de Supabase en `st.secrets`.

    Por favor, asegúrate de configurar las variables `SUPABASE_URL` y `SUPABASE_KEY` (o dentro de una sección `[supabase]`) en los Secrets de Streamlit.
    """)
    st.stop()

# 2. Inicialización del Cliente de Supabase
@st.cache_resource
def init_supabase(url, key):
    try:
        return create_client(url, key)
    except Exception as e:
        st.error(f"❌ **Error al inicializar el cliente de Supabase**: {e}")
        st.stop()

client = init_supabase(supabase_url, supabase_key)

# 3. Funciones de Aplanamiento y Carga de Datos Relacionales (Sin Fallback)
def flatten_sales(data):
    """Aplatana el JSON resultante de ventas de modelo relacional."""
    records = []
    for row in data:
        prod = row.get("productos") or {}
        chan = row.get("canales") or {}
        reg = row.get("regiones") or {}

        if isinstance(prod, list) and len(prod) > 0:
            prod = prod[0]
        if isinstance(chan, list) and len(chan) > 0:
            chan = chan[0]
        if isinstance(reg, list) and len(reg) > 0:
            reg = reg[0]

        record = {
            "id": row.get("id"),
            "fecha": row.get("fecha"),
            "cantidad": row.get("cantidad"),
            "precio_unitario_venta": row.get("precio_unitario_venta"),
            "descuento": row.get("descuento_aplicado") or 0.0,
            "ventas": row.get("monto_total") or 0.0,
            "region_id": row.get("region_id"),
            "canal_id": row.get("canal_id"),
            "producto": prod.get("nombre") or "Desconocido",
            "categoria": prod.get("categoria") or "Sin Categoría",
            "canal": chan.get("nombre") or "Desconocido",
            "region": reg.get("nombre") or "Desconocido"
        }
        records.append(record)
    df = pd.DataFrame(records)
    if not df.empty and 'fecha' in df.columns:
        df['fecha'] = pd.to_datetime(df['fecha'])
    return df

def flatten_budget(data):
    """Aplatana el JSON resultante de presupuestos utilizando anio y mes."""
    records = []
    for row in data:
        record = {
            "id": row.get("id"),
            "anio": row.get("anio"),
            "mes": row.get("mes"),
            "presupuesto": row.get("monto_presupuestado") or 0.0,
            "region_id": row.get("region_id"),
            "canal_id": row.get("canal_id")
        }
        records.append(record)

    df = pd.DataFrame(records)
    if not df.empty:
        # Crear la columna sintética fecha combinando anio y mes
        df['fecha'] = pd.to_datetime(
            df['anio'].astype(str) + '-' + df['mes'].astype(str).str.zfill(2) + '-01'
        )
    return df

@st.cache_data
def load_all_data():
    """Consulta la tabla ventas y presupuestos con sus relaciones directas de dimensiones."""
    df_sales = None
    df_budget = None

    # Consulta Principal de Ventas
    try:
        sales_resp = client.table("ventas").select(
            "id, fecha, cantidad, precio_unitario_venta, descuento_aplicado, monto_total, "
            "region_id, canal_id, "
            "productos(nombre, categoria), "
            "canales(nombre), "
            "regiones(nombre)"
        ).execute()
        if sales_resp.data:
            df_sales = flatten_sales(sales_resp.data)
    except Exception as e:
        st.error(f"❌ **Error al consultar la tabla 'ventas'**: {e}")
        st.stop()

    # Consulta de Presupuestos adaptada al esquema real
    try:
        budget_resp = client.table("presupuestos").select(
            "id, anio, mes, monto_presupuestado, region_id, canal_id"
        ).execute()
        if budget_resp.data:
            df_budget = flatten_budget(budget_resp.data)
    except Exception as e:
        st.error(f"❌ **Error al consultar la tabla 'presupuestos'**: {e}")
        st.stop()

    if df_sales is None or df_sales.empty:
        st.error("❌ **Error de Datos**: No se pudieron obtener registros válidos de la tabla 'ventas'.")
        st.stop()

    if df_budget is None:
        df_budget = pd.DataFrame(columns=["id", "fecha", "presupuesto", "canal_id", "region_id"])

    # Mapeo de nombres de canal y región en presupuestos a partir de las ventas
    if not df_budget.empty:
        region_map = dict(zip(df_sales['region_id'].dropna(), df_sales['region'].dropna()))
        canal_map = dict(zip(df_sales['canal_id'].dropna(), df_sales['canal'].dropna()))

        df_budget['region'] = df_budget['region_id'].map(region_map).fillna("Desconocido")
        df_budget['canal'] = df_budget['canal_id'].map(canal_map).fillna("Desconocido")
    else:
        df_budget['region'] = pd.Series(dtype=str)
        df_budget['canal'] = pd.Series(dtype=str)

    return df_sales, df_budget

# Cargar los datos directamente desde PostgreSQL (Sin Fallback)
df_sales, df_budget = load_all_data()

# 4. Barra Lateral (Sidebar) de Filtros
st.sidebar.header("Filtros de Datos")
st.sidebar.success("⚡ Conectado a Supabase PostgreSQL")

# Filtro de Rango de Fechas (por defecto abarcando todo el periodo disponible en ventas)
min_date = df_sales['fecha'].min().date()
max_date = df_sales['fecha'].max().date()

date_range = st.sidebar.date_input(
    "Selecciona Rango de Fechas",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date
)

# Control robusto para rango de fechas incompleto durante selección del usuario
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = date_range[0] if isinstance(date_range, (list, tuple)) else date_range
    end_date = start_date

# Selección múltiple por Región
all_regions = sorted(df_sales['region'].unique().tolist())
selected_regions = st.sidebar.multiselect(
    "Región",
    options=all_regions,
    default=all_regions
)

# Selección múltiple por Canal de Venta
all_channels = sorted(df_sales['canal'].unique().tolist())
selected_channels = st.sidebar.multiselect(
    "Canal de Venta",
    options=all_channels,
    default=all_channels
)

# Aplicar Filtros a Ventas y Presupuestos
start_dt = pd.to_datetime(start_date)
end_dt = pd.to_datetime(end_date)

filtered_sales = df_sales[
    (df_sales['fecha'] >= start_dt) &
    (df_sales['fecha'] <= end_dt) &
    (df_sales['region'].isin(selected_regions)) &
    (df_sales['canal'].isin(selected_channels))
]

filtered_budget = df_budget[
    (df_budget['fecha'] >= start_dt) &
    (df_budget['fecha'] <= end_dt) &
    (df_budget['region'].isin(selected_regions)) &
    (df_budget['canal'].isin(selected_channels))
] if not df_budget.empty else pd.DataFrame(columns=df_budget.columns)

# Formateadores auxiliares para monedas y números
def format_currency(value):
    return f"${value:,.2f}"

def format_number(value):
    return f"{value:,}"

# 5. Manejo de estados de 0 resultados y visualizaciones
if filtered_sales.empty:
    st.warning("⚠️ No hay resultados disponibles para los filtros seleccionados. Por favor, ajusta los criterios en la barra lateral.")

    # Tarjetas de KPIs vacías
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Ventas Totales", "$0.00")
    with col2:
        st.metric("Total de Transacciones", "0")
    with col3:
        st.metric("Ticket Promedio", "$0.00")
    with col4:
        st.metric("Descuentos Aplicados", "$0.00")
else:
    # Cálculos de Métricas KPIs
    total_sales = filtered_sales['ventas'].sum()
    total_transactions = len(filtered_sales)
    avg_ticket = filtered_sales['ventas'].mean() if total_transactions > 0 else 0
    total_discounts = filtered_sales['descuento'].sum()

    # Mostrar Tarjetas de KPIs (st.metric)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Ventas Totales", format_currency(total_sales))
    with col2:
        st.metric("Total de Transacciones", format_number(total_transactions))
    with col3:
        st.metric("Ticket Promedio", format_currency(avg_ticket))
    with col4:
        st.metric("Descuentos Aplicados", format_currency(total_discounts))

    st.markdown("---")

    # Visualizaciones con Plotly
    col_left, col_right = st.columns(2)

    with col_left:
        # Gráfico de Líneas: Tendencia de ventas mensual vs. Presupuesto (Budget)
        sales_monthly = filtered_sales.copy()
        sales_monthly['Mes'] = sales_monthly['fecha'].dt.strftime('%Y-%m')
        sales_grouped = sales_monthly.groupby('Mes')['ventas'].sum().reset_index()

        if not filtered_budget.empty:
            budget_monthly = filtered_budget.copy()
            budget_monthly['Mes'] = budget_monthly['fecha'].dt.strftime('%Y-%m')
            budget_grouped = budget_monthly.groupby('Mes')['presupuesto'].sum().reset_index()
        else:
            budget_grouped = pd.DataFrame(columns=['Mes', 'presupuesto'])

        # Combinar Ventas y Presupuesto por Mes
        merged_trend = pd.merge(sales_grouped, budget_grouped, on='Mes', how='outer').fillna(0)
        merged_trend = merged_trend.sort_values('Mes')

        fig_line = px.line(
            merged_trend,
            x='Mes',
            y=['ventas', 'presupuesto'],
            labels={'value': 'Monto ($)', 'variable': 'Métrica', 'Mes': 'Mes'},
            title='Tendencia de Ventas Mensual vs. Presupuesto (Budget)',
            markers=True
        )

        # Renombrar leyendas para mejor legibilidad
        new_names = {'ventas': 'Ventas Reales', 'presupuesto': 'Presupuesto'}
        fig_line.for_each_trace(lambda t: t.update(name = new_names.get(t.name, t.name)))

        fig_line.update_layout(
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_line, use_container_width=True)

    with col_right:
        # Gráfico de Barras: Top 5 de productos más vendidos en el periodo seleccionado
        product_grouped = filtered_sales.groupby('producto')['ventas'].sum().reset_index()
        top_products = product_grouped.sort_values('ventas', ascending=False).head(5)

        fig_bar = px.bar(
            top_products,
            x='ventas',
            y='producto',
            orientation='h',
            labels={'ventas': 'Ventas Totales ($)', 'producto': 'Producto'},
            title='Top 5 Productos más Vendidos',
            color='ventas',
            color_continuous_scale='blues'
        )
        # Ordenar barras para que el de mayor venta aparezca arriba
        fig_bar.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            coloraxis_showscale=False
        )
        st.plotly_chart(fig_bar, use_container_width=True)
