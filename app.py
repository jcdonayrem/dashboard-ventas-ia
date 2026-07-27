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

# 1. Lectura de Credenciales de Supabase
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
                # En Streamlit, st.secrets["supabase"] puede ser AttrDict o dict
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

# Intentar obtener las credenciales
supabase_url, supabase_key = get_supabase_credentials()

# Mostrar error explícito en pantalla si faltan credenciales
if not supabase_url or not supabase_key:
    st.error("""
    ❌ **Error de Configuración**: No se encontraron las credenciales de Supabase en `st.secrets`.

    Por favor, asegúrate de configurar las variables `SUPABASE_URL` y `SUPABASE_KEY` (o dentro de una sección `[supabase]`) en los Secrets de Streamlit.
    """)
    st.stop()

# 2. Inicialización del Cliente e Integración de Datos
@st.cache_resource
def init_supabase(url, key):
    try:
        return create_client(url, key)
    except Exception as e:
        st.error(f"❌ **Error al inicializar el cliente de Supabase**: {e}")
        st.stop()

# Inicialización
client = init_supabase(supabase_url, supabase_key)

def map_columns(df):
    """Estandariza los nombres de las columnas de la base de datos."""
    column_mapping = {
        'monto': 'ventas',
        'sales': 'ventas',
        'amount': 'ventas',
        'budget': 'presupuesto',
        'discount': 'descuento',
        'product': 'producto',
        'sales_channel': 'canal_venta',
        'canal': 'canal_venta',
        'date': 'fecha'
    }
    df = df.rename(columns=column_mapping)
    if 'fecha' in df.columns:
        df['fecha'] = pd.to_datetime(df['fecha'])
    return df

@st.cache_data
def load_data_from_supabase():
    df = None
    last_error = None

    # 1. Intentar consultar tabla 'sales'
    try:
        response = client.table("sales").select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df = map_columns(df)
            return df
    except Exception as e:
        last_error = e

    # 2. Intentar consultar tabla 'ventas'
    try:
        response = client.table("ventas").select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df = map_columns(df)
            return df
    except Exception as e:
        last_error = e

    # Si no se pudo obtener de ninguna tabla, mostrar error explícito en pantalla
    st.error(f"""
    ❌ **Error de Consulta de Datos**: No se pudo obtener registros de las tablas 'sales' o 'ventas' en Supabase.

    **Detalle del error:** {last_error}
    """)
    st.stop()

# Cargar los datos directamente desde PostgreSQL
df = load_data_from_supabase()

# 3. Barra Lateral (Sidebar) de Filtros (Sin alerta de Fallback)
st.sidebar.header("Filtros de Datos")
st.sidebar.success("⚡ Conectado a Supabase PostgreSQL")

# Filtro de Rango de Fechas (por defecto abarcando todo el periodo disponible)
min_date = df['fecha'].min().date()
max_date = df['fecha'].max().date()

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
all_regions = sorted(df['region'].unique().tolist())
selected_regions = st.sidebar.multiselect(
    "Región",
    options=all_regions,
    default=all_regions
)

# Selección múltiple por Canal de Venta
all_channels = sorted(df['canal_venta'].unique().tolist())
selected_channels = st.sidebar.multiselect(
    "Canal de Venta",
    options=all_channels,
    default=all_channels
)

# Aplicar Filtros
start_dt = pd.to_datetime(start_date)
end_dt = pd.to_datetime(end_date)

filtered_df = df[
    (df['fecha'] >= start_dt) &
    (df['fecha'] <= end_dt) &
    (df['region'].isin(selected_regions)) &
    (df['canal_venta'].isin(selected_channels))
]

# Formateadores auxiliares para monedas y números
def format_currency(value):
    return f"${value:,.2f}"

def format_number(value):
    return f"{value:,}"

# 4. Manejo de estados de 0 resultados y visualizaciones
if filtered_df.empty:
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
    total_sales = filtered_df['ventas'].sum()
    total_transactions = len(filtered_df)
    avg_ticket = filtered_df['ventas'].mean() if total_transactions > 0 else 0
    total_discounts = filtered_df['descuento'].sum()

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
        monthly_df = filtered_df.copy()
        monthly_df['Mes'] = monthly_df['fecha'].dt.strftime('%Y-%m')
        monthly_grouped = monthly_df.groupby('Mes')[['ventas', 'presupuesto']].sum().reset_index()
        monthly_grouped = monthly_grouped.sort_values('Mes')

        fig_line = px.line(
            monthly_grouped,
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
        product_grouped = filtered_df.groupby('producto')['ventas'].sum().reset_index()
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
