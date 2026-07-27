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

# 1. Configuración de Conexión a Supabase con Fallback a datos simulados
@st.cache_resource
def init_supabase():
    try:
        # Intenta obtener credenciales desde st.secrets
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception:
        # Falla silenciosa para habilitar fallback de desarrollo local
        return None

@st.cache_data
def generate_mock_data():
    """Genera un dataset de simulación robusto y realista."""
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", end="2024-12-31", freq="D")

    regions = ['Norte', 'Sur', 'Centro', 'Este', 'Oeste']
    channels = ['Online', 'Retail', 'Mayorista', 'Distribuidor']
    products = ['Producto A', 'Producto B', 'Producto C', 'Producto D', 'Producto E', 'Producto F', 'Producto G']

    num_rows = 1500

    data = {
        'fecha': pd.to_datetime(np.random.choice(dates, size=num_rows)),
        'region': np.random.choice(regions, size=num_rows),
        'canal_venta': np.random.choice(channels, size=num_rows),
        'producto': np.random.choice(products, size=num_rows, p=[0.3, 0.2, 0.15, 0.15, 0.1, 0.05, 0.05]),
        'ventas': np.round(np.random.exponential(scale=500, size=num_rows) + np.random.randint(50, 200, size=num_rows), 2),
        'descuento': np.round(np.random.beta(a=2, b=5, size=num_rows) * 100, 2),
    }

    df = pd.DataFrame(data)
    # Generar presupuesto correspondiente, cercano a ventas para comparación visual atractiva
    df['presupuesto'] = np.round(df['ventas'] * np.random.uniform(0.85, 1.15, size=num_rows), 2)

    return df.sort_values('fecha').reset_index(drop=True)

@st.cache_data
def load_data():
    client = init_supabase()
    if client is None:
        return generate_mock_data(), False

    try:
        # Intentar consultar tabla 'ventas'
        response = client.table("ventas").select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df = map_columns(df)
            return df, True
    except Exception:
        pass

    try:
        # Intentar consultar tabla 'sales'
        response = client.table("sales").select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df = map_columns(df)
            return df, True
    except Exception:
        pass

    return generate_mock_data(), False

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

# Carga de datos
df, using_supabase = load_data()

# 2. Barra Lateral (Sidebar) de Filtros
st.sidebar.header("Filtros de Datos")

if using_supabase:
    st.sidebar.success("⚡ Conectado a Supabase")
else:
    st.sidebar.info("ℹ️ Usando Datos de Simulación (Fallback)")

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

# 3. Manejo de estados de 0 resultados y visualizaciones
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
